"""Print and log every change MultiClamp Commander reports, to check reads against changes made by hand.

Read-only. Takes a snapshot of the tab Commander shows every 0.5 s, leaving a tab clicked in its window alone, and prints the readings and telegraph fields that changed
(meters left out) plus any disagreement between the API and the telegraph. Each change is appended
as one JSON line to watch_<time>.jsonl in --log-dir (default ~/ommm-logs).

    uv run python scripts/watch.py                 (until Ctrl+C)
    uv run python scripts/watch.py --seconds 600
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from ommm.commander import Commander, CommanderError, changes


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seconds", type=float, default=float("inf"))
    parser.add_argument("--log-dir", type=Path, default=Path.home() / "ommm-logs")
    args = parser.parse_args()

    log_path = args.log_dir / f"watch_{datetime.now():%Y%m%dT%H%M%S}.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"watching; log: {log_path}", flush=True)
    stop = time.monotonic() + args.seconds
    try:
        commander = Commander()
    except CommanderError as error:
        sys.exit(f"watch: {error}")
    with commander, log_path.open("a") as log:
        previous = commander.snapshot(show_active_tab=False)
        log.write(json.dumps({"time": previous["time"], "start": previous}) + "\n")
        while time.monotonic() < stop:
            time.sleep(0.5)
            snapshot = commander.snapshot(show_active_tab=False)
            changed = changes(previous, snapshot)
            disagreements = snapshot["disagreements"]
            if changed or disagreements != previous["disagreements"] or snapshot["errors"]:
                event = {"time": snapshot["time"], "changed": changed, "disagreements": disagreements, "errors": snapshot["errors"]}
                log.write(json.dumps(event) + "\n")
                log.flush()
                print(snapshot["time"][11:19], json.dumps(changed), flush=True)
                for line in disagreements + list(snapshot["errors"].values()):
                    print("   !!", line, flush=True)
            previous = snapshot


if __name__ == "__main__":
    main()
