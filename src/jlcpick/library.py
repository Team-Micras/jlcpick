"""A project's symbol library of parts drawn on KiCad's own symbols and footprints."""

import re
import tomllib
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

from jlcpick.sources.jlc import Part

EMPTY_LIBRARY = (
    '(kicad_symbol_lib\n\t(version 20251024)\n\t(generator "jlcpick")\n'
    '\t(generator_version "10.0")\n)\n'
)
EMPTY_TABLE = "(sym_lib_table\n\t(version 7)\n)\n"
EMPTY_FOOTPRINT_TABLE = "(fp_lib_table\n\t(version 7)\n)\n"


class Rule(TypedDict):
    """A ``packages.toml`` section: ``value`` names the JLC attribute shown as the Value."""

    kind: str
    value: NotRequired[str]
    categories: list[str]
    footprints: dict[str, list[str]]


PACKAGES: dict[str, Rule] = tomllib.loads(
    files("jlcpick").joinpath("packages.toml").read_text(encoding="utf-8")
)

_STRING = r'"(?:[^"\\]|\\.)*"'
_LEXEME = re.compile(rf"{_STRING}|[()]")
_HEAD = re.compile(rf"\((\w+)\s+({_STRING})")
_PROPERTY = re.compile(rf"\(property\s+({_STRING})\s+({_STRING})")
_EXTENDS = re.compile(rf"\(extends ({_STRING})\)")
_TABLE_LIB = re.compile(
    rf"\(lib\s+\(name ({_STRING})\)(?:\s*\((?!uri)\w+ {_STRING}\))*\s*\(uri ({_STRING})\)"
)
_PIN = re.compile(rf"\(name ({_STRING})|\(number ({_STRING})")
_NOT_IN_NAMES = re.compile(r'[\x00-\x1f:/\\<>"*?|]|[ .](?=[ .]*$)')
_WINDOWS_RESERVED = re.compile(r"(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?|\..*", re.IGNORECASE)
_PAREN = re.compile(r"\s*\([^)]*\)")


type Status = Literal["added", "unchanged", "replaced", "kept"]


@dataclass(frozen=True)
class Outcome:
    """What ``add`` did with a part: ``kept`` leaves a different symbol or file as is.

    ``draft`` parts were converted from EasyEDA: their footprint and 3D model need a review.
    """

    lcsc: str
    symbol: str
    footprint: str
    status: Status
    draft: bool


@dataclass(frozen=True)
class Stock:
    """The KiCad symbol and footprint a part gets, and the name of its own symbol."""

    symbol: str
    footprint: str
    name: str
    value: str


@dataclass(frozen=True)
class Entry:
    """A part's symbol, derived from the KiCad ``base`` symbol it ``extends`` or, without a base,
    converted from EasyEDA, with the ``files`` of its footprint and 3D model by path."""

    symbol: str
    base: str | None
    files: Mapping[Path, bytes] = field(default_factory=dict)

    @property
    def name(self) -> str:
        """The symbol's name in the library."""
        return _name(self.symbol)

    @property
    def base_name(self) -> str:
        """The base symbol's name in the library; empty without a base."""
        return "" if self.base is None else _name(self.base)


def stock(part: Part) -> Stock | None:
    """KiCad's own symbol and footprint for ``part``; None when ``packages.toml`` has none."""
    for symbol, rule in PACKAGES.items():
        if part.category not in rule["categories"]:
            continue
        footprint = next(
            (f for f, names in rule["footprints"].items() if part.package in names), None
        )
        if footprint is None:
            return None
        value = part.params.get(rule.get("value", ""), "-")
        if value == "-":
            value = part.mpn
        label = rule["kind"] if value == part.mpn else f"{rule['kind']} {value}"
        return Stock(symbol, footprint, _symbol_name(label, part), value)
    return None


