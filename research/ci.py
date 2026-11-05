"""Run a script's main() and surface any crash as a GitHub Actions error annotation
(readable from the API without logs access)."""
import os
import sys
import traceback


def run(main) -> None:
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        if os.getenv("GITHUB_ACTIONS"):
            last = " | ".join(tb.strip().splitlines()[-4:]).replace("%", "%25")
            print(f"::error::{type(e).__name__}: {last}")
        sys.exit(1)
