# Workspace configuration

Copy `configs/workspace.example.json` to
`~/.config/agentic-media/workspace.json` and set your checkout, interpreter and
storage paths. `MEDIA_WORKSPACE_CONFIG` or `--config` on the workspace command
selects a different file. The coordinator accepts `--workspace`. Relative workspace
paths resolve from the workspace file; Python paths resolve from each checkout.
Never put token contents or passwords in this file. Credential *directories* are
allowed; credentials remain in the existing local stores.

```bash
python scripts/workspace.py show
python scripts/workspace.py doctor
python scripts/workspace.py run --component images -- '{python}' scripts/generate_images.py config.json
python scripts/workspace.py run --component storybook -- '{python}' scripts/run_storybook.py --mode colab --story STORY.json --run-dir RUN
```

The wrapper and coordinator add the selected interpreter's directory to PATH for shell children.
All repositories carry it. Maintained Python entry points also load workspace
defaults directly; explicit environment variables take precedence. The coordinator
merges workspace component definitions with per-pipeline overrides. Example
pipelines now refer to configured component names instead of hard-coded roots.

## Path mapping

`components` accepts `sa3`, `images`, `ltx`, `storybook`, and `pipeline`, each with
`root` and `python`. They export `SA3_REPO`, `IMAGES_REPO`, `LTX_REPO`, etc., and
matching `*_PYTHON`. `SD15_REPO` is an alias for `IMAGES_REPO` used by the audio UI.

`paths` accepts these keys:

| Keys | Purpose |
| --- | --- |
| `data`, `models`, `datasets`, `runs`, `credentials` | Workspace storage roots, exported as `MEDIA_*_ROOT` |
| `images`, `music` | Default LTX input directories |
| `ltx_outputs`, `sa3_outputs`, `sa3_library`, `sa3_web_runs` | Existing output/library/UI stores |
| `gemma_base`, `gemma_server`, `gemma_model`, `gemma_mmproj` | Gemma launcher paths |
| `sd15_model` | Local pretrained SD15 model directory |
| `sdxl_binary`, `sdxl_model`, `sdxl_loras` | Optional hardware/model-path overrides for SDXL configs |
| `qwen_server`, `qwen_model_dir` | Qwen launcher paths |
| `piper`, `voices`, `ffmpeg`, `ffprobe` | Narration and media tools |

`{paths.runs}` and other `{paths.KEY}` placeholders work in pipeline stage
arguments. Generation parameters remain in component presets. Historical recipes
may still contain workstation defaults; run them through the workspace wrapper
and consult their status in `workflows.json`. GPU/remote worker scripts retain
their remote paths; they do not read local workspace configuration.

Existing data has not been physically relocated. The current local configuration
points at the original stores. New runs should use a deliberate `--run-dir` under
the configured run root; no command silently moves model or media directories.

## Shared source maintenance

`media_workspace/` here is canonical. Other repos carry generated copies with
`SOURCE.json` SHA-256 checksums so standalone clones work without a dependency on
this checkout. The modules use only the standard library at import time; Colab,
Playwright and requests are loaded only by the helpers that need them.

```bash
python scripts/sync_workspace.py --target /path/to/images --target /path/to/sa3
python scripts/sync_workspace.py --check --target /path/to/images
python scripts/workspace.py verify
```

CI verifies checksums and the workflow catalog in every repo. Make shared changes
here, run tests, sync the consumers, then commit all affected repositories. Version
1 consolidates tunnel keepalive, frontend reconnect handling, runtime token
refresh and kernel-based artifact recovery. Component-specific allocation/retry
policies remain local. The frontend's shared policy recognizes both Connect and
Reconnect; tunnel read timeouts retain the established success behavior.
