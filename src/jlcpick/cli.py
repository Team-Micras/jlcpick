"""Command-line entry point."""

import argparse
import glob
import json
import logging
import os
import re
import sys
from dataclasses import asdict
from pathlib import Path, PurePath

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


KICAD_10 = {
    "symbols": ("Device.kicad_sym", '(generator_version "10.0")'),
    "footprints": ("Resistor_SMD.pretty/R_0402_1005Metric.kicad_mod", "(version 2026"),
}


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
    kicad = _kicad_symbols(symbol_dir, parts)
    entries = [_entry(part, kicad, footprint_dir, lib, name) for part in parts]
    _refuse_clashes(parts, entries)
    path = lib / f"{name}.kicad_sym"
    old = _existing(path, library.EMPTY_LIBRARY)
    present = library.symbols(old)
    outcomes, changed, bases = [], [], {}
    for part, entry in zip(parts, entries, strict=True):
        _check_base(path, present, entry)
        if entry.base is not None:
            bases[entry.base] = None
        status, differ = _status(path, present.get(entry.name), entry, force)
        footprint = library.value(entry.symbol, "Footprint")
        outcomes.append(
            library.Outcome(part.lcsc, entry.name, footprint, status, bool(entry.files))
        )
        if status in ("added", "replaced"):
            changed.append(entry)
        if status == "kept":
            print(
                f"jlcpick: {part.lcsc}: {'; '.join(differ)}, kept; --force replaces it",
                file=sys.stderr,
            )
    for file, data in {f: d for entry in changed for f, d in entry.files.items()}.items():
        if _read(file) != data:
            Path(file).parent.mkdir(parents=True, exist_ok=True)
            Path(file).write_bytes(data)
    _write_if_changed(path, old, library.merge_symbols(old, changed, list(bases)))
    _register(Path("sym-lib-table"), library.EMPTY_TABLE, name, path)
    if any(outcome.draft for outcome in outcomes):
        pretty = lib / f"{name}.pretty"
        _register(Path("fp-lib-table"), library.EMPTY_FOOTPRINT_TABLE, name, pretty)
    if as_json:
        print(json.dumps([asdict(o) for o in outcomes], indent=2, ensure_ascii=False))
    else:
        print("\n".join(map(_outcome, outcomes)))


def _outcome(o: library.Outcome) -> str:
    line = f"{o.lcsc:<10} {o.status:<9} {o.symbol} · {o.footprint}"
    return f"{line}  draft: review footprint and 3D" if o.draft else line


def _register(table: Path, empty: str, name: str, path: Path) -> None:
    uri = _project_path(path)
    old = _existing(table, empty)
    registered = library.registered(old).get(name, uri)
    if registered != uri:
        print(
            f"jlcpick: {table} maps `{name}` to {registered}, but add wrote {uri}; "
            "point it at the right file",
            file=sys.stderr,
        )
    _write_if_changed(table, old, library.register(old, name, uri))


def _project_path(path: Path) -> str:
    return path.as_posix() if path.is_absolute() else f"${{KIPRJMOD}}/{path.as_posix()}"


def _kicad_symbols(symbol_dir: Path, parts: list[jlc.Part]) -> dict[str, dict[str, str]]:
    stocked = {s.symbol.partition(":")[0] for p in parts if (s := library.stock(p)) is not None}
    wanted = [f'\n\t(symbol "{p.mpn}"\n' for p in parts if library.stock(p) is None]
    paths = [symbol_dir / f"{nickname}.kicad_sym" for nickname in sorted(stocked)]
    paths += sorted(symbol_dir.glob("*.kicad_sym")) if wanted else []
    kicad = {}
    for path in dict.fromkeys(paths):
        text = _text(path)
        if path.stem in stocked or any(mpn in text for mpn in wanted):
            kicad[path.stem] = library.symbols(text)
    return kicad


def _existing(path: Path, empty: str) -> str:
    if not path.exists():
        return empty
    text = _text(path)
    try:
        library.check(text)
    except ValueError as error:
        raise BomError(f"{path}: {error}") from error
    return text


def _check_base(path: Path, present: dict[str, str], entry: library.Entry) -> None:
    if entry.base is None:
        return
    ours = present.get(entry.base_name)
    if ours is None or library.pins(ours) == library.pins(entry.base):
        return
    have, kicad = library.pins(ours), library.pins(entry.base)
    sys.exit(
        f"jlcpick: {path} already has a `{entry.base_name}` wired differently from KiCad's: "
        f"it has {[p for p in have if p not in kicad]}, KiCad's has "
        f"{[p for p in kicad if p not in have]}; restore it from KiCad's library"
    )


