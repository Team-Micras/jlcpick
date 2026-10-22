"""The cost of a whole JLCPCB order: the bare boards plus their assembly."""

from dataclasses import dataclass

from jlcpick import bom
from jlcpick.board import Fabrication
from jlcpick.sources.jlc import BoardPrice


@dataclass(frozen=True)
class Board:
    """The bare boards as JLC priced them: ``thickness_mm`` is JLC's option nearest the
    ``kicad_thickness_mm`` the board file declares."""

    width_mm: float
    length_mm: float
    layers: int
    thickness_mm: float
    kicad_thickness_mm: float
    color: str
    usd: float
    build_time: str


@dataclass(frozen=True)
class Extended:
    """What the extended parts add to the order: their feeder fees, and the units JLC charges
    beyond those placed (attrition and minimums). In Standard every part pays the feeder fee,
    basic ones too, so ``feeder_usd`` is 0 there."""

    parts: int
    feeder_usd: float
    extra_units_usd: float
    usd: float
    share_pct: float


@dataclass(frozen=True)
class Quote:
    """A whole order for ``qty`` boards, before shipping and taxes."""

    name: str
    qty: int
    board: Board
    pcba: bom.Report
    extended: Extended
    total_usd: float


def quote(fabrication: Fabrication, price: BoardPrice, color: str, pcba: bom.Report) -> Quote:
    """Add the boards JLC priced at ``price`` to the assembly ``pcba``."""
    board = Board(
        width_mm=fabrication.width_mm,
        length_mm=fabrication.length_mm,
        layers=fabrication.layers,
        thickness_mm=price.thickness_mm,
        kicad_thickness_mm=fabrication.thickness_mm,
        color=color,
        usd=price.usd,
        build_time=price.build_time,
    )
    total = round(board.usd + pcba.total_usd, 2)
    extended = [line for line in pcba.lines if line.tier == "extended"]
    feeder = 0.0 if pcba.assembly == "standard" else pcba.fees.feeder_usd
    extra = round(sum((line.charged - line.need) * line.unit_usd for line in extended), 2)
    usd = round(feeder + extra, 2)
    return Quote(
        name=pcba.name,
        qty=pcba.qty,
        board=board,
        pcba=pcba,
        extended=Extended(len(extended), feeder, extra, usd, round(100 * usd / total, 1)),
        total_usd=total,
    )


def text(quote: Quote) -> str:
    """The quote as the terminal shows it."""
    board, pcba, extended = quote.board, quote.pcba, quote.extended
    thickness = f"{board.thickness_mm:.1f} mm"
    if board.kicad_thickness_mm != board.thickness_mm:
        thickness += f" (board file {board.kicad_thickness_mm:g})"
    left_out = "shipping, taxes and customs"
    if pcba.assembly == "standard":
        left_out += "; packing, fixture and the per-board batch fee of Standard"
    return "\n".join(
        [
            f"{quote.name}  ×{quote.qty}  {pcba.assembly.capitalize()}",
            "",
            f"  board      US$ {board.usd:.2f}   builds in {board.build_time}",
            f"             {board.layers} layers · {board.width_mm:g} × {board.length_mm:g} mm · "
            f"{thickness} · {board.color} · HASL",
            f"  assembly   US$ {pcba.total_usd:.2f}   parts {pcba.parts_usd:.2f} + "
            f"fees {pcba.fees.total_usd:.2f}, fees as of {pcba.fees_as_of}",
            f"  total      US$ {quote.total_usd:.2f}   per board US$ "
            f"{quote.total_usd / quote.qty:.2f}",
            f"  extended   US$ {extended.usd:.2f}, {extended.share_pct:.1f} % of the total",
            f"             feeder {extended.feeder_usd:.2f} + units beyond those placed "
            f"{extended.extra_units_usd:.2f}, on {extended.parts} extended parts",
            "",
            f"  not included: {left_out}",
            "  parts, fees and swaps: jlcpick bom",
        ]
    )
