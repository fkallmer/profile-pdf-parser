from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .parser import parse_linkedin_pdf


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parse a manually exported profile PDF and write structured JSON."
    )
    parser.add_argument("pdf", type=Path, help="Path to the profile PDF export.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output JSON file. Defaults to stdout.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation. Use 0 for compact JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    parsed = parse_linkedin_pdf(args.pdf.read_bytes())
    indent = None if args.indent == 0 else args.indent
    payload = json.dumps(parsed, ensure_ascii=False, indent=indent)

    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        sys.stdout.write(payload + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
