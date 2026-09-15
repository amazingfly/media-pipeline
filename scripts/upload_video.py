#!/usr/bin/env python3
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
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUTH_DIR = Path(os.environ.get("MEDIA_AUTH_ROOT", str(PROJECT_ROOT / "auth")))
DEFAULT_OUTPUTS_DIR = Path(os.environ.get("LTX_OUTPUTS_DIR", str(PROJECT_ROOT / "outputs")))
DEFAULT_DATABASE = DEFAULT_OUTPUTS_DIR / "upload_database.json"
DEFAULT_YOUTUBE_CLIENT_SECRETS = DEFAULT_AUTH_DIR / "client_secret.json"
DEFAULT_YOUTUBE_TOKEN = DEFAULT_AUTH_DIR / "youtube_token.json"
DEFAULT_FACEBOOK_PAGE_ID_FILE = DEFAULT_AUTH_DIR / "facebook_page_id.txt"
DEFAULT_FACEBOOK_PAGE_ACCESS_TOKEN_FILE = (
    DEFAULT_AUTH_DIR / "facebook_page_access_token.txt"
)
DEFAULT_FACEBOOK_VERSION = "v25.0"
YOUTUBE_SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
)
YOUTUBE_CATEGORY_MUSIC = "10"


class UploadConfigError(RuntimeError):
    pass


class ApiUploadError(RuntimeError):
    pass


@dataclass(frozen=True)
class ShortSource:
    index: int
    path: Path
    source: str
    selection: dict[str, Any] | None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = utc_now()
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_database(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "version": 1,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "runs": {},
        }
    data = load_json(path)
    data.setdefault("version", 1)
    data.setdefault("runs", {})
    return data