def _entry(
    part: jlc.Part, kicad: dict[str, dict[str, str]], footprint_dir: Path, lib: Path, name: str
) -> library.Entry:
    stock = library.stock(part) or library.by_mpn(part, kicad)
    if stock is None:
        return _converted(part, lib, name)
    nickname, _, symbol = stock.symbol.partition(":")
    source = kicad[nickname][symbol]
    base = source
    while parent := library.parent(base):
        base = kicad[nickname][parent]
    footprint_nickname, _, footprint = stock.footprint.partition(":")
    pads = _text(footprint_dir / f"{footprint_nickname}.pretty" / f"{footprint}.kicad_mod")
    if pins := library.missing_pads(base, pads):
        sys.exit(
            f"jlcpick: {stock.footprint} has no pad for pin {', '.join(pins)} of {stock.symbol}; "
            "fix packages.toml"
        )
    return library.entry(part, stock, base, source)


def _converted(part: jlc.Part, lib: Path, name: str) -> library.Entry:
    raw = easyeda.cad(part.lcsc)
    if raw is None:
        sys.exit(
            f"jlcpick: {part.lcsc} ({part.package}, {part.category}): no KiCad symbol or "
            "footprint fits it and EasyEDA has nothing to convert; draw it by hand"
        )
    footprint = library.safe_name(easyeda.package(raw))
    step = lib / f"{name}.3dshapes" / f"{footprint}.step"
    text = easyeda.footprint(raw, PurePath(_project_path(step)))
    symbol = easyeda.symbol(raw)
    if pins := library.missing_pads(symbol, text):
        sys.exit(
            f"jlcpick: {part.lcsc}: EasyEDA's footprint has no pad for pin {', '.join(pins)} of "
            "its symbol; nothing written"
        )
    files: dict[PurePath, bytes] = {
        lib / f"{name}.pretty" / f"{footprint}.kicad_mod": text.encode()
    }
    if raw.step is None:
        print(f"jlcpick: {part.lcsc}: EasyEDA has no STEP model", file=sys.stderr)
    else:
        files[step] = raw.step
    return library.converted(part, symbol, f"{name}:{footprint}", files)


def _kicad_dir(variable: str, kind: str) -> Path:
    if variable in os.environ:
        return Path(os.environ[variable])
    found = [
        Path(p) for share in KICAD_SHARES for p in glob.glob(os.path.expanduser(f"{share}/{kind}"))
    ]
    sample, mark = KICAD_10[kind]
    current = [p for p in found if mark in _head(p / sample)]
    if not current:
        other = f" (the KiCad found, {found[0].parent}, is another version)" if found else ""
        sys.exit(f"jlcpick: KiCad 10's {kind} not found{other}; install KiCad 10 or set {variable}")
    return current[0]


def _head(path: Path) -> str:
    try:
        with path.open(encoding="utf-8") as file:
            return file.read(512)
    except OSError:
        return ""


def _status(
    path: Path, present: str | None, entry: library.Entry, force: bool
) -> tuple[library.Status, list[str]]:
    old = {file: _read(file) for file in entry.files}
    differ = [
        f"{file.as_posix()} is different"
        for file in old
        if old[file] not in (None, entry.files[file])
    ]
    if present not in (None, entry.symbol):
        differ.insert(0, f'{path} already has a different "{entry.name}"')
    if differ:
        return ("replaced" if force else "kept"), differ
    return ("added" if present is None or None in old.values() else "unchanged"), []


def _refuse_clashes(parts: list[jlc.Part], entries: list[library.Entry]) -> None:
    symbols: dict[str, str] = {}
    files: dict[PurePath, tuple[str, bytes]] = {}
    for part, entry in zip(parts, entries, strict=True):
        if entry.name in symbols:
            sys.exit(
                f"jlcpick: {symbols[entry.name]} and {part.lcsc} both make the symbol "
                f'"{entry.name}"; add one of them at a time'
            )
        symbols[entry.name] = part.lcsc
        for file, data in entry.files.items():
            first, other = files.setdefault(file, (part.lcsc, data))
            if other != data:
                sys.exit(
                    f"jlcpick: {first} and {part.lcsc} both make {file.as_posix()}, differently; "
                    "add one of them at a time"
                )


def _read(path: PurePath) -> bytes | None:
    return Path(path).read_bytes() if Path(path).exists() else None


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
