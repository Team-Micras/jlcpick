"""Command-line entry point."""

import argparse
import json
import logging
import re
import sys
from dataclasses import asdict
from pathlib import Path

from jlcpick import __version__, board, bom, bom_input, swaps
from jlcpick.bom_input import BomError
from jlcpick.sources import easyeda, http, jlc
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
    cost = commands.add_parser("bom", help="price a KiCad BOM for JLCPCB assembly")
    cost.add_argument("bom", type=Path, help="CSV from kicad-cli sch export bom, or LCSC codes")
    cost.add_argument("--pcb", type=Path, help="the .kicad_pcb, for joints, sides and THT")
    cost.add_argument("--qty", type=_positive, default=5, help="boards to assemble (5)")
    cost.add_argument("--assembly", choices=["economic", "standard"], default="economic")
    cost.add_argument("--exclude", type=_designators, action="extend", default=[], metavar="U1,U3")
    cost.add_argument("--json", action="store_true", help="print JSON")
    cost.add_argument("--verbose", action="store_true", help="list every part a swap skipped")
    cost.add_argument("--no-swaps", action="store_true", help="skip the search for safe swaps")
    cost.add_argument(
        "--fail-on-extended",
        action="store_true",
        help="exit 3 when an extended part pays the feeder fee",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.ERROR, format="jlcpick: %(message)s")
    try:
        if args.command == "get":
            _get(args.codes, args.json, args.out)
        else:
            _bom(args)
    except (SourceError, BomError, OSError) as error:
        sys.exit(f"jlcpick: {error}")


def _lcsc(text: str) -> str:
    code = text.upper()
    if not re.fullmatch(r"C\d+", code):
        raise argparse.ArgumentTypeError(f"{text!r} is not an LCSC code like C25744")
    return code


def _positive(text: str) -> int:
    if not text.isdigit() or int(text) == 0:
        raise argparse.ArgumentTypeError(f"{text!r} is not a positive whole number")
    return int(text)


def _designators(text: str) -> list[str]:
    return re.findall(r"[^,\s]+", text)


def _bom(args: argparse.Namespace) -> None:
    lines = bom_input.assembled(bom_input.read(_text(args.bom)), set(args.exclude))
    footprints = None if args.pcb is None else board.footprints(_text(args.pcb))
    codes = bom.codes(lines)
    if len(codes) > 1:
        seconds = len(codes) * http.pause("jlcpcb.com")
        print(f"jlcpick: looking up {len(codes)} parts, about {seconds:.0f} s", file=sys.stderr)
    parts = {code: jlc.part(code) for code in codes}
    suggestions = None if args.no_swaps else _suggestions(parts)
    name = (args.pcb or args.bom).stem
    report = bom.report(name, lines, parts, args.qty, args.assembly, footprints, suggestions)
    for warning in report.warnings:
        print(f"jlcpick: {warning}", file=sys.stderr)
    if args.json:
        print(json.dumps(asdict(report), indent=2, ensure_ascii=False))
    else:
        print(bom.text(report, verbose=args.verbose))
    paying = [line.lcsc for line in report.lines if line.feeder_fee and line.tier != "basic"]
    if args.fail_on_extended and paying:
        print(
            f"jlcpick: extended parts paying the feeder fee: {', '.join(paying)}", file=sys.stderr
        )
        sys.exit(3)


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise BomError(f"{path}: not UTF-8 text; save it as UTF-8 and try again") from error


def _suggestions(parts: dict[str, jlc.Part]) -> dict[str, swaps.Suggestion]:
    extended = [p for p in parts.values() if p.tier == "extended" and not p.preferred]
    if extended:
        seconds = 2 * len(extended) * http.pause("jlcpcb.com")
        print(
            f"jlcpick: looking for swaps of {len(extended)} extended parts, up to {seconds:.0f} s",
            file=sys.stderr,
        )
    return {code: swaps.suggest(part, jlc.basic_or_preferred) for code, part in parts.items()}


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