def read_auth_text(path: Path) -> str | None:
    if not path.is_file():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Upload one generated run: full video to YouTube, then the selected "
            "short to YouTube Shorts and Facebook Reels."
        )
    )
    parser.add_argument("--outputs-dir", type=Path, default=DEFAULT_OUTPUTS_DIR)
    parser.add_argument("--db", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument(
        "--run-label",
        "--run",
        help=(
            "Run directory name under outputs/. Defaults to the newest run with "
            "manifest.json and music_video.mp4."
        ),
    )
    parser.add_argument(
        "--short-index",
        type=int,
        help=(
            "Selected short number, e.g. 1 through 5. If omitted, the script "
            "tries to infer it from shorts/1This/."
        ),
    )
    parser.add_argument(
        "--current-short-dir",
        default="1This",
        help=(
            "Temporary directory containing the currently chosen short. This keeps "
            "today's workflow working while the DB still records --short-index."
        ),
    )
    parser.add_argument("--music-title")
    parser.add_argument("--full-title")
    parser.add_argument("--full-description")
    parser.add_argument("--short-title")
    parser.add_argument("--short-hashtags")
    parser.add_argument("--youtube-full-playlist-id", action="append", default=[])
    parser.add_argument("--youtube-short-playlist-id", action="append", default=[])
    parser.add_argument(
        "--full-privacy",
        choices=("private", "unlisted", "public"),
        help="YouTube privacy status for the full upload.",
    )
    parser.add_argument(
        "--short-privacy",
        choices=("private", "unlisted", "public"),
        help="YouTube privacy status for the short upload.",
    )
    parser.add_argument(
        "--made-for-kids",
        action="store_true",
        help="Set YouTube selfDeclaredMadeForKids=true. Defaults to false.",
    )
    parser.add_argument(
        "--youtube-client-secrets",
        type=Path,
        default=Path(
            os.environ.get(
                "YOUTUBE_CLIENT_SECRETS",
                str(DEFAULT_YOUTUBE_CLIENT_SECRETS),
            )
        ),
        help=(
            "OAuth client JSON from Google Cloud. Can also be set with "
            "YOUTUBE_CLIENT_SECRETS. Defaults to auth/client_secret.json."
        ),
    )
    parser.add_argument(
        "--youtube-token",
        type=Path,
        default=Path(os.environ.get("YOUTUBE_TOKEN_FILE", str(DEFAULT_YOUTUBE_TOKEN))),
        help=(
            "Stored OAuth token path. Can also be set with YOUTUBE_TOKEN_FILE. "
            "Defaults to auth/youtube_token.json."
        ),
    )
    parser.add_argument(
        "--youtube-no-browser",
        action="store_true",
        help="Do not open the browser automatically during OAuth.",
    )
    parser.add_argument(
        "--facebook-page-id",
        default=os.environ.get("FACEBOOK_PAGE_ID")
        or read_auth_text(DEFAULT_FACEBOOK_PAGE_ID_FILE),
        help=(
            "Facebook Page ID. Can also be set with FACEBOOK_PAGE_ID. Defaults "
            "to auth/facebook_page_id.txt."
        ),
    )
    parser.add_argument(
        "--facebook-page-access-token",
        default=os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN")
        or read_auth_text(DEFAULT_FACEBOOK_PAGE_ACCESS_TOKEN_FILE),
        help=(
            "Facebook Page access token. Can also be set with "
            "FACEBOOK_PAGE_ACCESS_TOKEN. Defaults to "
            "auth/facebook_page_access_token.txt."
        ),
    )
    parser.add_argument(
        "--facebook-api-version",
        default=os.environ.get("FACEBOOK_API_VERSION", DEFAULT_FACEBOOK_VERSION),
    )
    parser.add_argument(
        "--facebook-comment-wait-seconds",
        type=int,
        default=120,
        help="How long to retry the best-effort first Reel comment.",
    )
    parser.add_argument("--skip-youtube-full", action="store_true")
    parser.add_argument("--skip-youtube-short", action="store_true")
    parser.add_argument("--skip-facebook-short", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Upload again even when the DB already has a URL for this slot.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the final interactive confirmation prompt.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve files, collect metadata, print the plan, and exit without writes or uploads.",
    )
    return parser.parse_args()


def newest_completed_run(outputs_dir: Path) -> Path:
    if not outputs_dir.is_dir():
        raise UploadConfigError(f"Outputs directory does not exist: {outputs_dir}")
    candidates = [
        child
        for child in outputs_dir.iterdir()
        if child.is_dir()
        and (child / "manifest.json").is_file()
        and (child / "music_video.mp4").is_file()
    ]
    if not candidates:
        raise UploadConfigError(
            f"No completed runs with manifest.json and music_video.mp4 in {outputs_dir}"
        )
    return sorted(candidates, key=lambda path: path.name)[-1]


def resolve_run_dir(outputs_dir: Path, run_label: str | None) -> Path:
    outputs_dir = outputs_dir.resolve()
    if run_label:
        run_dir = outputs_dir / run_label
        if not run_dir.is_dir():
            raise UploadConfigError(f"Run directory does not exist: {run_dir}")
        return run_dir.resolve()
    return newest_completed_run(outputs_dir).resolve()


def infer_short_index_from_name(path: Path) -> int | None:
    match = re.search(r"(?:^|_)short_(\d+)(?:_|$)", path.name)
    if match:
        return int(match.group(1))
    match = re.search(r"short_(\d+)", path.name)
    if match:
        return int(match.group(1))
    return None


def load_short_selections(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "shorts" / "selections.json"
    if not path.is_file():
        return []
    data = load_json(path)
    selections = data.get("selections", [])
    if not isinstance(selections, list):
        return []
    return [item for item in selections if isinstance(item, dict)]


def selection_for_index(selections: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    if 1 <= index <= len(selections):
        return selections[index - 1]
    return None


def resolve_short_source(
    run_dir: Path,
    requested_index: int | None,
    current_short_dir: str,
) -> ShortSource:
    selections = load_short_selections(run_dir)
    current_dir = run_dir / "shorts" / current_short_dir
    current_files = sorted(current_dir.glob("*.mp4")) if current_dir.is_dir() else []
    if current_files:
        path = current_files[0].resolve()
        inferred_index = infer_short_index_from_name(path)
        index = requested_index or inferred_index
        if index is None:
            raise UploadConfigError(
                f"Could not infer the short index from {path.name}; pass --short-index."
            )
        return ShortSource(
            index=index,
            path=path,
            source=f"shorts/{current_short_dir}",
            selection=selection_for_index(selections, index),
        )

    if requested_index is None:
        raise UploadConfigError(
            f"No MP4 found in {current_dir}; pass --short-index to use shorts/short_N_*.mp4."
        )
    selection = selection_for_index(selections, requested_index)
    if selection and selection.get("exported_path"):
        exported_path = Path(str(selection["exported_path"]))
        if exported_path.is_file():
            return ShortSource(
                index=requested_index,
                path=exported_path.resolve(),
                source="shorts/selections.json",
                selection=selection,
            )
    matches = sorted((run_dir / "shorts").glob(f"short_{requested_index}_*.mp4"))
    if matches:
        return ShortSource(
            index=requested_index,
            path=matches[0].resolve(),
            source="shorts/short_N_*.mp4",
            selection=selection,
        )
    raise UploadConfigError(
        f"Could not find a video file for short index {requested_index} under {run_dir / 'shorts'}"
    )


def prompt_value(label: str, default: str | None = None, required: bool = True) -> str:
    if not sys.stdin.isatty():
        if default is not None:
            return default
        if not required:
            return ""
        raise UploadConfigError(f"{label} is required in noninteractive mode.")
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if value:
            return value
        if default is not None:
            return default
        if not required:
            return ""
        print("A value is required.")


def prompt_choice(label: str, default: str, choices: tuple[str, ...]) -> str:
    choices_text = "/".join(choices)
    while True:
        value = prompt_value(f"{label} ({choices_text})", default=default).lower()
        if value in choices:
            return value
        print(f"Choose one of: {choices_text}")


def prompt_playlist_ids(label: str, defaults: list[str]) -> list[str]:
    default_text = ", ".join(defaults) if defaults else None
    raw = prompt_value(label, default=default_text, required=False)
    return [item.strip() for item in raw.split(",") if item.strip()]


def title_from_music_path(path: Path) -> str:
    stem = path.stem
    stem = re.sub(r"-\d+s-[0-9a-f]+-\d+$", "", stem)
    stem = re.sub(r"[_-]+", " ", stem)
    return " ".join(word.capitalize() for word in stem.split())


def hashtags_from_title(title: str) -> str:
    tags = []
    for word in re.findall(r"[A-Za-z0-9]+", title):
        if word.lower() in {"a", "an", "and", "the"}:
            continue
        tags.append("#" + word[:1].upper() + word[1:])
    return " ".join(tags[:6])


def default_full_description(title: str) -> str:
    return (
        f"A {title} track generated with Stable Audio 3, images generated with "
        "Stable Diffusion 1.5 and videos generated with LTXVideo."
    )


def ensure_record(database: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    run_label = run_dir.name
    runs = database.setdefault("runs", {})
    record = runs.setdefault(
        run_label,
        {
            "created_at": utc_now(),
            "run_label": run_label,
        },
    )
    record["run_label"] = run_label
    record["run_dir"] = str(run_dir)
    record["updated_at"] = utc_now()
    return record


def collect_metadata(
    args: argparse.Namespace,
    record: dict[str, Any],
    manifest: dict[str, Any],
    run_dir: Path,
    short_source: ShortSource,
) -> dict[str, Any]:
    music_path = Path(str(manifest["music"]["path"])).resolve()
    previous_music = record.get("music", {}) if isinstance(record.get("music"), dict) else {}
    music_title_default = (
        args.music_title
        or previous_music.get("title")
        or title_from_music_path(music_path)
    )
    full_video = record.get("full_video", {})
    if not isinstance(full_video, dict):
        full_video = {}
    short_record = (
        record.get("shorts", {})
        if isinstance(record.get("shorts"), dict)
        else {}
    ).get(str(short_source.index), {})
    if not isinstance(short_record, dict):
        short_record = {}

    full_title = args.full_title or prompt_value(
        "Full YouTube title",
        default=full_video.get("title") or music_title_default,
    )
    music_title = args.music_title or prompt_value(
        "Music track title",
        default=music_title_default,
    )
    full_description = args.full_description or prompt_value(
        "Full YouTube description",
        default=full_video.get("description") or default_full_description(full_title),
    )
    short_hashtags = args.short_hashtags or prompt_value(
        "Short hashtags",
        default=short_record.get("hashtags") or hashtags_from_title(full_title),
    )
    short_title = args.short_title or prompt_value(
        "Short YouTube title",
        default=short_record.get("title") or f"{short_hashtags} Short",
    )
    full_playlist_ids = args.youtube_full_playlist_id or prompt_playlist_ids(
        "Full YouTube playlist IDs (comma-separated; stubbed for now)",
        defaults=full_video.get("youtube", {}).get("playlist_ids_requested", [])
        if isinstance(full_video.get("youtube"), dict)
        else [],
    )
    short_playlist_ids = args.youtube_short_playlist_id or prompt_playlist_ids(
        "Short YouTube playlist IDs (comma-separated; stubbed for now)",
        defaults=short_record.get("youtube", {}).get("playlist_ids_requested", [])
        if isinstance(short_record.get("youtube"), dict)
        else [],
    )
    full_privacy = args.full_privacy or prompt_choice(
        "Full YouTube privacy",
        default=full_video.get("youtube", {}).get("privacy_status", "unlisted")
        if isinstance(full_video.get("youtube"), dict)
        else "unlisted",
        choices=("private", "unlisted", "public"),
    )
    short_privacy = args.short_privacy or prompt_choice(
        "Short YouTube privacy",
        default=short_record.get("youtube", {}).get("privacy_status", "unlisted")
        if isinstance(short_record.get("youtube"), dict)
        else "unlisted",
        choices=("private", "unlisted", "public"),
    )

    metadata = {
        "music_path": music_path,
        "music_title": music_title,
        "full_title": full_title,
        "full_description": full_description,
        "short_title": short_title,
        "short_hashtags": short_hashtags,
        "full_playlist_ids": full_playlist_ids,
        "short_playlist_ids": short_playlist_ids,
        "full_privacy": full_privacy,
        "short_privacy": short_privacy,
    }

    record["music"] = {
        "title": music_title,
        "path": str(music_path),
        "duration_seconds": manifest["music"].get("duration_seconds"),
    }
    record["full_video"] = {
        **full_video,
        "path": str((run_dir / "music_video.mp4").resolve()),
        "title": full_title,
        "description": full_description,
    }
    shorts = record.setdefault("shorts", {})
    shorts[str(short_source.index)] = {
        **short_record,
        "index": short_source.index,
        "path": str(short_source.path),
        "source": short_source.source,
        "selection": short_source.selection,
        "title": short_title,
        "hashtags": short_hashtags,
    }
    record["current_short_index"] = short_source.index
    return metadata


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise UploadConfigError(f"{label} does not exist: {path}")


def youtube_slot_has_url(record: dict[str, Any], slot: str) -> bool:
    data = record.get(slot, {})
    if not isinstance(data, dict):
        return False
    youtube = data.get("youtube", {})
    return isinstance(youtube, dict) and bool(youtube.get("url"))


def youtube_short_has_url(record: dict[str, Any], index: int) -> bool:
    shorts = record.get("shorts", {})
    if not isinstance(shorts, dict):
        return False
    short_record = shorts.get(str(index), {})
    if not isinstance(short_record, dict):
        return False
    youtube = short_record.get("youtube", {})
    return isinstance(youtube, dict) and bool(youtube.get("url"))


def facebook_short_has_url(record: dict[str, Any], index: int) -> bool:
    shorts = record.get("shorts", {})
    if not isinstance(shorts, dict):
        return False
    short_record = shorts.get(str(index), {})
    if not isinstance(short_record, dict):
        return False
    facebook = short_record.get("facebook", {})
    return isinstance(facebook, dict) and bool(facebook.get("url"))


def preflight(args: argparse.Namespace, record: dict[str, Any], short_index: int) -> None:
    if args.dry_run:
        return
    need_youtube = False
    if (
        not args.skip_youtube_full
        and (args.force or not youtube_slot_has_url(record, "full_video"))
    ):
        need_youtube = True
    if (
        not args.skip_youtube_short
        and (args.force or not youtube_short_has_url(record, short_index))
    ):
        need_youtube = True
    if need_youtube:
        token_exists = args.youtube_token.expanduser().is_file()
        secrets_exists = args.youtube_client_secrets.expanduser().is_file()
        if not token_exists and not secrets_exists:
            raise UploadConfigError(
                "YouTube upload needs OAuth credentials. Pass "
                "--youtube-client-secrets /path/to/client_secret.json or set "
                "YOUTUBE_CLIENT_SECRETS. By default, place the OAuth client "
                f"JSON at {args.youtube_client_secrets.expanduser()}. A reusable "
                f"token will be saved to {args.youtube_token.expanduser()}."
            )

    if (
        not args.skip_facebook_short
        and (args.force or not facebook_short_has_url(record, short_index))
    ):
        if not args.facebook_page_id:
            raise UploadConfigError(
                "Facebook Reels upload needs --facebook-page-id or FACEBOOK_PAGE_ID."
            )
        if not args.facebook_page_access_token:
            raise UploadConfigError(
                "Facebook Reels upload needs --facebook-page-access-token or "
                "FACEBOOK_PAGE_ACCESS_TOKEN."
            )


def confirm_plan(
    args: argparse.Namespace,
    run_dir: Path,
    short_source: ShortSource,
    metadata: dict[str, Any],
) -> None:
    print()
    print("Upload plan")
    print(f"  Run: {run_dir.name}")
    print(f"  Full video: {run_dir / 'music_video.mp4'}")
    print(f"  Short #{short_source.index}: {short_source.path}")
    print(f"  Music: {metadata['music_title']}")
    print(f"  Full YouTube title: {metadata['full_title']}")
    print(f"  Short YouTube title: {metadata['short_title']}")
    print(f"  Short hashtags: {metadata['short_hashtags']}")
    print(f"  Full privacy: {metadata['full_privacy']}")
    print(f"  Short privacy: {metadata['short_privacy']}")
    if args.dry_run:
        print("Dry run: no uploads will be started.")
        return
    if args.yes:
        return
    answer = input("Proceed with uploads? [y/N]: ").strip().lower()
    if answer not in {"y", "yes"}:
        raise UploadConfigError("Aborted before upload.")


def build_youtube_service(args: argparse.Namespace) -> Any:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise UploadConfigError(
            "YouTube upload requires google-api-python-client and "
            "google-auth-oauthlib."
        ) from exc

    token_path = args.youtube_token.expanduser()
    client_secrets_path = args.youtube_client_secrets.expanduser()
    credentials = None
    if token_path.is_file():
        credentials = Credentials.from_authorized_user_file(
            str(token_path), list(YOUTUBE_SCOPES)
        )
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    if not credentials or not credentials.valid:
        require_file(client_secrets_path, "YouTube OAuth client secrets")
        flow = InstalledAppFlow.from_client_secrets_file(
            str(client_secrets_path), list(YOUTUBE_SCOPES)
        )
        credentials = flow.run_local_server(
            port=0,
            open_browser=not args.youtube_no_browser,
            prompt="consent",
        )
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json() + "\n", encoding="utf-8")
    return build("youtube", "v3", credentials=credentials)


def execute_youtube_resumable(request: Any, label: str, max_retries: int = 8) -> dict[str, Any]:
    try:
        import httplib2
        from googleapiclient.errors import HttpError
    except ImportError as exc:
        raise UploadConfigError("Missing YouTube upload dependencies.") from exc

    retriable_exceptions = (httplib2.HttpLib2Error, OSError)
    retriable_status_codes = {500, 502, 503, 504}
    response = None
    retry = 0
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                print(f"{label}: {int(status.progress() * 100)}% uploaded")
        except HttpError as exc:
            status_code = getattr(exc.resp, "status", None)
            if status_code not in retriable_status_codes or retry >= max_retries:
                raise
            retry += 1
            sleep_seconds = min(60, 2**retry)
            print(f"{label}: retrying after HTTP {status_code} in {sleep_seconds}s")
            time.sleep(sleep_seconds)
        except retriable_exceptions as exc:
            if retry >= max_retries:
                raise
            retry += 1
            sleep_seconds = min(60, 2**retry)
            print(f"{label}: retrying after {exc!r} in {sleep_seconds}s")
            time.sleep(sleep_seconds)
    if "id" not in response:
        raise ApiUploadError(f"YouTube upload returned no video id: {response}")
    return response


def upload_youtube_video(
    service: Any,
    video_path: Path,
    title: str,
    description: str,
    privacy_status: str,
    made_for_kids: bool,
) -> dict[str, str]:
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise UploadConfigError("Missing google-api-python-client.") from exc

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": YOUTUBE_CATEGORY_MUSIC,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": made_for_kids,
            "containsSyntheticMedia": True,
        },
    }
    media = MediaFileUpload(str(video_path), chunksize=8 * 1024 * 1024, resumable=True)
    request = service.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )
    response = execute_youtube_resumable(request, title)
    video_id = response["id"]
    return {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "uploaded_at": utc_now(),
        "privacy_status": privacy_status,
    }


