"""ommm [--summary] [--headstage 2] [FILE]: print Commander's readings for headstage 1 (or 2) of the one 700B as JSON,
or as a few readable lines with --summary; with FILE, print that saved snapshot as saved, with no Commander.
ommm --examples DIR copies ommm's examples into a new folder DIR, with no Commander."""

import argparse
import json
import shutil
import sys

import ommm
from ommm.summary import summary


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # the box has ♡ and Ω, which a cp1252 stdout (Windows, to a file or pipe) lacks
    parser = argparse.ArgumentParser(prog="ommm", description=__doc__.partition(": ")[2])
    parser.add_argument("file", nargs="?", metavar="FILE", help="a saved snapshot (`ommm > snapshot.json`) to print instead")
    parser.add_argument("--summary", action="store_true", help="a readable box instead of the JSON snapshot")
    parser.add_argument("--headstage", type=int, choices=(1, 2), default=1, help="the headstage to read, 1 by default")
    parser.add_argument("--examples", metavar="DIR", help="copy ommm's examples (ommm.EXAMPLES) into a new folder DIR, and stop")
    args = parser.parse_args()
    if args.examples:
        try:
            shutil.copytree(ommm.EXAMPLES, args.examples, ignore=shutil.ignore_patterns("__pycache__"))
        except OSError as error:  # DIR exists already, or cannot be made
            sys.exit(f"ommm: {error}")
        print(f"ommm's examples are in {args.examples}")
        return
    if args.file:
        try:
            snapshot = ommm.load_snapshot(args.file)
        except (OSError, ValueError) as error:  # no such file, not JSON, or not a snapshot
            sys.exit(f"ommm: {error}")
    else:
        try:
            with ommm.Amplifier(headstage=args.headstage) as amp:
                snapshot = amp.snapshot()
        except (ommm.CommanderError, ValueError) as error:  # no Commander or amplifier, or a log folder it cannot use
            sys.exit(f"ommm: {error}")
    print(summary(snapshot) if args.summary else json.dumps(snapshot, indent=2))


if __name__ == "__main__":
    main()
