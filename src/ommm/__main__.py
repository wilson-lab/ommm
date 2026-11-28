"""ommm [--summary] [--headstage 2] [FILE] [--out NEW]: print Commander's readings for headstage 1 (or 2) of the one
700B as JSON, or as a few readable lines with --summary; with FILE, print that saved snapshot as saved, with no
Commander; with --out, write them as UTF-8 to NEW, a file that is not there yet, instead of printing them.
ommm --examples DIR copies ommm's examples into a new folder DIR, with no Commander."""

import argparse
import json
import shutil
import sys
from pathlib import Path

import ommm
from ommm.summary import summary


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # the box has ♡ and Ω, which a cp1252 stdout (Windows, to a file or pipe) lacks
    parser = argparse.ArgumentParser(prog="ommm", description=__doc__.partition(": ")[2])
    parser.add_argument("file", nargs="?", metavar="FILE", help="a saved snapshot (`ommm --out snapshot.json`) to print instead")
    parser.add_argument("--summary", action="store_true", help="a readable box instead of the JSON snapshot")
    parser.add_argument("--headstage", type=int, choices=(1, 2), default=1, help="the headstage to read, 1 by default")
    parser.add_argument("--out", metavar="NEW", help="write to a new file NEW, as UTF-8, instead of printing; "
                        "Windows PowerShell's `>` writes UTF-16")
    parser.add_argument("--examples", metavar="DIR", help="copy ommm's examples (ommm.EXAMPLES) into a new folder DIR, and stop")
    args = parser.parse_args()
    if args.examples:
        try:
            shutil.copytree(ommm.EXAMPLES, args.examples, ignore=shutil.ignore_patterns("__pycache__"))
        except OSError as error:  # DIR exists already, or cannot be made
            sys.exit(f"ommm: {error}")
        print(f"ommm's examples are in {args.examples}")
        return
    if args.out and Path(args.out).exists():  # before Commander is read, so a name in use costs no read
        sys.exit(f"ommm: {args.out} exists: --out writes only a new file")
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
    text = summary(snapshot) if args.summary else json.dumps(snapshot, indent=2)
    if not args.out:
        print(text)
        return
    try:
        with open(args.out, "x", encoding="utf-8") as out:
            print(text, file=out)
    except OSError as error:  # made since the check, or in a folder that is not there
        sys.exit(f"ommm: {error}")


if __name__ == "__main__":
    main()
