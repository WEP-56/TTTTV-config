#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.client import HTTPException, IncompleteRead, RemoteDisconnected
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = ROOT / "sources.json"
DEFAULT_GROUP = "影视"
DEFAULT_NAME_PREFIX = "\U0001f3ac"
DEFAULT_TIMEOUT = 12
DEFAULT_MAX_AGE_DAYS = 45

API_PATTERN = re.compile(r"api\.php/provide/vod(?:$|[?#])", re.I)
ADULT_PATTERN = re.compile(
    "|".join(
        re.escape(item)
        for item in (
            "🔞",
            "🔒",
            "91md",
            "155",
            "naixx",
            "bwzy",
            "apidanaizi",
            "apilj",
            "apilsb",
            "apiyutu",
            "didizy",
            "fhapi",
            "heiliao",
            "hsck",
            "jkun",
            "lbapi",
            "lbapiby",
            "shayu",
            "slapi",
            "souav",
            "thzy",
            "jingpinx",
            "yytv",
            "xiaojizy",
            "kxgav",
            "pgxdy",
            "msnii",
            "xxibao",
            "siwa",
            "semao",
            "xiangjiao",
            "xingba",
            "dadizy",
            "xrbsp",
            "aosika",
            "aosikazy",
            "ckzy",
            "douapi",
            "doudou",
            "adult",
            "sex",
            "伦理",
            "福利",
            "成人",
            "写真",
            "番号",
            "国产自拍",
        )
    ),
    re.I,
)


@dataclass(frozen=True)
class Source:
    key: str
    name: str
    api: str
    detail: str = ""
    group: str = DEFAULT_GROUP
    r18: bool = False

    def as_json(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "api": self.api,
            "detail": self.detail,
            "group": self.group,
            "r18": self.r18,
        }


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    reason: str
    class_count: int = 0
    item_count: int = 0
    latest_time: datetime | None = None
    search_status: str = "-"


def github_blob_to_raw(url: str) -> str:
    marker = "github.com/"
    if marker not in url or "/blob/" not in url:
        return url

    path = url.split(marker, 1)[1].split("/")
    if len(path) < 5 or path[2] != "blob":
        return url

    owner, repo, _, branch, *file_path = path
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{'/'.join(file_path)}"


def add_query(url: str, params: dict[str, str]) -> str:
    parsed = urllib.parse.urlsplit(url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query.update(params)
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
    )


def fetch_text(url: str, timeout: int) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "TTTTV-source-sync/1.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8-sig", errors="replace")


def fetch_json(url: str, timeout: int) -> Any:
    return json.loads(fetch_text(url, timeout))


def fetch_json_retry(url: str, timeout: int, retries: int, retry_delay: float) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return fetch_json(url, timeout)
        except (
            json.JSONDecodeError,
            urllib.error.URLError,
            TimeoutError,
            IncompleteRead,
            RemoteDisconnected,
            HTTPException,
        ) as error:
            last_error = error
            if attempt < retries:
                import time

                time.sleep(retry_delay)
    if last_error:
        raise last_error
    raise RuntimeError("request failed")


def load_upstream(url: str, timeout: int) -> dict[str, Any]:
    data = fetch_json(github_blob_to_raw(url), timeout)
    if not isinstance(data, dict):
        raise ValueError("upstream JSON root must be an object")
    return data


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "r18"}


def is_r18(source: dict[str, Any]) -> bool:
    group = str(source.get("group", "")).strip().lower()
    blob = " ".join(
        str(source.get(field) or "")
        for field in ("key", "name", "api", "detail", "group")
    )
    return truthy(source.get("r18")) or group == "r18" or bool(ADULT_PATTERN.search(blob))


def iter_upstream_sources(data: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any]]]:
    api_site = data.get("api_site")
    if isinstance(api_site, dict):
        for key, value in api_site.items():
            if isinstance(value, dict):
                yield str(key), value

    sources = data.get("sources")
    if isinstance(sources, list):
        for value in sources:
            if isinstance(value, dict):
                yield str(value.get("key") or ""), value


