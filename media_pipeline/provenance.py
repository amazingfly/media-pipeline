"""Record only source state and package versions; never dump process environments."""
import hashlib
import json
import subprocess
from pathlib import Path
from media_workspace.contracts import hash_file


def revision(root):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL)
    try:
        if Path(git('rev-parse', '--show-toplevel').decode().strip()).resolve() != Path(root).resolve():
            return {'git': None}
        commit = git('rev-parse', 'HEAD').decode().strip()
        diff = git('diff', '--binary', 'HEAD')
        untracked = git('ls-files', '--others', '--exclude-standard', '-z').decode().split('\0')
        files = {name: hash_file(Path(root)/name) for name in untracked if name and (Path(root)/name).is_file()}
        return {'git': commit, 'dirty': bool(diff or files), 'diff_sha256': hashlib.sha256(diff).hexdigest(),
                'untracked': files}
    except subprocess.CalledProcessError:
        return {'git': None}


def capture(components):
    result = {}
    code = ('import sys,json,importlib.metadata as m; print(json.dumps({"python":sys.version,'
            '"packages":sorted((d.metadata["Name"],d.version) for d in m.distributions())}))')
    for name, item in components.items():
        process = subprocess.run([item['python'], '-c', code], capture_output=True, text=True, timeout=60)
        if process.returncode:
            raise ValueError(f'Cannot inspect {name} interpreter: {process.stderr.strip()}')
        result[name] = {'root': item['root'], 'interpreter': item['python'],
                        'source': revision(item['root']), 'environment': json.loads(process.stdout)}
    return result
