# Media pipeline

Coordinate the separate [SA3](https://github.com/amazingfly/sa3),
[images](https://github.com/amazingfly/images), and
[LTX video](https://github.com/amazingfly/ltx-video) repositories. This repository
owns orchestration, cross-run prompt provenance, and optional media publishing.

## Setup

Use Linux, Python 3.10+, and uv. Clone and set up each component separately; model
and GPU dependencies belong to those repositories, not this runner.

```bash
uv sync --locked --group dev
cp configs/pipeline.example.json configs/local.json
# Edit checkout roots, Python executables, and stage inputs in configs/local.json.
uv run media-pipeline plan --config configs/local.json --run-dir runs/demo
uv run media-pipeline doctor --config configs/local.json --run-dir runs/demo
uv run media-pipeline run --config configs/local.json --run-dir runs/demo
# After an interruption:
uv run media-pipeline run --config configs/local.json --run-dir runs/demo --resume
```

The example generates audio through SA3 Colab, generates images from the image
repository's configured prompts, assembles an LTX music video, and selects V3
shorts. Configure the image model paths and prompts first. Change the audio
output contract if the SA3 preset's `generation.output_name` changes. The image
stage uses the image repository's configured output directory; for isolated image
runs, supply a dedicated image config and update the video's input directory.
The workstation already has an ignored `configs/local.json` with its checkout and
interpreter paths. A successful `doctor` checks paths/executables, not model
availability, authentication, or GPU quota.

`plan` and `doctor` do not launch stages. `run` executes exactly the listed stages,
in order, using argument arrays without shell interpolation. Each stage writes a
log under the run directory. `pipeline-state.json` records checkpoints atomically,
and a filesystem lock prevents two runners from owning the same run directory.
Resume skips completed stages whose declared outputs still exist. A rerun
invalidates subsequent stages; changing the plan requires a new run directory.
Input content changes are not automatically detected: use a new run directory
when inputs or component code change. Stages without output declarations rely on
the saved exit status. Component-specific retries remain in the component tools.

## Existing workflows

- `scripts/run_validated_littlequeen_workflow.py`: curation → accepted-image and
  music selection → LTX → shorts. Set `LTX_REPO`, `IMAGES_REPO`, `LTX_PYTHON`, and
  `IMAGES_PYTHON` to select the component checkouts/environments. Its CLI accepts
  `--dataset-dir`, `--curation-report`, `--sa3-dir`, and `--run-dir`. Historical
  defaults remain supported on the original workstation.
- `promptGetter/get_prompts.py`: compile music/video prompt provenance. Use
  `--ltx-outputs` and `--sa3-outputs` for explicit stores; `db_cli.py` queries the
  compiled database. Generated databases and exports are ignored.
- `scripts/upload_video.py`: existing YouTube/Shorts/Facebook uploader. Install
  optional dependencies with `uv sync --extra publish` and see `--help` before
  use. Credentials stay in ignored `auth/`; use `--outputs-dir` for the video
  store. Publishing is a separate command and is not in the example pipeline.

On the original workstation, `auth/` and `outputs/` link to the preexisting LTX
stores; migrated script paths also have compatibility links. Credentials and
media were not copied to GitHub. See [migration record](docs/migration.md).

## Development

```bash
uv run pytest
```

Tests exercise sequential execution, failure/resume behavior, output contracts,
plan changes, literal command arguments, existing selection logic, and uploader
metadata handling. They do not call model or publishing services.

Configuration placeholders: `{run_dir}`, `{config_dir}`, `{root}`, `{python}`,
and `{component.root}` / `{component.python}` for named components. Relative
component roots are resolved from the config directory; relative Python paths
from the component root; relative output paths from the stage working directory.
Each stage needs `id`, `component`, and `argv`; `cwd`, `env`, and `outputs` are
optional. Put credentials in the inherited environment, not configuration files.