def by_mpn(part: Part, kicad: Mapping[str, Mapping[str, str]]) -> Stock | None:
    """KiCad's own symbol named after ``part.mpn`` in the ``kicad`` libraries, if it names a
    footprint; None otherwise."""
    for nickname, blocks in kicad.items():
        footprint = value(blocks.get(part.mpn, ""), "Footprint")
        if footprint:
            name = _symbol_name(_kind(part), part)
            return Stock(f"{nickname}:{part.mpn}", footprint, name, part.mpn)
    return None


def entry(part: Part, stock: Stock, base: str, source: str) -> Entry:
    """The symbol of ``part``, extending ``base``, a root KiCad symbol, with the fields of
    ``source``, KiCad's ``stock.symbol`` (``base`` itself unless it extends one), set to the
    part's."""
    properties = _children(source, "property")
    blocks = _with_fields(properties, _fields(part, stock.value, stock.footprint))
    lines = [f"(symbol {_quote(stock.name)}", f"(extends {_quote(_name(base))})", *blocks]
    return Entry("\n\t\t".join([*lines, "(embedded_fonts no)"]) + "\n\t)", base)


def converted(part: Part, symbol: str, footprint: str, files: Mapping[Path, bytes]) -> Entry:
    """The symbol of ``part`` from ``symbol``, converted from EasyEDA, renamed and with the
    part's fields, its footprint ``footprint`` and its ``files``."""
    name = _symbol_name(_kind(part), part)
    spans = [(start, end) for start, end in _spans(symbol, 1) if _head(symbol, start) == "property"]
    blocks = _with_fields(_children(symbol, "property"), _fields(part, part.mpn, footprint))
    indent = symbol[symbol.rindex("\n", 0, spans[0][0]) : spans[0][0]]
    symbol = symbol[: spans[0][0]] + indent.join(blocks) + symbol[spans[-1][1] :]
    old = re.escape(_name(symbol))
    unit = re.compile(rf'(\(symbol\s+)"{old}(_\d+_\d+)?"')
    return Entry(unit.sub(lambda m: m[1] + _quote(name + (m[2] or "")), symbol), None, files)


def parent(symbol: str) -> str | None:
    """The name of the symbol ``symbol`` extends; None for a root symbol."""
    extends = _EXTENDS.search(symbol)
    return None if extends is None else extends[1][1:-1]


def value(symbol: str, name: str) -> str:
    """The value of the property ``name`` of ``symbol``; empty when it has none."""
    found = {key[1:-1]: text[1:-1] for key, text in _PROPERTY.findall(symbol)}
    return found.get(name, "")


def safe_name(text: str) -> str:
    """``text`` with the characters KiCad does not take in a symbol or footprint name as ``_``,
    and ``_`` before a name Windows reserves (``CON``, ``NUL.txt``…) or one starting with a dot."""
    safe = _NOT_IN_NAMES.sub("_", text)
    return f"_{safe}" if _WINDOWS_RESERVED.fullmatch(safe) else safe


def symbols(library: str) -> dict[str, str]:
    """Each symbol block of a ``.kicad_sym``, by name."""
    return _children(library, "symbol")


def pins(symbol: str) -> list[tuple[str, str]]:
    """The sorted ``(name, number)`` of each pin of ``symbol``."""
    found = [(name or number)[1:-1] for name, number in _PIN.findall(symbol)]
    return sorted(zip(found[::2], found[1::2], strict=True))


def check(text: str) -> None:
    """Raise `ValueError` unless ``text`` is a whole s-expression file."""
    depth = 0
    for lexeme in _LEXEME.finditer(text):
        depth += {"(": 1, ")": -1}.get(lexeme.group(), 0)
        if depth < 0:
            break
    if depth != 0 or not text.strip():
        raise ValueError("empty or cut off, its parentheses do not balance")


