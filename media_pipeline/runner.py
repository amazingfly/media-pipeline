"""Sequential component runner with explicit commands and resumable checkpoints."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


class PipelineError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_state(path: Path, state: dict) -> None:
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as handle:
        json.dump(state, handle, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def expanded_path(value: str, base: Path) -> Path:
    path = Path(os.path.expandvars(value)).expanduser()
    return (base / path).absolute() if not path.is_absolute() else path.absolute()


def build_plan(config_path: Path, run_dir: Path) -> dict:
    config_path = config_path.resolve()
    config = json.loads(config_path.read_text())
    if not isinstance(config, dict) or config.get('version') != 1:
        raise PipelineError('Pipeline config must be an object with version=1')
    components = config.get('components')
    if not isinstance(components, dict) or not components:
        raise PipelineError('components must be a nonempty object')
    context = {'run_dir': str(run_dir.resolve()), 'config_dir': str(config_path.parent)}
    resolved = {}
    for name, component in components.items():
        if not isinstance(component, dict) or not isinstance(component.get('root'), str):
            raise PipelineError(f'Component {name} needs a root path')
        root = expanded_path(component['root'], config_path.parent)
        interpreter = component.get('python', '.venv/bin/python')
        if not isinstance(interpreter, str) or not interpreter:
            raise PipelineError(f'Component {name} needs a Python executable')
        interpreter = str(expanded_path(interpreter, root)) if '/' in interpreter else interpreter
        resolved[name] = {'root': str(root), 'python': interpreter}
        context.update({f'{name}.root': str(root), f'{name}.python': interpreter})
    stages = config.get('stages')
    if not isinstance(stages, list) or not stages:
        raise PipelineError('stages must be a nonempty list')
    planned = []
    ids = set()
    for stage in stages:
        if not isinstance(stage, dict):
            raise PipelineError('Each stage must be an object')
        stage_id = stage.get('id', '')
        if not isinstance(stage_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', stage_id) or stage_id in ids:
            raise PipelineError(f'Invalid or duplicate stage id: {stage_id!r}')
        ids.add(stage_id)
        name = stage.get('component')
        if name not in resolved:
            raise PipelineError(f'{stage_id}: unknown component {name!r}')
        values = {**context, **resolved[name]}

        def expand(value: str) -> str:
            if not isinstance(value, str):
                raise PipelineError(f'{stage_id}: command, environment, and path values must be strings')
            for key, replacement in values.items():
                value = value.replace('{' + key + '}', replacement)
            return value

        argv = stage.get('argv')
        if not isinstance(argv, list) or not argv:
            raise PipelineError(f'{stage_id}: argv must be a nonempty list')
        cwd = expanded_path(expand(stage.get('cwd', '{root}')), config_path.parent)
        env = stage.get('env', {})
        outputs = stage.get('outputs', [])
        if not isinstance(env, dict) or not isinstance(outputs, list):
            raise PipelineError(f'{stage_id}: env must be an object and outputs a list')
        planned.append({
            'id': stage_id, 'component': name, 'argv': [expand(arg) for arg in argv],
            'cwd': str(cwd), 'env': {key: expand(value) for key, value in env.items()},
            'outputs': [str(expanded_path(expand(output), cwd)) for output in outputs],
        })
    return {'version': 1, 'run_dir': str(run_dir.resolve()), 'components': resolved, 'stages': planned}


def doctor(plan: dict) -> list[str]:
    problems = []
    for stage in plan['stages']:
        if not Path(stage['cwd']).is_dir():
            problems.append(f"{stage['id']}: missing working directory {stage['cwd']}")
        executable = stage['argv'][0]
        if '/' in executable and not Path(executable).is_absolute():
            executable = str(Path(stage['cwd']) / executable)
        if not shutil.which(executable, path=stage['env'].get('PATH', os.environ.get('PATH'))):
            problems.append(f"{stage['id']}: missing executable {executable}")
    return problems


def execute(plan: dict, *, resume: bool = False) -> dict:
    problems = doctor(plan)
    if problems:
        raise PipelineError('\n'.join(problems))
    run_dir = Path(plan['run_dir'])
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / '.pipeline.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PipelineError(f'Another pipeline owns {run_dir}') from exc
        return execute_locked(plan, resume=resume)


def execute_locked(plan: dict, *, resume: bool) -> dict:
    run_dir = Path(plan['run_dir'])
    state_path = run_dir / 'pipeline-state.json'
    fingerprint = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    if state_path.exists():
        if not resume:
            raise PipelineError('Run state exists; use --resume or choose a new --run-dir')
        state = json.loads(state_path.read_text())
        if state.get('plan_sha256') != fingerprint:
            raise PipelineError('Plan changed; choose a new run directory instead of reusing checkpoints')
    else:
        state = {'version': 1, 'plan_sha256': fingerprint, 'started_at': now(), 'stages': {}}
    state['status'] = 'running'
    state.pop('finished_at', None)
    save_state(state_path, state)
    rerun_downstream = False
    for stage in plan['stages']:
        stage_id = stage['id']
        record = state['stages'].get(stage_id, {})
        outputs_exist = all(Path(output).exists() for output in stage['outputs'])
        if resume and not rerun_downstream and record.get('status') == 'complete' and outputs_exist:
            print(f'[{stage_id}] already complete', flush=True)
            continue
        rerun_downstream = True
        # Invalidate downstream checkpoints before execution, including on failure.
        reached = False
        for later in plan['stages']:
            reached = reached or later['id'] == stage_id
            if reached:
                state['stages'].pop(later['id'], None)
        log_path = run_dir / f'{stage_id}.log'
        record = {'status': 'running', 'started_at': now(), 'log': str(log_path)}
        state['stages'][stage_id] = record
        save_state(state_path, state)
        print(f'[{stage_id}] running; log: {log_path}', flush=True)
        try:
            with log_path.open('a') as log:
                log.write(f'\n=== Attempt started {now()} ===\n')
                log.flush()
                result = subprocess.run(stage['argv'], cwd=stage['cwd'],
                    env={**os.environ, 'PYTHONUNBUFFERED': '1', **stage['env']},
                    stdout=log, stderr=subprocess.STDOUT, check=False)
            if result.returncode:
                raise PipelineError(f'{stage_id} exited {result.returncode}; see {log_path}')
            missing = [output for output in stage['outputs'] if not Path(output).exists()]
            if missing:
                raise PipelineError(f'{stage_id} did not produce required outputs: {missing}')
        except (OSError, PipelineError, KeyboardInterrupt) as exc:
            record.update(status='failed', finished_at=now(), error=str(exc))
            state['status'] = 'failed'
            save_state(state_path, state)
            raise
        record.update(status='complete', finished_at=now())
        save_state(state_path, state)
    state.update(status='complete', finished_at=now())
    save_state(state_path, state)
    return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['plan', 'doctor', 'run'])
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args(argv)
    try:
        plan = build_plan(args.config, args.run_dir)
        if args.command == 'plan':
            print(json.dumps(plan, indent=2))
        elif args.command == 'doctor':
            problems = doctor(plan)
            if problems:
                raise PipelineError('\n'.join(problems))
            print(f"Ready: {len(plan['stages'])} stage executables and working directories available")
        else:
            execute(plan, resume=args.resume)
        return 0
    except (OSError, ValueError, PipelineError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
