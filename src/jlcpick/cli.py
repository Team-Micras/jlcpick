"""Command-line entry point."""

import argparse
import json
import logging
import re
import sys
from dataclasses import asdict
from pathlib import Path

from jlcpick import __version__
from jlcpick.sources import easyeda, jlc
from jlcpick.sources.http import SourceError


def main(argv: list[str] | None = None) -> None:
    """Parse arguments and run the requested command."""
    parser = argparse.ArgumentParser(prog="jlcpick")
    parser.add_argument("--version", action="version", version=f"jlcpick {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    get = commands.add_parser("get", help="show a part's tier, stock and prices")
    get.add_argument("codes", nargs="+", type=_lcsc, metavar="LCSC", help="e.g. C25744")
    get.add_argument("--json", action="store_true", help="print JSON")
    get.add_argument("--out", type=Path, metavar="DIR", help="also save footprint and STEP")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.ERROR, format="jlcpick: %(message)s")
    try:
        _get(args.codes, args.json, args.out)
    except SourceError as error:
        sys.exit(f"jlcpick: {error}")


def _lcsc(text: str) -> str:
    code = text.upper()
    if not re.fullmatch(r"C\d+", code):
        raise argparse.ArgumentTypeError(f"{text!r} is not an LCSC code like C25744")
    return code


def _get(codes: list[str], as_json: bool, out: Path | None) -> None:
    parts = [jlc.part(code) for code in codes]
    if as_json:
        print(json.dumps([asdict(part) for part in parts], indent=2, ensure_ascii=False))
    else:
        print("\n\n".join(map(_describe, parts)))
    if out is not None:
        for code in codes:
            _save_cad(code, out)


def _save_cad(code: str, out: Path) -> None:
    raw = easyeda.cad(code)
    if raw is None:
        print(f"jlcpick: {code}: EasyEDA has no CAD data, no footprint or STEP", file=sys.stderr)
        return
    out.mkdir(parents=True, exist_ok=True)
    step = out.resolve() / f"{code}.step"
    (out / f"{code}.kicad_mod").write_text(easyeda.footprint(raw, step), encoding="utf-8")
    if raw.step is None:
        print(f"jlcpick: {code}: EasyEDA has no STEP model", file=sys.stderr)
    else:
        step.write_bytes(raw.step)


def _describe(part: jlc.Part) -> str:
    tier = f"{part.tier}, preferred" if part.preferred else part.tier
    minimum = "none, basic is billed by use"
    if part.tier == "extended":
        minimum = f"{part.min_qty} (+{part.loss_qty} attrition)"
    prices = " · ".join(f"{price.from_qty}+ {price.usd:g}" for price in part.prices)
    return "\n".join(
        [
            f"{part.lcsc}  {part.mpn} · {part.manufacturer}",
            f"  tier        {tier}",
            f"  stock       {part.stock:,}",
            f"  package     {part.package} · {part.category}",
            f"  min order   {minimum}",
            f"  prices US$  {prices}",
            f"  datasheet   {part.datasheet or 'none'}",
        ]
    )
