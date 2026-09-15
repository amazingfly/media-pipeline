#!/usr/bin/env python3
"""Distribute the canonical shared package; never hand-edit component copies."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sync(target, check=False):
    source = ROOT / 'media_workspace'
    files = {p.name: p.read_bytes() for p in source.glob('*.py')}
    manifest = {'source': 'https://github.com/amazingfly/media-pipeline/tree/main/media_workspace',
                'version': '1.0.0', 'sha256': {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    files['SOURCE.json'] = (json.dumps(manifest, indent=2, sort_keys=True)+'\n').encode()
    destination = Path(target).resolve() / 'media_workspace'
    if destination == source:
        raise ValueError('Cannot vendor over canonical source')
    if check:
        differing = [name for name, content in files.items() if not (destination/name).is_file() or (destination/name).read_bytes() != content]
        extras = [p.name for p in destination.glob('*.py') if p.name not in files]
        if differing or extras:
            raise ValueError(f'{destination}: shared source differs: {differing + extras}')
    else:
        destination.mkdir(exist_ok=True)
        for name, content in files.items():
            (destination/name).write_bytes(content)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, action='append', required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for target in args.target:
        print(sync(target, args.check))
