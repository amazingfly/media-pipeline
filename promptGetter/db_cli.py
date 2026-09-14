#!/usr/bin/env python3
import os
import sys
import json
import argparse

# Standard convenient aliases
aliases = {
    "title": "music_track.title",
    "music_title": "music_track.title",
    "video_title": "video_metadata.title",
    "prompt": "music_track.prompt",
    "music_prompt": "music_track.prompt",
    "video_prompt": "video_metadata.clips.prompt",
    "clips_prompt": "video_metadata.clips.prompt",
    "seed": "music_track.seed",
    "music_seed": "music_track.seed",
    "selection_seed": "video_metadata.selection_seed",
    "dir": "ltx_run_directory",
    "directory": "ltx_run_directory",
    "lyrics": "music_track.lyrics",
    "clean_prompt": "music_track.clean_prompt"
}

def load_database():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(script_dir, "compiled_prompts.json")
    if not os.path.exists(db_path):
        print(f"Error: Compiled database not found at '{db_path}'.")
        print("Please run 'python get_prompts.py' first to compile the metadata.", file=sys.stderr)
        sys.exit(1)

    try:
        with open(db_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading database: {e}", file=sys.stderr)
        sys.exit(1)

def get_all_paths(data):
    paths = set()
    def recurse(curr, current_path=""):
        if isinstance(curr, dict):
            for k, v in curr.items():
                new_path = f"{current_path}.{k}" if current_path else k
                recurse(v, new_path)
        elif isinstance(curr, list) and curr:
            for item in curr:
                recurse(item, current_path)
        else:
            if current_path:
                paths.add(current_path)

    for run in data:
        recurse(run)
    return sorted(list(paths))

def extract_field(data, field_path):
    parts = field_path.split('.')

    def recurse(curr, parts_left):
        if not parts_left:
            return curr

        part = parts_left[0]
        if isinstance(curr, dict):
            if part in curr:
                return recurse(curr[part], parts_left[1:])
            return None
        elif isinstance(curr, list):
            res = []
            for item in curr:
                val = recurse(item, parts_left)
                if val is not None:
                    if isinstance(val, list):
                        res.extend(val)
                    else:
                        res.append(val)
            return res if res else None
        return None

    return recurse(data, parts)

def resolve_field(field_str, all_paths):
    field_str = field_str.strip()

    # 1. Check alias
    if field_str in aliases:
        return aliases[field_str], field_str

    # 2. Check exact path
    if field_str in all_paths:
        key_name = field_str.split('.')[-1]
        return field_str, key_name

    # 3. Check suffix match
    for path in all_paths:
        if path.endswith('.' + field_str) or path == field_str:
            return path, field_str

    return None, None

def print_fields(all_paths):
    print("\nAvailable Fields:")
    print("-----------------")
    # Show Aliases first
    print("Common Aliases:")
    for alias, target in sorted(aliases.items()):
        print(f"  {alias:<15} -> {target}")

    print("\nAll Fields (Dotted Path Notation):")
    for path in all_paths:
        print(f"  {path}")

def search_database(data, query):
    query = query.lower()
    results = []

    for run in data:
        # Fields to check
        dir_name = run.get("ltx_run_directory", "")
        music_title = run.get("music_track", {}).get("title", "")
        music_prompt = run.get("music_track", {}).get("prompt", "")
        video_title = run.get("video_metadata", {}).get("title", "")

        clips = run.get("video_metadata", {}).get("clips", [])
        clip_prompts = [c.get("prompt", "") for c in clips] + [c.get("motion_prompt", "") for c in clips]

        # Check matching
        match = (
            query in dir_name.lower() or
            query in music_title.lower() or
            query in music_prompt.lower() or
            query in video_title.lower() or
            any(query in cp.lower() for cp in clip_prompts)
        )

        if match:
            results.append(run)

    return results

def print_results(results):
    if not results:
        print("No matches found.")
        return

    print(f"\nFound {len(results)} matches:")
    print("=" * 60)
    for run in results:
        print(f"Directory:    {run.get('ltx_run_directory')}")
        print(f"Music Title:  {run.get('music_track', {}).get('title')}")
        music_prompt = run.get('music_track', {}).get('prompt', '')
        if len(music_prompt) > 80:
            music_prompt = music_prompt[:77] + "..."
        print(f"Music Prompt: {music_prompt}")
        print(f"Clips Count:  {len(run.get('video_metadata', {}).get('clips', []))}")
        print("-" * 60)

def export_fields(data, fields_str, all_paths, output_path):
    field_inputs = [f.strip() for f in fields_str.split(",") if f.strip()]
    resolved_fields = []

    for f in field_inputs:
        path, key_name = resolve_field(f, all_paths)
        if path:
            resolved_fields.append((f, path, key_name))
        else:
            print(f"Error: Field '{f}' not recognized.", file=sys.stderr)
            print("Use the 'list' command to see all available fields.", file=sys.stderr)
            sys.exit(1)

    exported_data = []
    for run in data:
        item = {}
        for original_input, path, key_name in resolved_fields:
            val = extract_field(run, path)
            # Use the user's input key name for output mapping
            item[original_input] = val
        exported_data.append(item)

    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(exported_data, f, indent=2, ensure_ascii=False)
        print(f"Successfully exported {len(exported_data)} records to '{output_path}'")
    except Exception as e:
        print(f"Error writing export file: {e}", file=sys.stderr)
        sys.exit(1)

def interactive_mode(data, all_paths):
    while True:
        print("\n--- JSON Database CLI Menu ---")
        print("1. List all available fields & aliases")
        print("2. Search database")
        print("3. Export specific fields to a JSON file")
        print("4. Exit")

        choice = input("Select an option (1-4): ").strip()
        if choice == '1':
            print_fields(all_paths)
        elif choice == '2':
            query = input("Enter search query: ").strip()
            if query:
                results = search_database(data, query)
                print_results(results)
        elif choice == '3':
            fields_str = input("Enter fields to export (comma-separated, e.g., 'title, prompt'): ").strip()
            if fields_str:
                output_file = input("Enter output filename (default: export.json): ").strip()
                if not output_file:
                    output_file = "export.json"
                export_fields(data, fields_str, all_paths, output_file)
        elif choice == '4':
            print("Goodbye!")
            break
        else:
            print("Invalid choice, please select 1-4.")

def main():
    data = load_database()
    all_paths = get_all_paths(data)

    parser = argparse.ArgumentParser(description="Basic JSON database CLI tool.")
    subparsers = parser.add_subparsers(dest="command", help="Sub-command to execute")

    # List sub-command
    subparsers.add_parser("list", help="List all fields and aliases in the database")

    # Search sub-command
    search_parser = subparsers.add_parser("search", help="Search the database by query text")
    search_parser.add_argument("query", help="Text query to search for")

    # Export sub-command
    export_parser = subparsers.add_parser("export", help="Export specific fields to a JSON file")
    export_parser.add_argument("fields", help="Comma-separated list of fields/aliases to export")
    export_parser.add_argument("-o", "--output", default="export.json", help="Path to save the exported JSON file")

    args = parser.parse_args()

    if args.command == "list":
        print_fields(all_paths)
    elif args.command == "search":
        results = search_database(data, args.query)
        print_results(results)
    elif args.command == "export":
        export_fields(data, args.fields, all_paths, args.output)
    else:
        # No args, enter interactive mode
        interactive_mode(data, all_paths)

if __name__ == "__main__":
    main()
