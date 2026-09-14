import copy
import json
import sys
from pathlib import Path

import pytest

from media_pipeline.runner import PipelineError, build_plan, execute


def fixture_plan(tmp_path):
    config = {
        'version': 1,
        'components': {'test': {'root': str(tmp_path), 'python': sys.executable}},
        'stages': [
            {'id': name, 'component': 'test', 'argv': ['{python}', '-c',
             'from pathlib import Path; import sys; p=Path(sys.argv[1]); p.write_text(p.read_text()+"x" if p.exists() else "x")',
             '{run_dir}/' + name], 'outputs': ['{run_dir}/' + name]}
            for name in ['audio', 'images', 'video']
        ],
    }
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    return build_plan(path, tmp_path / 'run')


def test_resume_skips_completed_stages(tmp_path):
    plan = fixture_plan(tmp_path)
    execute(plan)
    execute(plan, resume=True)
    assert (tmp_path / 'run/audio').read_text() == 'x'
    assert (tmp_path / 'run/video').read_text() == 'x'


def test_missing_output_invalidates_downstream(tmp_path):
    plan = fixture_plan(tmp_path)
    execute(plan)
    (tmp_path / 'run/images').unlink()
    execute(plan, resume=True)
    assert (tmp_path / 'run/audio').read_text() == 'x'
    assert (tmp_path / 'run/images').read_text() == 'x'
    assert (tmp_path / 'run/video').read_text() == 'xx'


def test_failure_stops_downstream_and_resumes(tmp_path):
    plan = fixture_plan(tmp_path)
    marker = tmp_path / 'ready'
    plan['stages'][1]['argv'] = [sys.executable, '-c',
        'from pathlib import Path; import sys; assert Path(sys.argv[1]).exists(); Path(sys.argv[2]).write_text("done")',
        str(marker), str(tmp_path / 'run/images')]
    with pytest.raises(PipelineError, match='exited'):
        execute(plan)
    assert not (tmp_path / 'run/video').exists()
    assert json.loads((tmp_path / 'run/pipeline-state.json').read_text())['status'] == 'failed'
    marker.touch()
    execute(plan, resume=True)
    assert (tmp_path / 'run/audio').read_text() == 'x'
    assert (tmp_path / 'run/video').read_text() == 'x'


def test_changed_plan_cannot_reuse_checkpoints(tmp_path):
    plan = fixture_plan(tmp_path)
    execute(plan)
    changed = copy.deepcopy(plan)
    changed['stages'][0]['env'] = {'TEST_CHANGED': '1'}
    with pytest.raises(PipelineError, match='Plan changed'):
        execute(changed, resume=True)
    with pytest.raises(PipelineError, match='Run state exists'):
        execute(plan)


def test_success_without_required_output_is_failure(tmp_path):
    plan = fixture_plan(tmp_path)
    plan['stages'][0]['argv'] = [sys.executable, '-c', 'pass']
    with pytest.raises(PipelineError, match='required outputs'):
        execute(plan)
    assert not (tmp_path / 'run/images').exists()


def test_arguments_are_not_shell_expanded(tmp_path):
    plan = fixture_plan(tmp_path)
    literal = '$(touch SHOULD_NOT_EXIST); hello'
    plan['stages'] = [{'id': 'literal', 'component': 'test', 'cwd': str(tmp_path), 'env': {},
        'argv': [sys.executable, '-c', 'import sys; from pathlib import Path; Path(sys.argv[1]).write_text(sys.argv[2])',
                 str(tmp_path / 'run/literal'), literal], 'outputs': [str(tmp_path / 'run/literal')]}]
    execute(plan)
    assert (tmp_path / 'run/literal').read_text() == literal
    assert not (tmp_path / 'SHOULD_NOT_EXIST').exists()


def test_concurrent_runner_cannot_share_run_directory(tmp_path):
    import fcntl
    plan = fixture_plan(tmp_path)
    run_dir = Path(plan['run_dir'])
    run_dir.mkdir()
    with (run_dir / '.pipeline.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(PipelineError, match='Another pipeline'):
            execute(plan)
    assert not (run_dir / 'pipeline-state.json').exists()


def test_component_adapters_use_component_interpreters(tmp_path):
    from argparse import Namespace
    from unittest.mock import patch
    import scripts.run_validated_littlequeen_workflow as workflow
    args = Namespace(skip_curation=False, dataset_dir=tmp_path, curation_report=tmp_path / 'report.json',
                     curation_gemma_timeout=10, skip_pipeline=False, no_open_frontend=True)
    with patch.object(workflow, 'run_command') as run:
        with patch.object(workflow, 'IMAGE_PYTHON', '/images/python'):
            workflow.run_curation(args, None)
            assert run.call_args.args[0][0] == '/images/python'
        with patch.object(workflow, 'DEFAULT_PICKER_PYTHON', Path('/ltx/python')):
            workflow.run_ltx_pipeline(args, None, manifest_path=tmp_path / 'manifest.json',
                                      selected_dir=tmp_path, track=tmp_path / 'track.ogg', seed=1)
            assert run.call_args.args[0][0] == '/ltx/python'
