#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from source_sync import DEFAULT_MAX_AGE_DAYS, DEFAULT_TARGET, DEFAULT_TIMEOUT, Source, check_source, load_sources


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify sources.json availability and recency.")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    args = parser.parse_args()

    data = load_sources(args.target)
    failed = 0
    for item in data["sources"]:
        if not isinstance(item, dict):
            continue
        source = Source(
            key=str(item.get("key") or ""),
            name=str(item.get("name") or ""),
            api=str(item.get("api") or ""),
            detail=str(item.get("detail") or ""),
            group=str(item.get("group") or ""),
            r18=bool(item.get("r18")),
        )
        result = check_source(source, timeout=args.timeout, max_age_days=args.max_age_days)
        if result.ok:
            latest = result.latest_time.date().isoformat() if result.latest_time else "unknown"
            print(
                f"OK   {source.key} classes={result.class_count} "
                f"items={result.item_count} latest={latest}"
            )
        else:
            failed += 1
            print(f"FAIL {source.key} {result.reason}")

    print(f"checked={len(data['sources'])} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
