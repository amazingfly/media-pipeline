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
from media_workspace.config import load_workspace, environment, COMPONENT_ENV
from media_workspace.contracts import snapshot, write_contract, validate_contract, KINDS
from .provenance import capture


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


def build_plan(config_path: Path, run_dir: Path, workspace_path=None) -> dict:
    config_path = config_path.resolve()
    config = json.loads(config_path.read_text())
    if not isinstance(config, dict) or config.get('version') != 1:
        raise PipelineError('Pipeline config must be an object with version=1')
    workspace = load_workspace(workspace_path)
    workspace_env = {key: os.environ.get(key, value) for key, value in environment(workspace).items()}
    components = config.get('components')
    if not isinstance(components, dict) or not components:
        raise PipelineError('components must be a nonempty object')
    context = {'run_dir': str(run_dir.resolve()), 'config_dir': str(config_path.parent)}
    context.update({f'paths.{key}': value for key, value in workspace['paths'].items()})
    resolved = {}
    for name, component in components.items():
        if isinstance(component, dict):
            component = {**workspace['components'].get(name, {}), **component}
        if not isinstance(component, dict) or not isinstance(component.get('root'), str):
            raise PipelineError(f'Component {name} needs a root path')
        root = expanded_path(component['root'], config_path.parent)
        interpreter = component.get('python', '.venv/bin/python')
        if not isinstance(interpreter, str) or not interpreter:
            raise PipelineError(f'Component {name} needs a Python executable')
        interpreter = str(expanded_path(interpreter, root)) if '/' in interpreter else interpreter
        resolved[name] = {'root': str(root), 'python': interpreter}
        context.update({f'{name}.root': str(root), f'{name}.python': interpreter})
    workspace_env.update(environment({'components': {name: item for name, item in resolved.items() if name in COMPONENT_ENV}, 'paths': {}}))
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
        inputs = stage.get('inputs', [])
        if not isinstance(inputs, list):
            raise PipelineError(f'{stage_id}: inputs must be a list')
        contracts = []
        input_contracts = stage.get('input_contracts', [])
        if not isinstance(input_contracts, list):
            raise PipelineError(f'{stage_id}: input_contracts must be a list')
        for contract in input_contracts:
            if not isinstance(contract, dict) or contract.get('kind') not in KINDS or not isinstance(contract.get('path'), str):
                raise PipelineError(f'{stage_id}: invalid input contract')
            contracts.append({'path': str(expanded_path(expand(contract['path']), cwd)), 'kind': contract['kind']})
        artifact = stage.get('artifact')
        if artifact:
            if not isinstance(artifact, dict) or artifact.get('kind') not in KINDS or not isinstance(artifact.get('manifest'), str) or not isinstance(artifact.get('paths'), list) or not artifact['paths']:
                raise PipelineError(f'{stage_id}: artifact needs kind, manifest and nonempty paths')
            artifact = {'kind': artifact['kind'], 'manifest': str(expanded_path(expand(artifact['manifest']), cwd)),
                        'paths': [str(expanded_path(expand(path), cwd)) for path in artifact['paths']]}
        if not isinstance(env, dict) or not isinstance(outputs, list):
            raise PipelineError(f'{stage_id}: env must be an object and outputs a list')
        planned.append({
            'id': stage_id, 'component': name, 'argv': [expand(arg) for arg in argv],
            'cwd': str(cwd), 'env': {**workspace_env, **{key: expand(value) for key, value in env.items()}},
            'inputs': [str(expanded_path(expand(path), cwd)) for path in inputs],
            'input_contracts': contracts, 'artifact': artifact,
            'outputs': [str(expanded_path(expand(output), cwd)) for output in outputs],
        })
    return {'version': 1, 'run_dir': str(run_dir.resolve()), 'components': resolved, 'stages': planned}


def stage_environment(plan, stage):
    env = {**os.environ, 'PYTHONUNBUFFERED': '1', **stage['env']}
    if 'PATH' not in stage['env']:
        interpreter = shutil.which(plan['components'][stage['component']]['python'])
        if interpreter:
            env['PATH'] = str(Path(interpreter).parent) + os.pathsep + env.get('PATH', '')
    return env