def normalize_source(
    key: str,
    source: dict[str, Any],
    *,
    group: str,
    name_prefix: str,
    include_r18: bool,
) -> Source | None:
    key = str(key or source.get("key") or "").strip()
    api = str(source.get("api") or "").strip()
    if not key or not api or not API_PATTERN.search(api):
        return None
    if not include_r18 and is_r18({**source, "key": key}):
        return None

    name = str(source.get("name") or key).strip()
    if name_prefix and not name.startswith(name_prefix):
        name = f"{name_prefix}{name}"

    return Source(
        key=key,
        name=name,
        api=api,
        detail=str(source.get("detail") or "").strip(),
        group=group,
        r18=False if not include_r18 else is_r18({**source, "key": key}),
    )


def normalize_upstream_sources(
    data: dict[str, Any],
    *,
    group: str = DEFAULT_GROUP,
    name_prefix: str = DEFAULT_NAME_PREFIX,
    include_r18: bool = False,
) -> list[Source]:
    seen: dict[str, Source] = {}
    for key, value in iter_upstream_sources(data):
        source = normalize_source(
            key,
            value,
            group=group,
            name_prefix=name_prefix,
            include_r18=include_r18,
        )
        if source:
            seen[source.api] = source
    return list(seen.values())


def load_sources(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"sources": []}
    with path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        raise ValueError(f"{path} must contain a sources array")
    return data


def detect_newline(path: Path) -> str:
    if not path.exists():
        return "\n"
    data = path.read_bytes()
    return "\r\n" if b"\r\n" in data else "\n"


def write_sources(path: Path, data: dict[str, Any]) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline=detect_newline(path),
        dir=path.parent,
        delete=False,
    ) as file:
        file.write(text)
        temp_name = file.name
    Path(temp_name).replace(path)


def parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and value > 0:
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    if isinstance(value, (int, float)):
        return None

    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return parse_time(int(text))

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(text[: len(fmt)], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (TypeError, ValueError):
        return None


def list_from_response(data: Any) -> list[Any]:
    if not isinstance(data, dict):
        return []
    for key in ("class", "type", "list"):
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return list(value.values())
    return []


def latest_video_time(items: list[Any]) -> datetime | None:
    latest: datetime | None = None
    for item in items:
        if not isinstance(item, dict):
            continue
        for field in ("vod_time", "vod_time_add", "vod_time_hits", "time", "updated_at"):
            parsed = parse_time(item.get(field))
            if parsed and (latest is None or parsed > latest):
                latest = parsed
    return latest


def check_source(
    source: Source,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    retries: int = 1,
    retry_delay: float = 0.5,
    search_keyword: str = "",
) -> CheckResult:
    try:
        class_data = fetch_json_retry(
            add_query(source.api, {"ac": "list"}), timeout, retries, retry_delay
        )
        classes = list_from_response(class_data)
        if not classes:
            return CheckResult(False, "no categories")

        video_items: list[Any] = []
        last_error = "no videos"
        for ac in ("videolist", "detail"):
            try:
                video_data = fetch_json_retry(
                    add_query(source.api, {"ac": ac, "pg": "1"}), timeout, retries, retry_delay
                )
                video_items = list_from_response(video_data)
                if video_items:
                    break
                last_error = f"{ac} returned no videos"
            except (
                json.JSONDecodeError,
                urllib.error.URLError,
                TimeoutError,
                IncompleteRead,
                RemoteDisconnected,
                HTTPException,
            ) as error:
                last_error = f"{ac} failed: {error}"

        if not video_items:
            return CheckResult(False, last_error, class_count=len(classes))

        latest = latest_video_time(video_items)
        if latest is not None:
            age_seconds = (datetime.now(timezone.utc) - latest).total_seconds()
            if age_seconds > max_age_days * 86400:
                return CheckResult(
                    False,
                    f"stale latest={latest.date().isoformat()}",
                    class_count=len(classes),
                    item_count=len(video_items),
                    latest_time=latest,
                )

        search_status = "-"
        if search_keyword:
            search_status = check_search(
                source,
                search_keyword,
                timeout=timeout,
                retries=retries,
                retry_delay=retry_delay,
            )

        return CheckResult(
            True,
            "ok",
            class_count=len(classes),
            item_count=len(video_items),
            latest_time=latest,
            search_status=search_status,
        )
    except (
        json.JSONDecodeError,
        urllib.error.URLError,
        TimeoutError,
        IncompleteRead,
        RemoteDisconnected,
        HTTPException,
    ) as error:
        return CheckResult(False, str(error))


def check_search(
    source: Source,
    keyword: str,
    *,
    timeout: int,
    retries: int,
    retry_delay: float,
) -> str:
    try:
        data = fetch_json_retry(add_query(source.api, {"wd": keyword}), timeout, retries, retry_delay)
        items = list_from_response(data)
        if not items:
            return "no_result"
        encoded = json.dumps(items, ensure_ascii=False)
        return "match" if keyword in encoded else "unmatched"
    except (
        json.JSONDecodeError,
        urllib.error.URLError,
        TimeoutError,
        IncompleteRead,
        RemoteDisconnected,
        HTTPException,
    ):
        return "failed"


def merge_sources(
    current: list[Any],
    candidates: list[Source],
    *,
    refresh_existing: bool = False,
) -> tuple[list[dict[str, Any]], list[Source], list[Source]]:
    by_key: dict[str, dict[str, Any]] = {}
    by_api: dict[str, str] = {}
    for item in current:
        if not isinstance(item, dict) or not item.get("key"):
            continue
        key = str(item["key"])
        by_key[key] = dict(item)
        if item.get("api"):
            by_api[str(item["api"])] = key

    added: list[Source] = []
    refreshed: list[Source] = []
    for source in candidates:
        existing_key = by_api.get(source.api)
        if existing_key:
            if refresh_existing:
                by_key[existing_key].update(source.as_json())
                refreshed.append(source)
            continue

        if source.key in by_key:
            if refresh_existing:
                by_key[source.key].update(source.as_json())
                refreshed.append(source)
            continue

        by_key[source.key] = source.as_json()
        by_api[source.api] = source.key
        added.append(source)

    return list(by_key.values()), added, refreshed


def sync_upstream(
    *,
    label: str,
    url: str,
    target: Path,
    dry_run: bool,
    verify: bool,
    include_r18: bool,
    group: str,
    name_prefix: str,
    timeout: int,
    max_age_days: int,
    retries: int,
    retry_delay: float,
    refresh_existing: bool,
) -> int:
    print(f"[{label}] fetching {github_blob_to_raw(url)}")
    data = load_upstream(url, timeout)
    candidates = normalize_upstream_sources(
        data,
        group=group,
        name_prefix=name_prefix,
        include_r18=include_r18,
    )

    current_data = load_sources(target)
    current = current_data["sources"]
    current_apis = {str(item.get("api")) for item in current if isinstance(item, dict)}
    current_keys = {str(item.get("key")) for item in current if isinstance(item, dict)}
    new_candidates = [
        source
        for source in candidates
        if source.api not in current_apis and source.key not in current_keys
    ]

    accepted: list[Source] = []
    rejected: list[tuple[Source, CheckResult]] = []
    for source in new_candidates:
        if not verify:
            accepted.append(source)
            continue
        result = check_source(
            source,
            timeout=timeout,
            max_age_days=max_age_days,
            retries=retries,
            retry_delay=retry_delay,
        )
        if result.ok:
            accepted.append(source)
            latest = result.latest_time.date().isoformat() if result.latest_time else "unknown"
            print(
                f"  OK   {source.key} classes={result.class_count} "
                f"items={result.item_count} latest={latest}"
            )
        else:
            rejected.append((source, result))
            print(f"  SKIP {source.key} {result.reason}")

    merged, added, refreshed = merge_sources(
        current,
        accepted if not refresh_existing else candidates,
        refresh_existing=refresh_existing,
    )

    print(f"[{label}] upstream candidates: {len(candidates)}")
    print(f"[{label}] new candidates: {len(new_candidates)}")
    print(f"[{label}] accepted: {len(accepted)}")
    print(f"[{label}] rejected: {len(rejected)}")
    print(f"[{label}] added: {len(added)}")
    print(f"[{label}] refreshed: {len(refreshed)}")

    if dry_run:
        print(f"[{label}] dry run; {target} was not changed")
        return len(added)

    updated = dict(current_data)
    updated["sources"] = merged
    write_sources(target, updated)
    print(f"[{label}] updated {target}")
    return len(added)


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-verify", action="store_true")
    parser.add_argument("--include-r18", action="store_true")
    parser.add_argument("--refresh-existing", action="store_true")
    parser.add_argument("--group", default=DEFAULT_GROUP)
    parser.add_argument("--name-prefix", default=DEFAULT_NAME_PREFIX)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=0.5)
