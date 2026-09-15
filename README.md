# Media pipeline

Coordinate the separate [SA3](https://github.com/amazingfly/sa3),
[images](https://github.com/amazingfly/images), [LTX video](https://github.com/amazingfly/ltx-video), and
[storybook-pipeline](https://github.com/amazingfly/storybook-pipeline) repositories. This repository
owns orchestration, cross-run prompt provenance, and optional media publishing.

## Setup

Use Linux, Python 3.10+, and uv. Clone and set up each component separately; model
and GPU dependencies belong to those repositories, not this runner.

```bash
uv sync --locked --group dev
mkdir -p ~/.config/agentic-media
cp configs/workspace.example.json ~/.config/agentic-media/workspace.json
# Edit workspace paths/interpreters, then select stage inputs:
cp configs/pipeline.example.json configs/local.json
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
The workstation has an ignored `configs/local.json` for stage settings; checkout
and interpreter paths live in `~/.config/agentic-media/workspace.json`. A successful `doctor` checks paths/executables, not model
availability, authentication, or GPU quota.

`plan` and `doctor` do not launch stages. `run` executes exactly the listed stages,
in order, using argument arrays without shell interpolation. Each stage writes a
log under the run directory. `pipeline-state.json` records checkpoints atomically,
and a filesystem lock prevents two runners from owning the same run directory.
Resume verifies input/output content, component source and Python environments.
Changed inputs or environments require a new run directory. Missing or modified
outputs rerun their stage and invalidate downstream checkpoints. See
[contracts and provenance](docs/contracts.md) for the exact guarantees and limits.


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

For storybook production, use `configs/storybook.example.json` after setting up
the storybook checkout and its image assets. See [repository ownership and the
shared organization controls](docs/organization.md) for the five-repository structure.

See [workflow support status](docs/workflows.md). Use `python scripts/workspace.py doctor`
to check centralized checkout/interpreter configuration, and
`python scripts/workspace.py run --component pipeline -- {python} SCRIPT [ARGS]`
to launch with shared paths. Workspace setup is documented in
[media-pipeline](https://github.com/amazingfly/media-pipeline/blob/main/docs/workspace.md).
