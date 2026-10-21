"""A KiCad BOM, or a bare list of LCSC codes, as the lines JLC assembles.

The BOM is the CSV of::

    kicad-cli sch export bom board.kicad_sch --ref-range-delimiter '' \\
        --fields 'Reference,Value,Footprint,QUANTITY,DNP,LCSC' \\
        --labels 'Refs,Value,Footprint,Qty,DNP,LCSC' --group-by 'Value,Footprint,LCSC,DNP'

where ``LCSC`` is the symbol field holding the code; put your field's name in ``--fields`` and keep
the label. Columns are matched by name, ignoring case: the code may also be in ``LCSC Part``,
``LCSC Part #``, ``JLCPCB Part #`` or ``Supplier Part``, the designators in ``Reference`` or
``Designator``. A one-column CSV of codes is a list, one use per row.
"""

import csv
import re
from dataclasses import dataclass, replace

_COLUMNS = {
    "lcsc": ("lcsc", "lcsc part", "lcsc part #", "lcsc part number", "jlcpcb part #",
             "supplier part"),
    "designators": ("refs", "reference", "designator", "designators"),
    "qty": ("qty", "quantity"),
    "dnp": ("dnp",),
}  # fmt: skip
_LCSC = re.compile(r"C\d+")


class BomError(ValueError):
    """A BOM or board file that jlcpick cannot use."""


@dataclass(frozen=True)
class BomLine:
    """One BOM row; ``lcsc`` is empty when the row has no code."""

    designators: tuple[str, ...]
    lcsc: str
    dnp: bool

    @property
    def uses(self) -> int:
        """Units per board: one per designator, or one for a row of a bare code list."""
        return len(self.designators) or 1


def read(text: str) -> list[BomLine]:
    """Parse a BOM or a code list; raise `BomError` naming what is wrong with it."""
    rows = [row for row in csv.reader(text.splitlines()) if any(cell.strip() for cell in row)]
    if rows and all(len(row) == 1 for row in rows):
        return _code_list([row[0] for row in rows])
    header = [cell.strip().lower() for cell in rows[0]] if rows else []
    columns = {
        key: next((header.index(name) for name in names if name in header), None)
        for key, names in _COLUMNS.items()
    }
    if columns["lcsc"] is None:
        raise BomError(f"the BOM has no LCSC column; name one of: {', '.join(_COLUMNS['lcsc'])}")
    if columns["designators"] is None:
        raise BomError("the BOM has no designator column, such as Refs or Designator")

    def cell(row: list[str], key: str) -> str:
        index = columns[key]
        return row[index].strip() if index is not None and index < len(row) else ""

    def line(number: int, row: list[str]) -> BomLine:
        designators = tuple(re.findall(r"[^,\s]+", cell(row, "designators")))
        qty = cell(row, "qty")
        if qty.isdigit() and int(qty) != len(designators):
            raise BomError(
                f"row {number}: Qty {qty} but {len(designators)} designators; ranges like C5-C8"
                " count as one, so export with --ref-range-delimiter ''"
            )
        dnp = cell(row, "dnp").lower() not in ("", "no", "0", "false")
        return BomLine(designators, _code(cell(row, "lcsc"), number), dnp)

    return [line(number, row) for number, row in enumerate(rows[1:], start=2)]


def assembled(lines: list[BomLine], exclude: set[str]) -> list[BomLine]:
    """Drop DNP lines and the ``exclude`` designators; raise `BomError` for unknown ones."""
    unknown = exclude - {designator for line in lines for designator in line.designators}
    if unknown:
        raise BomError(f"--exclude: not in the BOM: {', '.join(sorted(unknown))}")
    kept = []
    for line in lines:
        designators = tuple(d for d in line.designators if d not in exclude)
        if not line.dnp and (designators or not line.designators):
            kept.append(replace(line, designators=designators))
    return kept


def _code_list(cells: list[str]) -> list[BomLine]:
    start = 1 if _LCSC.fullmatch(cells[0].strip().upper()) else 2
    return [
        BomLine((), _code(code, number), False)
        for number, code in enumerate(cells[start - 1 :], start)
    ]


def _code(text: str, row: int) -> str:
    code = text.strip().upper()
    if code and not _LCSC.fullmatch(code):
        raise BomError(f"row {row}: {text!r} is not an LCSC code like C25744")
    return code
