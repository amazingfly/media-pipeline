#!/usr/bin/env python3

# Load centralized workstation defaults; explicit environment/CLI values win.
import sys as _workspace_sys
from pathlib import Path as _WorkspacePath
for _workspace_root in _WorkspacePath(__file__).resolve().parents:
    if (_workspace_root / "media_workspace").is_dir():
        _workspace_sys.path.insert(0, str(_workspace_root))
        break
from media_workspace.config import apply_environment as _apply_workspace
_apply_workspace()

import os
import sys
import json
import glob
import re
import argparse

def clean_stem(filename):
    if not filename:
        return ""
    base = os.path.basename(filename)
    stem, _ = os.path.splitext(base)
    return stem.lower()

def extract_hash(stem):
    # Search for a 12-character hex-like hash (e.g. c87895a77002)
    match = re.search(r'[a-f0-9]{12}', stem)
    if match:
        return match.group(0)
    return None

def match_music_track(music_path, sa3_tracks):
    if not music_path:
        return None

    music_stem = clean_stem(music_path)
    music_hash = extract_hash(music_stem)

    # 1. Try exact stem match
    for track in sa3_tracks:
        for ref_path in track["references"]:
            ref_stem = clean_stem(ref_path)
            if music_stem == ref_stem:
                return track

    # 2. Try prefix/suffix stem match (e.g. one has run label prefix, other doesn't)
    for track in sa3_tracks:
        for ref_path in track["references"]:
            ref_stem = clean_stem(ref_path)
            if music_stem.endswith("__" + ref_stem) or ref_stem.endswith("__" + music_stem):
                return track

    # 3. Try matching by hash + track ID
    for track in sa3_tracks:
        track_id = track["sa3_track_id"].lower()
        track_hash = extract_hash(track["sa3_run_directory"].lower())

        # If we have hashes and they match
        if music_hash and track_hash and music_hash == track_hash:
            if track_id in music_stem:
                return track

    # 4. Fallback: match by unique hash
    if music_hash:
        matches = []
        for track in sa3_tracks:
            track_hash = extract_hash(track["sa3_run_directory"].lower())
            if track_hash == music_hash:
                matches.append(track)
        if len(matches) == 1:
            return matches[0]

    # 5. Last resort fallback: check if track ID is in the music stem
    for track in sa3_tracks:
        track_id = track["sa3_track_id"].lower()
        if track_id in music_stem:
            return track

    return None

