# Artifact contracts and provenance

`schemas/artifact-v1.json` defines a shared artifact envelope for `audio`, `image`,
`video`, and `story`. Native component manifests and story schemas stay unchanged;
the coordinator writes sidecar contracts around completed outputs. Consumers can
validate those contracts without importing the producer's implementation.

```json
{
  "artifact": {
    "kind": "audio",
    "paths": ["{run_dir}/audio/track.flac"],
    "manifest": "{run_dir}/contracts/audio.json"
  },
  "inputs": ["{sa3.root}/colab/generation_config.json"]
}
```

A downstream stage declares `input_contracts` as a list of objects with `path` and
`kind`. Before starting it, the runner checks schema/version, kind, absolute asset
paths, sizes and SHA-256 hashes. Required outputs must exist before a contract is
written. Empty artifact directories cannot produce a successful contract. Native
JSON manifests may be included alongside media files in `paths`.

Checkpoint v2 (`schemas/pipeline-state-v2.json`) records:

- Component Git commit, tracked diff hash, and hashes of nonignored untracked files.
- Each selected Python interpreter, Python version, and installed package versions.
- The coordinator source/environment and expanded stage commands (environment
  variable names only; arbitrary environment values are not saved).
- Declared input paths and hashes, including input contract files.
- Completed output paths and hashes, stage status, timestamps and logs.

Only declared inputs are hashed: list model files and any additional datasets in
`inputs` when their exact contents are part of the run contract. Hashing large
models/datasets takes time. Directory inputs include filenames and file contents.
Credential directories and arbitrary environment values are not collected.

Resume rejects changed component source/environments or changed inputs. Missing
or modified outputs rerun that stage and invalidate later stages. Changing the
command plan requires a new run directory. Legacy v1 checkpoints remain readable
as files, but cannot be resumed as provenance-verified v2 runs. A new run directory
is required; native component resumption remains available independently.

Source/environment snapshots are taken at coordinator start; avoid editing code
or updating environments during a running job. Model and remote-worker versions
are only captured when their configs/files are declared as inputs; local package
versions do not attest to the packages installed inside a remote Colab runtime.
