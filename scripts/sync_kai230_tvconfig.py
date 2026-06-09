#!/usr/bin/env python3
from __future__ import annotations

import argparse

from source_sync import add_common_args, sync_upstream


URL = "https://gist.githubusercontent.com/kai230/f006ed45efba3a21d244c76a480e81ed/raw/tvconfig.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge verified normal sources from kai230 tvconfig gist."
    )
    add_common_args(parser)
    args = parser.parse_args()

    sync_upstream(
        label="kai230-tvconfig",
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