def main():
    parser = argparse.ArgumentParser(description="Compile prompt and generation metadata from ltxVideo and sa3 runs.")
    parser.add_argument(
        "-o", "--output",
        help="Path to write the compiled JSON file (default: compiled_prompts.json in script's directory)"
    )
    parser.add_argument("--ltx-outputs", default=os.environ.get("LTX_OUTPUTS_DIR"))
    parser.add_argument("--sa3-outputs", default=os.environ.get("SA3_OUTPUTS_DIR"))
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Resolve paths relative to cwd or script location
    if os.path.isdir('outputs'):
        ltx_outputs_dir = os.path.abspath('outputs')
    elif os.path.isdir(os.path.join(script_dir, '../outputs')):
        ltx_outputs_dir = os.path.abspath(os.path.join(script_dir, '../outputs'))
    else:
        ltx_outputs_dir = os.path.abspath(os.path.join(script_dir, '../outputs'))

    if args.ltx_outputs:
        ltx_outputs_dir = os.path.abspath(os.path.expanduser(args.ltx_outputs))
    workspace_dir = os.path.dirname(ltx_outputs_dir)
    sa3_outputs_dir = os.path.abspath(os.path.expanduser(args.sa3_outputs)) if args.sa3_outputs else os.path.abspath(os.path.join(workspace_dir, '../sa3/outputs'))

    print(f"Resolving directories:")
    print(f"  ltxVideo Outputs: {ltx_outputs_dir}")
    print(f"  sa3 Outputs:      {sa3_outputs_dir}")

    if not os.path.isdir(ltx_outputs_dir):
        print(f"Error: ltxVideo outputs directory does not exist at '{ltx_outputs_dir}'", file=sys.stderr)
        sys.exit(1)

    if not os.path.isdir(sa3_outputs_dir):
        print(f"Warning: sa3 outputs directory does not exist at '{sa3_outputs_dir}'. Match lookup will be disabled.")

    # 1. Load sa3 tracks
    sa3_tracks = []
    if os.path.isdir(sa3_outputs_dir):
        sa3_manifests = glob.glob(os.path.join(sa3_outputs_dir, "*/manifest.json"))
        print(f"Scanning {len(sa3_manifests)} sa3 manifests...")
        for manifest_path in sa3_manifests:
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                run_dir_name = os.path.basename(os.path.dirname(manifest_path))
                tracks_list = data.get("tracks", [])
                if not isinstance(tracks_list, list):
                    continue

                for track in tracks_list:
                    if not isinstance(track, dict):
                        continue
                    track_id = track.get("id")
                    if not track_id:
                        continue

                    references = []
                    combined = track.get("combined", {})
                    if isinstance(combined, dict):
                        for k, v in combined.items():
                            if isinstance(v, str) and v:
                                references.append(v)

                    for act in track.get("acts", []):
                        if isinstance(act, dict):
                            for k, v in act.items():
                                if isinstance(v, str) and v and any(ext in v.lower() for ext in ['.flac', '.ogg', '.mp3', '.wav']):
                                    references.append(v)

                    colab_gen = data.get("colab_generation", {})
                    results = []
                    if isinstance(colab_gen, dict):
                        results = colab_gen.get("results", [])
                        if not isinstance(results, list):
                            results = [colab_gen]

                    target_result = None
                    for res in results:
                        if isinstance(res, dict) and res.get("id") == track_id:
                            target_result = res
                            break

                    if target_result is None and len(results) == 1:
                        target_result = results[0]

                    if target_result is None:
                        colab_conf = data.get("colab_config", {})
                        if isinstance(colab_conf, dict):
                            generations = colab_conf.get("generations", [])
                            if isinstance(generations, list):
                                for gen in generations:
                                    if isinstance(gen, dict) and gen.get("id") == track_id:
                                        target_result = gen
                                        break

                    if target_result:
                        output_name = target_result.get("output_name")
                        if output_name:
                            references.append(output_name)
                        audio = target_result.get("audio", {})
                        if isinstance(audio, dict):
                            audio_path = audio.get("path")
                            if audio_path:
                                references.append(audio_path)

                    track_prompt = ""
                    track_neg_prompt = ""
                    track_seed = None
                    track_settings = {}

                    if target_result:
                        track_prompt = target_result.get("prompt") or ""
                        track_neg_prompt = target_result.get("negative_prompt") or ""
                        if "settings" in target_result and isinstance(target_result["settings"], dict):
                            track_seed = target_result["settings"].get("seed")
                            track_settings = target_result["settings"]
                        elif "seed" in target_result:
                            track_seed = target_result.get("seed")

                    if not track_prompt:
                        for act in track.get("acts", []):
                            if isinstance(act, dict) and act.get("prompt"):
                                track_prompt = act["prompt"]
                                if act.get("seed"):
                                    track_seed = act["seed"]
                                break
                    if not track_prompt:
                        config = data.get("config", {})
                        if isinstance(config, dict):
                            for config_track in config.get("tracks", []):
                                if isinstance(config_track, dict) and config_track.get("id") == track_id:
                                    track_prompt = config_track.get("prompt") or ""
                                    break

                    sa3_tracks.append({
                        "sa3_run_directory": run_dir_name,
                        "sa3_track_id": track_id,
                        "prompt": track_prompt,
                        "negative_prompt": track_neg_prompt,
                        "seed": track_seed,
                        "settings": track_settings,
                        "references": list(set(references)),
                        "standard_prompts": data.get("config", {}).get("standard_prompts", {}),
                        "model": data.get("config", {}).get("model", {}) or data.get("colab_config", {}).get("model", {}),
                        "created_at": data.get("created_at")
                    })

            except Exception as e:
                print(f"Warning: Failed to parse sa3 manifest {manifest_path}: {e}")

    # 2. Load ltxVideo upload database
    upload_db_runs = {}
    db_path = os.path.join(ltx_outputs_dir, "upload_database.json")
    if os.path.exists(db_path):
        try:
            with open(db_path, 'r', encoding='utf-8') as f:
                db_data = json.load(f)
                upload_db_runs = db_data.get("runs", {})
            print(f"Loaded {len(upload_db_runs)} runs from upload_database.json")
        except Exception as e:
            print(f"Warning: Failed to load upload database: {e}")

    # 3. Scan ltxVideo manifests
    ltx_manifests = glob.glob(os.path.join(ltx_outputs_dir, "*/manifest.json"))
    print(f"Scanning {len(ltx_manifests)} ltxVideo manifests...")

    ltx_records = []
    match_count = 0

    for manifest_path in ltx_manifests:
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            run_dir_name = os.path.basename(os.path.dirname(manifest_path))

            # Skip motion proof folders
            if run_dir_name in ["motion-proof"]:
                continue

            music_data = data.get("music", {})
            music_path = ""
            music_duration = 0.0
            if isinstance(music_data, dict):
                music_path = music_data.get("path") or ""
                music_duration = music_data.get("duration_seconds") or 0.0

            matched_track = match_music_track(music_path, sa3_tracks)
            if matched_track:
                match_count += 1

            db_music_title = ""
            db_video_title = ""
            db_video_description = ""
            db_shorts = {}

            if run_dir_name in upload_db_runs:
                run_db = upload_db_runs[run_dir_name]
                db_music_title = run_db.get("music", {}).get("title") or ""
                db_video_title = run_db.get("full_video", {}).get("title") or ""
                db_video_description = run_db.get("full_video", {}).get("description") or ""
                db_shorts = run_db.get("shorts") or {}

            music_info = {
                "title": db_music_title or (matched_track["sa3_track_id"] if matched_track else ""),
                "filename": os.path.basename(music_path) if music_path else "",
                "path": music_path,
                "duration_seconds": music_duration,
                "sa3_match_found": matched_track is not None
            }

            if matched_track:
                prompt_text = matched_track["prompt"] or ""
                lyrics_text = ""
                clean_prompt_text = prompt_text

                # Find case-insensitive "lyrics:"
                lyrics_match = re.search(r'(?i)\blyrics:\s*(.*)', prompt_text, re.DOTALL)
                if lyrics_match:
                    lyrics_text = lyrics_match.group(1).strip()
                    if (lyrics_text.startswith('"') and lyrics_text.endswith('"')) or (lyrics_text.startswith("'") and lyrics_text.endswith("'")):
                        lyrics_text = lyrics_text[1:-1].strip()

                    # Split off the lyrics from the prompt
                    clean_parts = re.split(r'(?i)\blyrics:', prompt_text, maxsplit=1)
                    clean_prompt_text = clean_parts[0].strip()

                music_info.update({
                    "sa3_run_directory": matched_track["sa3_run_directory"],
                    "sa3_track_id": matched_track["sa3_track_id"],
                    "prompt": prompt_text,
                    "clean_prompt": clean_prompt_text,
                    "lyrics": lyrics_text if lyrics_text else None,
                    "negative_prompt": matched_track["negative_prompt"],
                    "seed": matched_track["seed"],
                    "created_at": matched_track["created_at"],
                    "model": matched_track["model"],
                    "settings": matched_track["settings"],
                    "standard_prompts": matched_track["standard_prompts"]
                })

            video_metadata = {
                "title": db_video_title,
                "description": db_video_description,
                "settings": data.get("settings", {}),
                "selection_seed": data.get("selection_seed"),
                "shorts": db_shorts,
                "clips": []
            }

            clips = data.get("clips", [])
            if isinstance(clips, list):
                for clip in clips:
                    if not isinstance(clip, dict):
                        continue
                    video_metadata["clips"].append({
                        "id": clip.get("id"),
                        "index": clip.get("index"),
                        "image_path": clip.get("image_path"),
                        "motion_prompt": clip.get("motion_prompt"),
                        "prompt": clip.get("prompt"),
                        "seed": clip.get("seed"),
                        "clip_path": clip.get("clip_path"),
                        "status": clip.get("status"),
                        "generation_sha256": clip.get("generation_sha256")
                    })

            record = {
                "ltx_run_directory": run_dir_name,
                "ltx_run_path": os.path.dirname(manifest_path),
                "created_at": data.get("created_at"),
                "updated_at": data.get("updated_at"),
                "status": data.get("status"),
                "music_track": music_info,
                "video_metadata": video_metadata
            }

            ltx_records.append(record)

        except Exception as e:
            print(f"Warning: Failed to parse ltxVideo manifest {manifest_path}: {e}")

    print(f"Total ltxVideo runs scanned: {len(ltx_records)}")
    print(f"Successfully matched with sa3 music tracks: {match_count} / {len(ltx_records)}")

    # Sort records by run directory name (effectively by date)
    ltx_records.sort(key=lambda r: r["ltx_run_directory"], reverse=True)

    # 4. Write output
    output_path = args.output
    if not output_path:
        output_path = os.path.join(script_dir, "compiled_prompts.json")

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(ltx_records, f, indent=2, ensure_ascii=False)
        print(f"Successfully wrote compiled prompts to: {output_path}")
    except Exception as e:
        print(f"Error: Failed to write output JSON to '{output_path}': {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
