from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from scripts.run_validated_littlequeen_workflow import (
    load_accepted_images,
    newest_unused_track,
    previously_ambiguous_image_paths,
    select_images,
    used_track_names,
)


class ValidatedLittleQueenWorkflowTests(unittest.TestCase):
    def test_prior_multi_subject_prompt_excludes_accepted_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = root / "outputs"
            run_dir = outputs / "old-run"
            images = root / "images"
            run_dir.mkdir(parents=True)
            images.mkdir()
            ambiguous = images / "ambiguous.png"
            clean = images / "clean.png"
            ambiguous.touch()
            clean.touch()
            (run_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "settings": {"motion_style": "little-queen"},
                        "clips": [
                            {
                                "image_path": str(ambiguous),
                                "prompt_error": (
                                    "The main queen glows while a smaller figure "
                                    "copies her pose."
                                ),
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            report = root / "report.json"
            report.write_text(
                json.dumps(
                    {
                        "records": [
                            {"decision": "accept", "image_file": str(ambiguous)},
                            {"decision": "accept", "image_file": str(clean)},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            excluded = previously_ambiguous_image_paths(outputs)
            accepted = load_accepted_images(report, excluded)

            self.assertEqual(excluded, {str(ambiguous.resolve())})
            self.assertEqual(accepted, [clean.resolve()])

    def test_selection_starts_with_every_image_from_newest_batch(self) -> None:
        accepted = [
            Path(f"/images/image_{index}_20260705_193630.png")
            for index in range(1, 4)
        ] + [
            Path(f"/images/image_{index}_20260627_141058.png")
            for index in range(4, 8)
        ]

        selected, batch, newest_count, newest_selected, repeated = select_images(
            accepted,
            required_count=6,
            seed=42,
        )

        self.assertEqual(batch, "20260705_193630")
        self.assertEqual(newest_count, 3)
        self.assertEqual(newest_selected, 3)
        self.assertEqual(repeated, 0)
        self.assertTrue(
            all(path.stem.endswith("20260705_193630") for path in selected[:3])
        )
        self.assertEqual(len(set(selected)), 6)

    def test_selection_repeats_only_after_all_accepted_images_are_used(self) -> None:
        accepted = [
            Path(f"/images/image_{index}_20260705_193630.png")
            for index in range(1, 3)
        ] + [
            Path(f"/images/image_{index}_20260627_141058.png")
            for index in range(3, 6)
        ]

        selected, _, _, _, repeated = select_images(
            accepted,
            required_count=7,
            seed=7,
        )

        self.assertEqual(len(set(selected[:5])), 5)
        self.assertEqual(repeated, 2)

    def test_track_selection_skips_names_used_by_existing_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tracks_dir = root / "tracks"
            outputs_dir = root / "outputs"
            run_dir = outputs_dir / "run"
            tracks_dir.mkdir()
            run_dir.mkdir(parents=True)
            newest = tracks_dir / "newest.flac"
            next_newest = tracks_dir / "next-newest.flac"
            newest.touch()
            next_newest.touch()
            os.utime(next_newest, (100, 100))
            os.utime(newest, (200, 200))
            (run_dir / "manifest.json").write_text(
                json.dumps({"music": {"path": f"/moved/archive/{newest.name}"}}),
                encoding="utf-8",
            )

            used = used_track_names(outputs_dir)
            selected = newest_unused_track(tracks_dir, used)

            self.assertEqual(used, {"newest.flac"})
            self.assertEqual(selected, next_newest.resolve())


if __name__ == "__main__":
    unittest.main()
