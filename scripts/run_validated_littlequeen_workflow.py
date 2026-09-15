#!/usr/bin/env python3
"""Run Little Queen curation, selection, LTX generation, and shorts picking."""

from __future__ import annotations

# Load centralized workstation defaults; explicit environment/CLI values win.
import sys as _workspace_sys
from pathlib import Path as _WorkspacePath
for _workspace_root in _WorkspacePath(__file__).resolve().parents:
    if (_workspace_root / "media_workspace").is_dir():
        _workspace_sys.path.insert(0, str(_workspace_root))
        break
from media_workspace.config import apply_environment as _apply_workspace
_apply_workspace()


import argparse
import json
import math
import os
import random
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(os.environ.get("LTX_REPO", str(Path(__file__).resolve().parents[2] / "ltxVideo"))).expanduser().resolve()
DEFAULT_PICKER_PYTHON = Path(os.environ.get("LTX_PYTHON", str(PROJECT_ROOT / ".venv/bin/python")))
IMAGE_PROJECT = Path(os.environ.get("IMAGES_REPO", "/mnt/storage/projects/agentic/images")).expanduser().resolve()
IMAGE_PYTHON = os.environ.get("IMAGES_PYTHON", str(IMAGE_PROJECT / ".venv/bin/python") if (IMAGE_PROJECT / ".venv/bin/python").is_file() else sys.executable)
DATASET_DIR = IMAGE_PROJECT / "scripts" / "output_lora_littlequeen_dataset"
CURATION_SCRIPT = IMAGE_PROJECT / "scripts" / "curate_littlequeen_dataset.py"
DEFAULT_CURATION_REPORT = DATASET_DIR / "curation" / "first_pass_report.json"
DEFAULT_SA3_DIR = Path(
    "/mnt/storage/sa3Archive/storage-runs/"
    "sa3_nightcore_guidance_sweep_20260705/yes"
)
AUDIO_EXTENSIONS = {".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"}
IMAGE_BATCH_PATTERN = re.compile(r"_(\d{8}_\d{6})$")
AMBIGUOUS_RENDERED_SUBJECTS = re.compile(
    r"\b(?:large|small|smaller|main|second)\s+(?:subject|figure|girl|queen)\b"
    r"|\b(?:two|both)\s+(?:subjects|figures|girls|queens)\b",
    flags=re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Little Queen images and run an LTX music video from accepted images."
    )
    parser.add_argument("--dataset-dir", type=Path, default=DATASET_DIR)
    parser.add_argument("--curation-report", type=Path, default=DEFAULT_CURATION_REPORT)
    parser.add_argument("--sa3-dir", type=Path, default=DEFAULT_SA3_DIR)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--clip-seconds", type=float, default=2.0)
    parser.add_argument("--selection-seed", type=int)
    parser.add_argument("--curation-gemma-timeout", type=float, default=240.0)
    parser.add_argument("--skip-curation", action="store_true")
    parser.add_argument("--skip-pipeline", action="store_true")
    parser.add_argument("--skip-picker", action="store_true")
    parser.add_argument("--no-open-frontend", action="store_true")
    return parser.parse_args()


class TeeLogger:
    def __init__(self, log_path: Path) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path = log_path
        self.handle = log_path.open("a", encoding="utf-8")

    def close(self) -> None:
        self.handle.close()

    def info(self, message: str) -> None:
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}"
        print(line, flush=True)
        self.handle.write(line + "\n")
        self.handle.flush()

    def stream(self, line: str) -> None:
        print(line, end="", flush=True)
        self.handle.write(line)
        self.handle.flush()


def run_command(command: list[str], logger: TeeLogger, *, cwd: Path = PROJECT_ROOT) -> None:
    logger.info(f"Command: {' '.join(command)}")
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    assert process.stdout is not None
    for line in process.stdout:
        logger.stream(line)
    returncode = process.wait()
    if returncode != 0:
        raise SystemExit(f"Command failed with exit code {returncode}: {' '.join(command)}")


