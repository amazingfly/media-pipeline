import json
import subprocess
import sys
from pathlib import Path

import pytest
from media_workspace.config import load_workspace, environment
from media_workspace.contracts import write_contract, validate_contract
from media_pipeline.runner import execute, PipelineError
from test_runner import fixture_plan


def test_workspace_resolves_relative_paths_and_rejects_unknown_keys(tmp_path):
    config = tmp_path / 'workspace.json'
    config.write_text(json.dumps({'version':1, 'components':{'ltx':{'root':'video','python':'.venv/bin/python'}}, 'paths':{'models':'models'}}))
    workspace = load_workspace(config)
    assert workspace['components']['ltx']['root'] == str(tmp_path/'video')
    assert environment(workspace)['MEDIA_MODEL_ROOT'] == str(tmp_path/'models')
    config.write_text('{"version":1,"paths":{"typo":"models"}}')
    with pytest.raises(ValueError, match='Unknown workspace path'):
        load_workspace(config)


@pytest.mark.parametrize('kind', ['audio','image','video','story'])
def test_artifact_roundtrip_and_tamper_detection(tmp_path, kind):
    asset = tmp_path / 'asset'; asset.write_bytes(b'original')
    manifest = write_contract(tmp_path/'contract.json', kind=kind, paths=[asset], producer={'component':'test'})
    validate_contract(manifest, verify=True, expected_kind=kind)
    asset.write_bytes(b'changed!')
    with pytest.raises(ValueError, match='changed or missing'):
        validate_contract(manifest, verify=True)
    manifest['version'] = 99
    with pytest.raises(ValueError, match='schema/version'):
        validate_contract(manifest)


def test_resume_rejects_changed_input(tmp_path):
    plan = fixture_plan(tmp_path)
    source = tmp_path/'source.txt'; source.write_text('one')
    plan['stages'][0]['inputs'] = [str(source)]
    execute(plan)
    source.write_text('two')
    with pytest.raises(PipelineError, match='input content changed'):
        execute(plan, resume=True)
    assert (tmp_path/'run/audio').read_text() == 'x'


def test_modified_output_reruns_stage_and_downstream(tmp_path):
    plan = fixture_plan(tmp_path); execute(plan)
    (tmp_path/'run/images').write_text('tampered')
    execute(plan, resume=True)
    assert (tmp_path/'run/audio').read_text() == 'x'
    assert (tmp_path/'run/video').read_text() == 'xx'


def test_revision_and_dirty_source_invalidate_resume(tmp_path):
    source = tmp_path/'component'; source.mkdir()
    subprocess.run(['git','init','-q',str(source)],check=True)
    (source/'app.py').write_text('print("one")')
    subprocess.run(['git','-C',str(source),'add','.'],check=True)
    subprocess.run(['git','-C',str(source),'-c','user.name=Test','-c','user.email=test@example.com','commit','-qm','fixture'],check=True)
    plan=fixture_plan(tmp_path); plan['components']['test']['root']=str(source)
    execute(plan)
    (source/'app.py').write_text('print("two")')
    with pytest.raises(PipelineError, match='source or environment changed'):
        execute(plan,resume=True)


def test_contract_flows_between_real_subprocesses(tmp_path):
    plan=fixture_plan(tmp_path)
    manifest=str(tmp_path/'run/contracts/audio.json')
    plan['stages'][0]['artifact']={'kind':'audio','paths':[str(tmp_path/'run/audio')],'manifest':manifest}
    plan['stages'][1]['input_contracts']=[{'path':manifest,'kind':'audio'}]
    execute(plan)
    state=execute(plan,resume=True)
    assert state['version']==2
    assert state['provenance']['test']['environment']['python']
    assert state['stages']['audio']['outputs'][0]['files'][0]['sha256']
    assert (tmp_path/'run/video').read_text()=='x'


def test_published_json_schemas_match_written_contracts(tmp_path):
    import jsonschema
    root=Path(__file__).resolve().parents[1]
    plan=fixture_plan(tmp_path)
    state=execute(plan)
    jsonschema.validate(state,json.loads((root/'schemas/pipeline-state-v2.json').read_text()))
    asset=tmp_path/'asset';asset.write_bytes(b'fixture')
    value=write_contract(tmp_path/'manifest.json',kind='image',paths=[asset],producer={'component':'test'})
    jsonschema.validate(value,json.loads((root/'schemas/artifact-v1.json').read_text()))


def test_shell_children_use_component_python(tmp_path):
    plan=fixture_plan(tmp_path)
    binary=tmp_path/'component-bin/python';binary.parent.mkdir()
    binary.symlink_to(sys.executable)
    plan['components']['test']['python']=str(binary)
    plan['stages']=plan['stages'][:1]
    plan['stages'][0]['argv']=['python','-c','import sys; from pathlib import Path; Path(sys.argv[1]).write_text(sys.executable)',str(tmp_path/'run/audio')]
    execute(plan)
    assert (tmp_path/'run/audio').read_text()==str(binary)
