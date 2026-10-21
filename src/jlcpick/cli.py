"""Command-line entry point."""

import argparse
import glob
import json
import logging
import os
import re
import sys
from dataclasses import asdict
from pathlib import Path

from jlcpick import __version__, board, bom, bom_input, library, swaps
from jlcpick.bom_input import BomError
from jlcpick.sources import easyeda, http, jlc
from jlcpick.sources.http import SourceError

KICAD_SHARES = (
    "/usr/share/kicad",
    "/usr/local/share/kicad",
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport",
    "C:/Program Files/KiCad/10.0/share/kicad",
    "~/.local/share/flatpak/runtime/org.kicad.KiCad.Library.*/*/stable/active/files",
    "/var/lib/flatpak/runtime/org.kicad.KiCad.Library.*/*/stable/active/files",
)


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
    add = commands.add_parser("add", help="add parts to the project's symbol library")
    add.add_argument("codes", nargs="+", type=_lcsc, metavar="LCSC", help="e.g. C25744")
    add.add_argument(
        "--lib", type=Path, default=Path("lib"), metavar="DIR", help="library folder (lib)"
    )
    add.add_argument("--force", action="store_true", help="replace a symbol of the same name")
    add.add_argument("--json", action="store_true", help="print JSON")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.ERROR, format="jlcpick: %(message)s")
    try:
        if args.command == "get":
            _get(args.codes, args.json, args.out)
        elif args.command == "add":
            _add(args.codes, args.lib, args.force, args.json)
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


def _add(codes: list[str], lib: Path, force: bool, as_json: bool) -> None:
    projects = sorted(Path().glob("*.kicad_pro"))
    if len(projects) != 1:
        sys.exit("jlcpick: run add in the KiCad project's folder, next to its one .kicad_pro")
    name = projects[0].stem
    symbol_dir = _kicad_dir("KICAD10_SYMBOL_DIR", "symbols")
    footprint_dir = _kicad_dir("KICAD10_FOOTPRINT_DIR", "footprints")
    parts = [jlc.part(code) for code in dict.fromkeys(codes)]
    found = [(part, library.stock(part)) for part in parts]
    stocked = [(part, stock) for part, stock in found if stock is not None]
    if len(stocked) < len(found):
        unknown = ", ".join(f"{p.lcsc} ({p.package}, {p.category})" for p, s in found if s is None)
        sys.exit(
            f"jlcpick: packages.toml has no KiCad footprint for {unknown}; converting EasyEDA's "
            "is not done yet, `jlcpick get CODE --out DIR` saves a draft footprint to review"
        )
    kicad = {
        nickname: library.symbols(_text(symbol_dir / f"{nickname}.kicad_sym"))
        for nickname in {stock.symbol.partition(":")[0] for _, stock in stocked}
    }
    path = lib / f"{name}.kicad_sym"
    old = _text(path) if path.exists() else library.EMPTY_LIBRARY
    present = library.symbols(old)
    outcomes, changed = [], []
    for part, stock in stocked:
        entry = _entry(part, stock, kicad, footprint_dir)
        status = _status(present.get(entry.name), entry, force)
        outcomes.append(library.Outcome(part.lcsc, entry.name, stock.footprint, status))
        if status in ("added", "replaced"):
            changed.append(entry)
        if status == "kept":
            print(
                f'jlcpick: {part.lcsc}: {path} already has a different "{entry.name}", kept; '
                "--force replaces it",
                file=sys.stderr,
            )
    _write_if_changed(path, old, library.merge_symbols(old, changed))
    uri = path.as_posix() if path.is_absolute() else f"${{KIPRJMOD}}/{path.as_posix()}"
    table = Path("sym-lib-table")
    old_table = _text(table) if table.exists() else library.EMPTY_TABLE
    _write_if_changed(table, old_table, library.register(old_table, name, uri))
    if as_json:
        print(json.dumps([asdict(o) for o in outcomes], indent=2, ensure_ascii=False))
    else:
        print("\n".join(f"{o.lcsc:<10} {o.status:<9} {o.symbol} · {o.footprint}" for o in outcomes))


def _entry(
    part: jlc.Part, stock: library.Stock, kicad: dict[str, dict[str, str]], footprint_dir: Path
) -> library.Entry:
    nickname, _, symbol = stock.symbol.partition(":")
    base = kicad[nickname][symbol]
    footprint_nickname, _, footprint = stock.footprint.partition(":")
    pads = _text(footprint_dir / f"{footprint_nickname}.pretty" / f"{footprint}.kicad_mod")
    if pins := library.missing_pads(base, pads):
        sys.exit(
            f"jlcpick: {stock.footprint} has no pad for pin {', '.join(pins)} of {stock.symbol}; "
            "fix packages.toml"
        )
    return library.entry(part, stock, base)


def _kicad_dir(variable: str, kind: str) -> Path:
    if variable in os.environ:
        return Path(os.environ[variable])
    found = [p for share in KICAD_SHARES for p in glob.glob(os.path.expanduser(f"{share}/{kind}"))]
    if not found:
        sys.exit(f"jlcpick: KiCad 10's {kind} not found; install KiCad 10 or set {variable}")
    return Path(found[0])


def _status(present: str | None, entry: library.Entry, force: bool) -> library.Status:
    if present is None:
        return "added"
    if present == entry.symbol:
        return "unchanged"
    return "replaced" if force else "kept"


def _write_if_changed(path: Path, old: str, new: str) -> None:
    if new != old:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new, encoding="utf-8")


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
