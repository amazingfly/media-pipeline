# Migration record

The following source moved from ltxVideo into this repository:

- `scripts/run_validated_littlequeen_workflow.py` and its tests.
- `scripts/upload_video.py` and its tests.
- `promptGetter/` source and its ignored local database/export files.

Ignored symlinks in ltxVideo preserve the original paths. `auth/` and `outputs/`
here link to the original local LTX directories. No credentials or generated media
are committed. The new runner writes its own run state under `runs/` instead.

The LTX-specific `scripts/run_full_pipeline.py` remains in ltx-video: it implements
that component's retries and assembly. The orchestration repository calls it as a
subprocess using the LTX environment. Image-specific storybook rendering remains
in images, including its narration and video assembly utilities.

Git history preservation:

- ltx-video retains its original two commits, followed by cleanup commits.
- SA3's former nested scripts Git repository is preserved locally under
  `sa3/.local/reorganization/`; the new root repository contains ordinary files.
- images' former history includes large model binaries and is preserved intact
  under `images/.local/reorganization/original.git`. GitHub has a source-only history.

All three existing repositories retain their original local checkout locations.
Large storage trees, installed services, and existing run manifests remain in place.