def record_youtube_playlist_stub(
    youtube_record: dict[str, Any],
    playlist_ids: list[str],
) -> None:
    # PLAYLIST STUB:
    # This records intended playlist membership but intentionally does not call
    # playlistItems.insert yet. Once playlist routing is settled, replace this
    # block with real YouTube playlist insertion and store each playlistItem id.
    youtube_record["playlist_ids_requested"] = playlist_ids
    youtube_record["playlist_status"] = "stub_not_implemented"
    if playlist_ids:
        print(f"Playlist stub recorded for: {', '.join(playlist_ids)}")


def short_youtube_description(full_url: str) -> str:
    return full_url


def facebook_reel_description(full_url: str, hashtags: str) -> str:
    return f"{full_url}\n{hashtags}"


class FacebookClient:
    def __init__(self, page_access_token: str, api_version: str) -> None:
        try:
            import requests
        except ImportError as exc:
            raise UploadConfigError("Facebook upload requires requests.") from exc
        self.requests = requests
        self.page_access_token = page_access_token
        self.graph_base = f"https://graph.facebook.com/{api_version}"

    def _handle_response(self, response: Any) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise ApiUploadError(
                f"Non-JSON Facebook response {response.status_code}: {response.text[:500]}"
            ) from exc
        if response.status_code >= 400 or "error" in data:
            raise ApiUploadError(f"Facebook API error: {data}")
        return data

    def graph_post(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        payload = {**data, "access_token": self.page_access_token}
        response = self.requests.post(
            f"{self.graph_base}/{path.lstrip('/')}",
            data=payload,
            timeout=120,
        )
        return self._handle_response(response)

    def graph_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = {**params, "access_token": self.page_access_token}
        response = self.requests.get(
            f"{self.graph_base}/{path.lstrip('/')}",
            params=query,
            timeout=60,
        )
        return self._handle_response(response)

    def start_reel_upload(self, page_id: str) -> dict[str, Any]:
        return self.graph_post(f"{page_id}/video_reels", {"upload_phase": "start"})

    def upload_reel_binary(self, upload_url: str, video_path: Path) -> dict[str, Any]:
        headers = {
            "Authorization": f"OAuth {self.page_access_token}",
            "offset": "0",
            "file_size": str(video_path.stat().st_size),
            "Content-Type": "application/octet-stream",
        }
        with video_path.open("rb") as handle:
            response = self.requests.post(
                upload_url,
                headers=headers,
                data=handle,
                timeout=(30, 1800),
            )
        return self._handle_response(response)

    def finish_reel_upload(
        self,
        page_id: str,
        video_id: str,
        title: str,
        description: str,
    ) -> dict[str, Any]:
        return self.graph_post(
            f"{page_id}/video_reels",
            {
                "upload_phase": "finish",
                "video_id": video_id,
                "video_state": "PUBLISHED",
                "title": title,
                "description": description,
            },
        )

    def reel_status(self, video_id: str) -> dict[str, Any]:
        return self.graph_get(video_id, {"fields": "status"})

    def add_comment(self, object_id: str, message: str) -> dict[str, Any]:
        return self.graph_post(f"{object_id}/comments", {"message": message})


def upload_facebook_reel(
    client: FacebookClient,
    page_id: str,
    video_path: Path,
    title: str,
    description: str,
) -> dict[str, Any]:
    start = client.start_reel_upload(page_id)
    video_id = str(start.get("video_id", ""))
    upload_url = str(start.get("upload_url", ""))
    if not video_id or not upload_url:
        raise ApiUploadError(f"Facebook did not return video_id and upload_url: {start}")
    upload = client.upload_reel_binary(upload_url, video_path)
    finish = client.finish_reel_upload(page_id, video_id, title, description)
    return {
        "video_id": video_id,
        "url": f"https://www.facebook.com/reel/{video_id}",
        "uploaded_at": utc_now(),
        "description": description,
        "start_response": start,
        "upload_response": upload,
        "finish_response": finish,
    }


def add_facebook_first_comment_best_effort(
    client: FacebookClient,
    video_id: str,
    message: str,
    wait_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + max(0, wait_seconds)
    last_error = None
    while True:
        try:
            response = client.add_comment(video_id, message)
            return {
                "status": "posted",
                "message": message,
                "response": response,
                "posted_at": utc_now(),
            }
        except Exception as exc:  # Best effort: Reel objects can lag commentability.
            last_error = str(exc)
            if time.monotonic() >= deadline:
                return {
                    "status": "failed",
                    "message": message,
                    "error": last_error,
                    "attempted_at": utc_now(),
                }
            time.sleep(10)


def full_youtube_record(record: dict[str, Any]) -> dict[str, Any]:
    full = record.setdefault("full_video", {})
    return full.setdefault("youtube", {})


def short_record(record: dict[str, Any], index: int) -> dict[str, Any]:
    return record.setdefault("shorts", {}).setdefault(str(index), {"index": index})


def short_youtube_record(record: dict[str, Any], index: int) -> dict[str, Any]:
    return short_record(record, index).setdefault("youtube", {})


def short_facebook_record(record: dict[str, Any], index: int) -> dict[str, Any]:
    return short_record(record, index).setdefault("facebook", {})


def run() -> int:
    args = parse_args()
    run_dir = resolve_run_dir(args.outputs_dir, args.run_label)
    manifest_path = run_dir / "manifest.json"
    full_video_path = run_dir / "music_video.mp4"
    require_file(manifest_path, "Manifest")
    require_file(full_video_path, "Full video")
    manifest = load_json(manifest_path)
    short_source = resolve_short_source(
        run_dir,
        requested_index=args.short_index,
        current_short_dir=args.current_short_dir,
    )
    require_file(short_source.path, "Short video")

    database_path = args.db.resolve()
    database = load_database(database_path)
    record = ensure_record(database, run_dir)
    metadata = collect_metadata(args, record, manifest, run_dir, short_source)
    if not args.dry_run:
        save_json_atomic(database_path, database)

    preflight(args, record, short_source.index)
    confirm_plan(args, run_dir, short_source, metadata)
    if args.dry_run:
        return 0

    youtube_service = None
    full_url = full_youtube_record(record).get("url")
    if args.skip_youtube_full:
        if not full_url:
            raise UploadConfigError(
                "--skip-youtube-full was used, but the DB has no full YouTube URL."
            )
    elif args.force or not full_url:
        youtube_service = youtube_service or build_youtube_service(args)
        print("Uploading full video to YouTube...")
        youtube_result = upload_youtube_video(
            youtube_service,
            full_video_path,
            metadata["full_title"],
            metadata["full_description"],
            metadata["full_privacy"],
            args.made_for_kids,
        )
        youtube_record = full_youtube_record(record)
        youtube_record.update(youtube_result)
        record_youtube_playlist_stub(youtube_record, metadata["full_playlist_ids"])
        save_json_atomic(database_path, database)
        full_url = youtube_result["url"]
        print(f"Full YouTube URL: {full_url}")
    else:
        print(f"Using existing full YouTube URL from DB: {full_url}")
        record_youtube_playlist_stub(full_youtube_record(record), metadata["full_playlist_ids"])
        save_json_atomic(database_path, database)

    if not isinstance(full_url, str) or not full_url:
        raise ApiUploadError("Full YouTube URL is unavailable; cannot upload shorts.")

    yt_short_description = short_youtube_description(full_url)
    fb_description = facebook_reel_description(full_url, metadata["short_hashtags"])
    short = short_record(record, short_source.index)
    short["youtube_description"] = yt_short_description
    short["facebook_description"] = fb_description
    save_json_atomic(database_path, database)

    if args.skip_youtube_short:
        print("Skipping YouTube short upload.")
    elif args.force or not youtube_short_has_url(record, short_source.index):
        youtube_service = youtube_service or build_youtube_service(args)
        print("Uploading short to YouTube...")
        youtube_result = upload_youtube_video(
            youtube_service,
            short_source.path,
            metadata["short_title"],
            yt_short_description,
            metadata["short_privacy"],
            args.made_for_kids,
        )
        youtube_record = short_youtube_record(record, short_source.index)
        youtube_record.update(youtube_result)
        youtube_record["description"] = yt_short_description
        record_youtube_playlist_stub(youtube_record, metadata["short_playlist_ids"])
        save_json_atomic(database_path, database)
        print(f"Short YouTube URL: {youtube_result['url']}")
    else:
        existing = short_youtube_record(record, short_source.index).get("url")
        print(f"Using existing short YouTube URL from DB: {existing}")

    if args.skip_facebook_short:
        print("Skipping Facebook Reel upload.")
    elif args.force or not facebook_short_has_url(record, short_source.index):
        print("Uploading short to Facebook Reels...")
        facebook = FacebookClient(
            page_access_token=args.facebook_page_access_token,
            api_version=args.facebook_api_version,
        )
        facebook_result = upload_facebook_reel(
            facebook,
            str(args.facebook_page_id),
            short_source.path,
            metadata["short_title"],
            fb_description,
        )
        facebook_record = short_facebook_record(record, short_source.index)
        facebook_record.update(facebook_result)
        save_json_atomic(database_path, database)
        print(f"Facebook Reel URL: {facebook_result['url']}")

        comment_result = add_facebook_first_comment_best_effort(
            facebook,
            facebook_result["video_id"],
            full_url,
            args.facebook_comment_wait_seconds,
        )
        facebook_record["first_comment"] = comment_result
        save_json_atomic(database_path, database)
        if comment_result["status"] == "posted":
            print("Facebook first comment posted.")
        else:
            print(f"Facebook first comment failed: {comment_result.get('error')}")
    else:
        existing = short_facebook_record(record, short_source.index).get("url")
        print(f"Using existing Facebook Reel URL from DB: {existing}")

    print(f"Upload database updated: {database_path}")
    return 0


def main() -> None:
    try:
        raise SystemExit(run())
    except (UploadConfigError, ApiUploadError, KeyboardInterrupt) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