def merge_symbols(library: str, entries: Iterable[Entry], bases: Iterable[str] = ()) -> str:
    """``library`` with each entry's symbol, replacing one of the same name, and the ``bases``.

    The base symbol an entry extends is added before it the first time and never replaced; a
    base in ``bases`` that the library lacks is added at the end.
    """
    for entry in entries:
        present = symbols(library)
        if entry.base is not None and _name(entry.base) not in present:
            library = _append(library, entry.base)
        old = present.get(entry.name)
        library = (
            _append(library, entry.symbol) if old is None else library.replace(old, entry.symbol, 1)
        )
    for base in bases:
        if _name(base) not in symbols(library):
            library = _append(library, base)
    return library


def register(table: str, nickname: str, uri: str) -> str:
    """``table``, a ``sym-lib-table``, with a library ``nickname`` at ``uri`` unless it has one."""
    if nickname in registered(table):
        return table
    fields = f'(name {_quote(nickname)}) (type "KiCad") (uri {_quote(uri)}) (options "") (descr "")'
    return _append(table, f"(lib {fields})")


def registered(table: str) -> dict[str, str]:
    """The uri of each library of ``table``, a ``sym-lib-table``, by nickname."""
    return {name[1:-1]: uri[1:-1] for name, uri in _TABLE_LIB.findall(table)}


def missing_pads(symbol: str, footprint: str) -> list[str]:
    """The pin numbers of ``symbol`` that ``footprint``, a ``.kicad_mod``, has no pad for."""
    pads = {pad.strip('"') for pad in re.findall(rf"\(pad ({_STRING}|[^\s()]+)", footprint)}
    pins = [pin[1:-1] for pin in re.findall(rf"\(number ({_STRING})", symbol)]
    return [pin for pin in pins if pin not in pads]


def _symbol_name(label: str, part: Part) -> str:
    return safe_name(f"{label} {part.package} - {part.mpn}")


def _kind(part: Part) -> str:
    return _PAREN.sub("", part.category)


def _fields(part: Part, value: str, footprint: str) -> dict[str, str]:
    return {
        "Value": value,
        "Footprint": footprint,
        "Datasheet": part.datasheet or "",
        "Description": part.description,
        "MPN": part.mpn,
        "Manufacturer": part.manufacturer,
        "LCSC": part.lcsc,
    }


def _with_fields(properties: dict[str, str], fields: dict[str, str]) -> list[str]:
    template = properties.get("Datasheet") or properties["Footprint"]
    keywords = [block for name, block in properties.items() if name.startswith("ki_")]
    blocks = [
        _with_value(block, name, fields.pop(name, None))
        for name, block in properties.items()
        if not name.startswith("ki_")
    ]
    blocks += [_with_value(template, name, value) for name, value in fields.items()]
    return [*blocks, *keywords]


def _head(text: str, start: int) -> str | None:
    head = _HEAD.match(text, start)
    return None if head is None else head[1]


def _spans(text: str, depth: int) -> Iterator[tuple[int, int]]:
    level = start = 0
    for lexeme in _LEXEME.finditer(text):
        if lexeme.group() == "(":
            if level == depth:
                start = lexeme.start()
            level += 1
        elif lexeme.group() == ")":
            level -= 1
            if level == depth:
                yield start, lexeme.end()


def _children(block: str, kind: str) -> dict[str, str]:
    found = {}
    for start, end in _spans(block, 1):
        head = _HEAD.match(block, start)
        if head is not None and head[1] == kind:
            found[head[2][1:-1]] = block[start:end]
    return found


def _name(block: str) -> str:
    head = _HEAD.match(block)
    assert head is not None
    return head[2][1:-1]


def _with_value(block: str, name: str, value: str | None) -> str:
    if value is None:
        return block
    return _PROPERTY.sub(lambda _: f"(property {_quote(name)} {_quote(value)}", block, count=1)


def _append(text: str, block: str) -> str:
    end = text.rindex(")")
    return f"{text[:end]}\t{block}\n{text[end:]}"


def _quote(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'
