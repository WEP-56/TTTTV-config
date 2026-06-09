#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

from source_sync import (
    DEFAULT_MAX_AGE_DAYS,
    DEFAULT_TARGET,
    DEFAULT_TIMEOUT,
    Source,
    check_source,
    load_sources,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = ROOT / "reports" / "source-health.md"
DEFAULT_HISTORY = ROOT / "reports" / "source-health-history.json"
DEFAULT_JSON = ROOT / "reports" / "source-health-latest.json"


@dataclass(frozen=True)
class CheckRow:
    key: str
    name: str
    api: str
    detail: str
    ok: bool
    reason: str
    class_count: int
    item_count: int
    latest: str
    search_status: str


def source_from_item(item: dict) -> Source:
    return Source(
        key=str(item.get("key") or ""),
        name=str(item.get("name") or ""),
        api=str(item.get("api") or ""),
        detail=str(item.get("detail") or ""),
        group=str(item.get("group") or ""),
        r18=bool(item.get("r18")),
    )


def load_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def build_stats(rows: list[CheckRow], history: list[dict], warn_streak: int) -> list[dict]:
    stats = []
    for row in rows:
        records = []
        for day in history:
            for item in day.get("results", []):
                if item.get("key") == row.key or item.get("api") == row.api:
                    records.append(item)
                    break

        ok_count = sum(1 for item in records if item.get("ok"))
        fail_count = sum(1 for item in records if not item.get("ok"))
        streak = 0
        for item in reversed(records):
            if item.get("ok"):
                break
            streak += 1
        trend = "".join("Y" if item.get("ok") else "N" for item in records[-7:])
        total = ok_count + fail_count
        success_rate = f"{ok_count / total * 100:.1f}%" if total else "-"
        status = "OK" if row.ok else "FAIL"
        if streak >= warn_streak:
            status = "WARN"

        stats.append(
            {
                **asdict(row),
                "ok_count": ok_count,
                "fail_count": fail_count,
                "fail_streak": streak,
                "success_rate": success_rate,
                "trend": trend,
                "status": status,
            }
        )
    return sorted(stats, key=lambda item: (item["ok"], -item["fail_streak"], item["key"]))


def write_report(
    path: Path,
    *,
    checked_at: str,
    keyword: str,
    stats: list[dict],
    max_age_days: int,
) -> None:
    ok_count = sum(1 for item in stats if item["ok"])
    fail_count = len(stats) - ok_count
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Source Health Report",
        "",
        f"Updated: {checked_at}",
        f"Sources: {len(stats)} | OK: {ok_count} | Failed: {fail_count} | Max age: {max_age_days} days | Search: {keyword or '-'}",
        "",
        "| Status | Key | Name | API | Classes | Items | Latest | Search | Success | Streak | 7-run Trend | Reason |",
        "|---|---|---|---|---:|---:|---|---|---:|---:|---|---|",
    ]
    for item in stats:
        lines.append(
            "| {status} | {key} | {name} | [api]({api}) | {class_count} | {item_count} | "
            "{latest} | {search_status} | {success_rate} | {fail_streak} | {trend} | {reason} |".format(
                status=item["status"],
                key=escape_cell(item["key"]),
                name=escape_cell(item["name"]),
                api=escape_cell(item["api"]),
                class_count=item["class_count"],
                item_count=item["item_count"],
                latest=item["latest"],
                search_status=item["search_status"],
                success_rate=item["success_rate"],
                fail_streak=item["fail_streak"],
                trend=item["trend"] or "-",
                reason=escape_cell(item["reason"]),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check source availability, recency, search behavior, and write reports."
    )
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=0.5)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--history-days", type=int, default=30)
    parser.add_argument("--warn-streak", type=int, default=3)
    parser.add_argument("--search-keyword", default="\u6597\u7f57\u5927\u9646")
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args()

    data = load_sources(args.target)
    sources = [
        source_from_item(item)
        for item in data["sources"]
        if isinstance(item, dict) and item.get("key") and item.get("api")
    ]

    def run(source: Source) -> CheckRow:
        result = check_source(
            source,
            timeout=args.timeout,
            max_age_days=args.max_age_days,
            retries=args.retries,
            retry_delay=args.retry_delay,
            search_keyword=args.search_keyword,
        )
        latest = result.latest_time.date().isoformat() if result.latest_time else "unknown"
        status = "OK" if result.ok else "FAIL"
        print(
            f"{status:<4} {source.key} classes={result.class_count} "
            f"items={result.item_count} latest={latest} search={result.search_status} {result.reason}"
        )
        return CheckRow(
            key=source.key,
            name=source.name,
            api=source.api,
            detail=source.detail,
            ok=result.ok,
            reason=result.reason,
            class_count=result.class_count,
            item_count=result.item_count,
            latest=latest,
            search_status=result.search_status,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        rows = list(pool.map(run, sources))

    checked_at = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M CST")
    history = load_history(args.history)
    history.append(
        {
            "date": datetime.now(timezone.utc).date().isoformat(),
            "checked_at": checked_at,
            "keyword": args.search_keyword,
            "results": [asdict(row) for row in rows],
        }
    )
    history = history[-max(1, args.history_days) :]
    stats = build_stats(rows, history, args.warn_streak)

    save_json(args.history, history)
    save_json(
        args.json_output,
        {
            "checked_at": checked_at,
            "keyword": args.search_keyword,
            "source_count": len(rows),
            "ok_count": sum(1 for row in rows if row.ok),
            "failed_count": sum(1 for row in rows if not row.ok),
            "results": stats,
        },
    )
    write_report(
        args.report,
        checked_at=checked_at,
        keyword=args.search_keyword,
        stats=stats,
        max_age_days=args.max_age_days,
    )

    failed = sum(1 for row in rows if not row.ok)
    print(f"checked={len(rows)} failed={failed} report={args.report}")
    return 0 if args.allow_failures or failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
