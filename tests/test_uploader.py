from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "upload_video.py"
SPEC = importlib.util.spec_from_file_location("upload_video", SCRIPT_PATH)
assert SPEC and SPEC.loader
upload_video = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = upload_video
SPEC.loader.exec_module(upload_video)


class UploadVideoTests(unittest.TestCase):
    def test_default_metadata_templates_match_current_workflow(self) -> None:
        self.assertEqual(
            upload_video.default_full_description("Futuresynth Rave"),
            (
                "A Futuresynth Rave track generated with Stable Audio 3, "
                "images generated with Stable Diffusion 1.5 and videos generated "
                "with LTXVideo."
            ),
        )
        self.assertEqual(
            upload_video.hashtags_from_title("Futuresynth Rave"),
            "#Futuresynth #Rave",
        )
        self.assertEqual(
            upload_video.short_youtube_description("https://youtu.be/example"),
            "https://youtu.be/example",
        )
        self.assertEqual(
            upload_video.facebook_reel_description(
                "https://youtu.be/example",
                "#Futuresynth #Rave",
            ),
            "https://youtu.be/example\n#Futuresynth #Rave",
        )

    def test_resolve_short_source_prefers_current_short_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "20260627-100405"
            current_dir = run_dir / "shorts" / "1This"
            current_dir.mkdir(parents=True)
            chosen = current_dir / "short_3_ss147.4_to_178.4.mp4"
            chosen.write_bytes(b"placeholder")
            selections = {
                "selections": [
                    {"exported_path": "short_1.mp4"},
                    {"exported_path": "short_2.mp4"},
                    {"exported_path": str(run_dir / "shorts" / "short_3.mp4")},
                ]
            }
            (run_dir / "shorts" / "selections.json").write_text(
                json.dumps(selections),
                encoding="utf-8",
            )

            source = upload_video.resolve_short_source(run_dir, None, "1This")

            self.assertEqual(source.index, 3)
            self.assertEqual(source.path, chosen.resolve())
            self.assertEqual(source.source, "shorts/1This")
            self.assertEqual(source.selection, selections["selections"][2])

    def test_resolve_short_source_supports_future_index_only_flow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "20260627-100405"
            shorts_dir = run_dir / "shorts"
            shorts_dir.mkdir(parents=True)
            exported = shorts_dir / "short_4_ss200.1_to_231.1.mp4"
            exported.write_bytes(b"placeholder")
            selections = {
                "selections": [
                    {"exported_path": str(shorts_dir / "short_1.mp4")},
                    {"exported_path": str(shorts_dir / "short_2.mp4")},
                    {"exported_path": str(shorts_dir / "short_3.mp4")},
                    {"exported_path": str(exported)},
                ]
            }
            (shorts_dir / "selections.json").write_text(
                json.dumps(selections),
                encoding="utf-8",
            )

            source = upload_video.resolve_short_source(run_dir, 4, "1This")

            self.assertEqual(source.index, 4)
            self.assertEqual(source.path, exported.resolve())
            self.assertEqual(source.source, "shorts/selections.json")
            self.assertEqual(source.selection, selections["selections"][3])


if __name__ == "__main__":
    unittest.main()
