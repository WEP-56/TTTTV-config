#!/usr/bin/env python3
from __future__ import annotations

import argparse

from source_sync import add_common_args, sync_upstream


URL = "https://github.com/hafrey1/LunaTV-config/blob/main/LunaTV-config.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge verified normal sources from LunaTV-config full config."
    )
    add_common_args(parser)
    args = parser.parse_args()

    sync_upstream(
        label="lunatv-full",
        url=URL,
        target=args.target,
        dry_run=args.dry_run,
        verify=not args.no_verify,
        include_r18=args.include_r18,
        group=args.group,
        name_prefix=args.name_prefix,
        timeout=args.timeout,
        max_age_days=args.max_age_days,
        retries=args.retries,
        retry_delay=args.retry_delay,
        refresh_existing=args.refresh_existing,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
