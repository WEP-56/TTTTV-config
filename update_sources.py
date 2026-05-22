#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_SOURCE_URL = "https://github.com/hafrey1/LunaTV-config/blob/main/jin18.json"
DEFAULT_TARGET = Path(__file__).with_name("sources.json")
DEFAULT_GROUP = "\u5f71\u89c6"
DEFAULT_NAME_PREFIX = "\U0001f3ac"


def github_blob_to_raw(url: str) -> str:
    marker = "github.com/"
    if marker not in url or "/blob/" not in url:
        return url

    path = url.split(marker, 1)[1].split("/")
    if len(path) < 5 or path[2] != "blob":
        return url

    owner, repo, _, branch, *file_path = path
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{'/'.join(file_path)}"


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "r18"}


def is_r18(source: dict[str, Any]) -> bool:
    group = str(source.get("group", "")).strip().lower()
    return truthy(source.get("r18")) or group == "r18"


def fetch_json(url: str, timeout: int) -> dict[str, Any]:
    raw_url = github_blob_to_raw(url)
    request = urllib.request.Request(
        raw_url,
        headers={"User-Agent": "TTTTV-flutter-config-source-updater"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8-sig")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("Upstream JSON root must be an object")
    return data


def iter_upstream_sources(data: dict[str, Any]):
    api_site = data.get("api_site")
    if isinstance(api_site, dict):
        for key, value in api_site.items():
            if isinstance(value, dict):
                yield key, value
        return

    sources = data.get("sources")
    if isinstance(sources, list):
        for value in sources:
            if isinstance(value, dict):
                yield value.get("key"), value
        return

    raise ValueError("Upstream JSON must contain either 'api_site' or 'sources'")


def normalize_sources(
    data: dict[str, Any],
    *,
    group: str,
    name_prefix: str,
) -> list[dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}

    for key, source in iter_upstream_sources(data):
        key = str(key or source.get("key") or "").strip()
        api = str(source.get("api") or "").strip()
        if not key or not api or is_r18(source):
            continue

        name = str(source.get("name") or key).strip()
        if name_prefix and not name.startswith(name_prefix):
            name = f"{name_prefix}{name}"

        normalized[key] = {
            "key": key,
            "name": name,
            "api": api,
            "detail": str(source.get("detail") or "").strip(),
            "group": group,
            "r18": False,
        }

    return list(normalized.values())


def load_existing(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"sources": []}
    with path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"{path} root must be an object")
    if not isinstance(data.get("sources"), list):
        raise ValueError(f"{path} must contain a 'sources' array")
    return data


def by_key(sources: list[Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for source in sources:
        if isinstance(source, dict) and source.get("key"):
            result[str(source["key"])] = source
    return result


def print_summary(existing_sources: list[Any], new_sources: list[dict[str, Any]]) -> None:
    old = by_key(existing_sources)
    new = by_key(new_sources)

    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    updated = sorted(
        key
        for key in set(old) & set(new)
        if {
            field: old[key].get(field)
            for field in ("name", "api", "detail", "group", "r18")
        }
        != {
            field: new[key].get(field)
            for field in ("name", "api", "detail", "group", "r18")
        }
    )
    r18_removed = sum(
        1 for source in existing_sources if isinstance(source, dict) and is_r18(source)
    )

    print(f"Current sources: {len(old)}")
    print(f"New sources: {len(new)}")
    print(f"Added: {len(added)}")
    print(f"Updated: {len(updated)}")
    print(f"Removed: {len(removed)}")
    print(f"R18 entries removed: {r18_removed}")

    for label, keys in (("added", added), ("updated", updated), ("removed", removed)):
        if keys:
            print(f"{label}: {', '.join(keys)}")


def detect_newline(path: Path) -> str:
    if not path.exists():
        return "\n"
    data = path.read_bytes()
    return "\r\n" if b"\r\n" in data else "\n"


def write_json(path: Path, data: dict[str, Any]) -> None:
    newline = detect_newline(path)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline=newline,
        dir=path.parent,
        delete=False,
    ) as file:
        file.write(text)
        temp_name = file.name

    Path(temp_name).replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync sources.json from LunaTV-config jin18.json and remove R18 sources."
    )
    parser.add_argument("--url", default=DEFAULT_SOURCE_URL, help="Upstream JSON URL")
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET,
        help="Path to sources.json",
    )
    parser.add_argument("--group", default=DEFAULT_GROUP, help="Group for normal sources")
    parser.add_argument(
        "--name-prefix",
        default=DEFAULT_NAME_PREFIX,
        help="Prefix added to source display names; pass an empty string to disable",
    )
    parser.add_argument("--timeout", type=int, default=30, help="Network timeout seconds")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the comparison summary without writing sources.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target = args.target.resolve()

    existing = load_existing(target)
    upstream = fetch_json(args.url, args.timeout)
    new_sources = normalize_sources(
        upstream,
        group=args.group,
        name_prefix=args.name_prefix,
    )

    print_summary(existing["sources"], new_sources)

    if args.dry_run:
        print("Dry run only; sources.json was not changed.")
        return 0

    updated = dict(existing)
    updated["sources"] = new_sources
    write_json(target, updated)
    print(f"Updated {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