def doctor(plan: dict) -> list[str]:
    problems = []
    for stage in plan['stages']:
        if not Path(stage['cwd']).is_dir():
            problems.append(f"{stage['id']}: missing working directory {stage['cwd']}")
        executable = stage['argv'][0]
        if '/' in executable and not Path(executable).is_absolute():
            executable = str(Path(stage['cwd']) / executable)
        if not shutil.which(executable, path=stage_environment(plan, stage).get('PATH')):
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
        state = {'version': 2, 'plan_sha256': fingerprint, 'started_at': now(), 'stages': {}}
    provenance = capture(plan['components'])
    coordinator = capture({'runner': {'root': str(Path(__file__).resolve().parents[1]), 'python': sys.executable}})['runner']
    if resume and state.get('coordinator') and state['coordinator'] != coordinator:
        raise PipelineError('Coordinator source or environment changed; choose a new run directory')
    if resume and state.get('provenance') and state['provenance'] != provenance:
        raise PipelineError('Component source or environment changed; choose a new run directory')
    if resume and state.get('version') != 2:
        raise PipelineError('Unsupported or legacy checkpoint; choose a new run directory')
    state['coordinator'] = coordinator
    state['provenance'] = provenance
    state['plan'] = {'components': plan['components'], 'stages': [
        {**{key: value for key, value in stage.items() if key != 'env'},
         'environment_keys': sorted(stage['env'])} for stage in plan['stages']]}
    state['resume_invariants'] = 'declared inputs, component source and Python environment'
    state['status'] = 'running'
    state.pop('finished_at', None)
    state.pop('error', None)
    save_state(state_path, state)
    rerun_downstream = False
    for stage in plan['stages']:
        stage_id = stage['id']
        record = state['stages'].get(stage_id, {})
        try:
            for contract in stage.get('input_contracts', []):
                validate_contract(json.loads(Path(contract['path']).read_text()), verify=True, expected_kind=contract['kind'])
            inputs = snapshot(stage.get('inputs', []) + [c['path'] for c in stage.get('input_contracts', [])])
        except (ValueError, OSError) as exc:
            state['status'] = 'failed'
            state['stages'][stage_id] = {'status': 'failed', 'error': str(exc), 'finished_at': now()}
            save_state(state_path, state)
            raise PipelineError(str(exc)) from exc
        if resume and record.get('inputs') is not None and record['inputs'] != inputs:
            state['status'] = 'failed'
            state['error'] = f'{stage_id}: input content changed; choose a new run directory'
            save_state(state_path, state)
            raise PipelineError(state['error'])
        output_paths = list(dict.fromkeys(stage['outputs'] + (stage['artifact']['paths'] + [stage['artifact']['manifest']] if stage.get('artifact') else [])))
        outputs_exist = all(Path(output).exists() for output in output_paths)
        if record.get('status') == 'complete' and ('inputs' not in record or 'outputs' not in record):
            outputs_exist = False
        if outputs_exist and record.get('outputs') is not None:
            outputs_exist = snapshot(output_paths) == record['outputs']
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
        record = {'status': 'running', 'started_at': now(), 'log': str(log_path), 'inputs': inputs}
        state['stages'][stage_id] = record
        save_state(state_path, state)
        print(f'[{stage_id}] running; log: {log_path}', flush=True)
        try:
            with log_path.open('a') as log:
                log.write(f'\n=== Attempt started {now()} ===\n')
                log.flush()
                result = subprocess.run(stage['argv'], cwd=stage['cwd'],
                    env=stage_environment(plan, stage),
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
        try:
            if stage.get('artifact'):
                artifact = stage['artifact']
                write_contract(artifact['manifest'], kind=artifact['kind'], paths=artifact['paths'],
                               producer={'stage': stage_id, 'provenance': provenance[stage['component']]})
            record['outputs'] = snapshot(output_paths)
        except (ValueError, OSError) as exc:
            record.update(status='failed', error=str(exc), finished_at=now())
            state['status'] = 'failed'
            save_state(state_path, state)
            raise PipelineError(str(exc)) from exc
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
    parser.add_argument('--workspace', type=Path)
    args = parser.parse_args(argv)
    try:
        plan = build_plan(args.config, args.run_dir, args.workspace)
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