def audio_duration_seconds(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(result.stdout.strip())


def used_track_names(outputs_dir: Path) -> set[str]:
    used: set[str] = set()
    for manifest_path in outputs_dir.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        music_path = manifest.get("music", {}).get("path")
        if music_path:
            used.add(Path(str(music_path)).name)
    return used


def newest_unused_track(sa3_dir: Path, used_names: set[str]) -> Path:
    tracks = sorted(
        (
            path
            for path in sa3_dir.iterdir()
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
        ),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    for track in tracks:
        if track.name not in used_names:
            return track.resolve()
    raise RuntimeError(
        f"No unused audio tracks remain in {sa3_dir}; found {len(tracks)} track(s)"
    )


def latest_littlequeen_manifest(run_dir: Path) -> Path | None:
    manifests = sorted(
        (path for path in (run_dir / "outputs").glob("*/manifest.json")),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for manifest_path in manifests:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("settings", {}).get("motion_style") == "little-queen":
            return manifest_path.resolve()
    return None


def used_images_from_manifest(manifest_path: Path | None) -> set[str]:
    if manifest_path is None:
        return set()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    used: set[str] = set()
    for clip in manifest.get("clips", []):
        image_path = clip.get("image_path")
        if image_path:
            used.add(str(Path(image_path).resolve()))
    return used


def previously_ambiguous_image_paths(outputs_dir: Path) -> set[str]:
    ambiguous: set[str] = set()
    for manifest_path in outputs_dir.glob("*/manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("settings", {}).get("motion_style") != "little-queen":
            continue
        for clip in manifest.get("clips", []):
            audit_text = " ".join(
                str(value)
                for value in (clip.get("motion_prompt"), clip.get("prompt_error"))
                if value
            )
            image_path = clip.get("image_path")
            if image_path and AMBIGUOUS_RENDERED_SUBJECTS.search(audit_text):
                ambiguous.add(str(Path(str(image_path)).resolve()))
    return ambiguous


def load_accepted_images(
    report_path: Path,
    excluded_paths: set[str] | None = None,
) -> list[Path]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    excluded = excluded_paths or set()
    accepted: list[Path] = []
    for record in report.get("records", []):
        if record.get("decision") != "accept":
            continue
        image_path = Path(str(record.get("image_file", ""))).resolve()
        if image_path.is_file() and str(image_path) not in excluded:
            accepted.append(image_path)
    accepted.sort(key=lambda path: path.name)
    if not accepted:
        raise RuntimeError(f"No accepted images found in {report_path}")
    return accepted


def clear_selected_dir(selected_dir: Path) -> None:
    selected_dir.mkdir(parents=True, exist_ok=True)
    for path in selected_dir.iterdir():
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            raise RuntimeError(f"Refusing to remove nested directory in selected image dir: {path}")


def image_batch_id(path: Path) -> str:
    match = IMAGE_BATCH_PATTERN.search(path.stem)
    if match:
        return match.group(1)
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d_%H%M%S")


def select_images(
    accepted: list[Path],
    required_count: int,
    seed: int,
) -> tuple[list[Path], str, int, int, int]:
    rng = random.Random(seed)
    newest_batch = max(image_batch_id(path) for path in accepted)
    newest = [path for path in accepted if image_batch_id(path) == newest_batch]
    rng.shuffle(newest)

    selected = newest[:required_count]
    newest_selected_count = len(selected)
    if len(selected) < required_count:
        selected_set = {str(path.resolve()) for path in selected}
        fallback_pool = [path for path in accepted if str(path.resolve()) not in selected_set]
        rng.shuffle(fallback_pool)
        needed = required_count - len(selected)
        selected.extend(fallback_pool[:needed])

    repeated_count = 0
    while len(selected) < required_count:
        repeat_pool = accepted.copy()
        rng.shuffle(repeat_pool)
        repeated = repeat_pool[: required_count - len(selected)]
        selected.extend(repeated)
        repeated_count += len(repeated)

    return selected, newest_batch, len(newest), newest_selected_count, repeated_count


def link_selected_images(selected: list[Path], selected_dir: Path) -> None:
    clear_selected_dir(selected_dir)
    for index, image_path in enumerate(selected, start=1):
        link_path = selected_dir / f"lq_{index:04d}_{image_path.name}"
        link_path.symlink_to(image_path)


def write_selection_report(
    path: Path,
    *,
    track: Path,
    duration: float,
    required_count: int,
    seed: int,
    last_manifest: Path | None,
    accepted_count: int,
    excluded_images: list[str],
    newest_batch: str,
    newest_accepted_count: int,
    newest_selected_count: int,
    repeated_count: int,
    selected: list[Path],
) -> None:
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "track": str(track),
        "track_duration_seconds": duration,
        "required_clip_count": required_count,
        "selection_seed": seed,
        "last_littlequeen_manifest": str(last_manifest) if last_manifest else None,
        "accepted_count": accepted_count,
        "previously_ambiguous_excluded_count": len(excluded_images),
        "previously_ambiguous_excluded_images": excluded_images,
        "newest_image_batch": newest_batch,
        "newest_accepted_count": newest_accepted_count,
        "newest_selected_count": newest_selected_count,
        "fill_from_all_accepted_count": len(selected) - newest_selected_count - repeated_count,
        "repeated_image_count": repeated_count,
        "selected_images": [str(path) for path in selected],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_curation(args: argparse.Namespace, logger: TeeLogger) -> None:
    if args.skip_curation:
        logger.info("Skipping curation because --skip-curation was provided.")
        return
    command = [
        IMAGE_PYTHON,
        "-u",
        str(CURATION_SCRIPT),
        "--images-dir",
        str(args.dataset_dir.resolve()),
        "--output",
        str(args.curation_report.resolve()),
        "--judge",
        "gemma",
        "--gemma-timeout",
        str(args.curation_gemma_timeout),
        "--keep-gemma-running",
    ]
    run_command(command, logger, cwd=IMAGE_PROJECT)


def run_ltx_pipeline(
    args: argparse.Namespace,
    logger: TeeLogger,
    *,
    manifest_path: Path,
    selected_dir: Path,
    track: Path,
    seed: int,
) -> None:
    if args.skip_pipeline:
        logger.info("Skipping LTX pipeline because --skip-pipeline was provided.")
        return
    session_name = f"lq-validated-{manifest_path.parent.name[:32]}"
    command = [
        str(DEFAULT_PICKER_PYTHON),
        "-u",
        str(PROJECT_ROOT / "scripts" / "run_full_pipeline.py"),
        "--manifest",
        str(manifest_path),
        "--image-dir",
        str(selected_dir),
        "--music",
        str(track),
        "--motion-style",
        "little-queen",
        "--selection-seed",
        str(seed),
        "--preserve-image-order",
        "--session",
        session_name,
        "--batch-size",
        "0",
        "--playback-fps",
        "12",
        "--output-fps",
        "24",
        "--transition-seconds",
        "0.5",
    ]
    if args.no_open_frontend:
        command.append("--no-open-frontend")
    run_command(command, logger)


def run_picker(args: argparse.Namespace, logger: TeeLogger, *, run_dir: Path) -> None:
    if args.skip_picker:
        logger.info("Skipping short picker because --skip-picker was provided.")
        return
    picker_python = DEFAULT_PICKER_PYTHON
    command = [
        str(picker_python),
        "-u",
        "-m",
        "antigravityPicker.cli",
        "--outputs-dir",
        str(run_dir),
        "--force",
    ]
    run_command(command, logger)


def main() -> int:
    args = parse_args()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = (args.run_dir or (PROJECT_ROOT / "outputs" / f"{timestamp}-littlequeen-validated")).resolve()
    manifest_path = run_dir / "manifest.json"
    selected_dir = run_dir / "selected_images"
    logger = TeeLogger(run_dir / "validated_littlequeen_workflow.log")
    try:
        logger.info(f"Workflow run directory: {run_dir}")
        run_curation(args, logger)

        prior_track_names = used_track_names(PROJECT_ROOT / "outputs")
        track = newest_unused_track(args.sa3_dir.resolve(), prior_track_names)
        duration = audio_duration_seconds(track)
        required_count = math.ceil(duration / args.clip_seconds)
        seed = args.selection_seed if args.selection_seed is not None else random.SystemRandom().randrange(0, 2**31)
        last_manifest = latest_littlequeen_manifest(PROJECT_ROOT)
        excluded_images = previously_ambiguous_image_paths(PROJECT_ROOT / "outputs")
        accepted = load_accepted_images(
            args.curation_report.resolve(),
            excluded_images,
        )
        (
            selected,
            newest_batch,
            newest_accepted_count,
            newest_selected_count,
            repeated_count,
        ) = select_images(
            accepted,
            required_count,
            seed,
        )
        link_selected_images(selected, selected_dir)
        write_selection_report(
            run_dir / "selected_images.json",
            track=track,
            duration=duration,
            required_count=required_count,
            seed=seed,
            last_manifest=last_manifest,
            accepted_count=len(accepted),
            excluded_images=sorted(excluded_images),
            newest_batch=newest_batch,
            newest_accepted_count=newest_accepted_count,
            newest_selected_count=newest_selected_count,
            repeated_count=repeated_count,
            selected=selected,
        )
        logger.info(f"Selected track: {track}")
        logger.info(
            f"Selected {required_count} image link(s): {len(accepted)} accepted, "
            f"{newest_selected_count}/{newest_accepted_count} from newest batch "
            f"{newest_batch}, {repeated_count} repeated pick(s)."
        )
        if excluded_images:
            logger.info(
                "Excluded "
                f"{len(excluded_images)} previously accepted image(s) whose prior "
                "Gemma audit described multiple rendered subjects."
            )

        run_ltx_pipeline(
            args,
            logger,
            manifest_path=manifest_path,
            selected_dir=selected_dir,
            track=track,
            seed=seed,
        )
        run_picker(args, logger, run_dir=run_dir)
        logger.info("Validated Little Queen workflow complete.")
        return 0
    finally:
        logger.close()


if __name__ == "__main__":
    raise SystemExit(main())
