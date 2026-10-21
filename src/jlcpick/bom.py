"""The cost of assembling a BOM at JLCPCB: what each part costs and the order's fees."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from jlcpick import pricing
from jlcpick.board import Footprint
from jlcpick.bom_input import BomLine
from jlcpick.sources.jlc import Part


@dataclass(frozen=True)
class Line:
    """One distinct part of the order: ``need`` units placed, ``charged`` units billed.

    ``tht`` and ``joints`` are None without a board file.
    """

    lcsc: str
    designators: tuple[str, ...]
    mpn: str
    tier: Literal["basic", "extended"]
    preferred: bool
    need: int
    charged: int
    unit_usd: float
    total_usd: float
    feeder_fee: bool
    tht: bool | None
    joints: int | None


@dataclass(frozen=True)
class Report:
    """A BOM's assembly cost for ``qty`` boards, costliest line first."""

    name: str
    qty: int
    assembly: pricing.Assembly
    fees_as_of: str
    fees_source: str
    sides: int
    lines: tuple[Line, ...]
    parts_usd: float
    fees: pricing.Fees
    total_usd: float
    warnings: tuple[str, ...]


def codes(lines: Sequence[BomLine]) -> list[str]:
    """The distinct LCSC codes of ``lines``, in BOM order."""
    return list(dict.fromkeys(line.lcsc for line in lines if line.lcsc))


def report(
    name: str,
    lines: Sequence[BomLine],
    parts: Mapping[str, Part],
    qty: int,
    assembly: pricing.Assembly,
    board: Mapping[str, Footprint] | None,
) -> Report:
    """Price ``lines`` for ``qty`` boards; ``parts`` holds every code of the lines."""
    warnings = [
        f"{', '.join(line.designators) or 'a row'}: no LCSC code, left out of the cost"
        for line in lines
        if not line.lcsc
    ]
    if board is None:
        warnings.append("no --pcb: joints n/d, THT unknown, one assembled side assumed")
    else:
        missing = [d for line in lines if line.lcsc for d in line.designators if d not in board]
        if missing:
            warnings.append(f"not on the board, no joints counted: {', '.join(missing)}")
    groups = {code: [line for line in lines if line.lcsc == code] for code in codes(lines)}
    placed = {
        code: None
        if board is None
        else [board[d] for line in group for d in line.designators if d in board]
        for code, group in groups.items()
    }
    placements = [_placement(parts[code], groups[code], placed[code], qty) for code in groups]
    sides = len({f.side for found in placed.values() for f in found or [] if not f.tht}) or 1
    fees = pricing.fees(assembly, placements, sides)
    priced = [
        _line(p, groups[p.part.lcsc], qty, p.part.lcsc in fees.feeder_parts) for p in placements
    ]
    priced.sort(key=lambda line: -line.total_usd - (fees.feeder_each_usd if line.feeder_fee else 0))
    parts_usd = round(sum(line.total_usd for line in priced), 2)
    return Report(
        name=name,
        qty=qty,
        assembly=assembly,
        fees_as_of=pricing.FEES_AS_OF,
        fees_source=pricing.FEES_SOURCE,
        sides=sides,
        lines=tuple(priced),
        parts_usd=parts_usd,
        fees=fees,
        total_usd=round(parts_usd + fees.total_usd, 2),
        warnings=tuple(warnings),
    )


def text(report: Report) -> str:
    """The report as the terminal shows it."""
    fees = report.fees
    source = report.fees_source.removeprefix("https://")
    total = report.total_usd
    lines = [
        f"{report.name}  ×{report.qty}  {report.assembly.capitalize()}"
        f"  fees as of {report.fees_as_of} ({source})",
        "",
        f"  parts      per board US$ {report.parts_usd / report.qty:.2f}"
        f"   total US$ {report.parts_usd:.2f}",
        f"  fees       {_fees(report)}",
        f"  joints     {_joints(report.fees)}",
        f"  total      US$ {total:.2f}   per board US$ {total / report.qty:.2f}",
    ]
    if report.assembly == "standard":
        lines.append("  not included: packing, fixture and the per-board batch fee of Standard")
    others = [line for line in report.lines if line.tier != "basic"]
    if others:
        lines += ["", f"  not basic ({len(others)})", _ROW.format(*_HEADER)]
        for line in others:
            fee = f"{fees.feeder_each_usd:.2f}" if line.feeder_fee else ""
            tier = "preferred" if line.preferred else "extended"
            lines.append(
                _ROW.format(
                    line.lcsc,
                    line.mpn[:20],
                    _short(line.designators),
                    tier,
                    line.need,
                    line.charged,
                    f"{line.total_usd:.2f}",
                    fee,
                )
            )
    basic = len(report.lines) - len(others)
    lines += ["", f"  basic ({basic}) → --json"]
    return "\n".join(line.rstrip() for line in lines)


_ROW = "    {:<10} {:<20} {:<14} {:<9} {:>5} {:>7} {:>9} {:>6}"
_HEADER = ("lcsc", "mpn", "designators", "tier", "used", "charged", "parts US$", "fee")


def _fees(report: Report) -> str:
    fees = report.fees
    schedule = pricing.SCHEDULES[report.assembly]
    sides = report.sides if schedule.per_side else 1
    feeder = "extended" if report.assembly == "economic" else "feeders"
    parts = [
        f"setup {_times(sides, schedule.setup, fees.setup_usd)}",
        f"stencil {_times(sides, schedule.stencil, fees.stencil_usd)}",
        f"{feeder} {len(fees.feeder_parts)} × {fees.feeder_each_usd:.2f} = {fees.feeder_usd:.2f}",
        f"x-ray {fees.xray_units} × {fees.xray_each_usd:.2f} = {fees.xray_usd:.2f}",
    ]
    if report.assembly == "standard":
        parts.append(f"handling {fees.handling_usd:.2f}")
    return " · ".join(parts)


def _times(count: int, unit: float, total: float) -> str:
    return f"{total:.2f}" if count == 1 else f"{count} × {unit:.2f} = {total:.2f}"


def _joints(fees: pricing.Fees) -> str:
    if fees.smt_joints is None:
        return "n/d"
    smt = f"SMT {fees.smt_joints:,} = {fees.smt_joints_usd:.2f}"
    if not fees.manual_joints:
        return smt
    return f"{smt} · hand-soldered {fees.manual_joints:,} + labor = {fees.manual_usd:.2f}"


def _short(designators: tuple[str, ...]) -> str:
    joined = ",".join(designators)
    return joined if len(joined) <= 14 else joined[:13] + "…"


def _placement(
    part: Part, group: list[BomLine], placed: list[Footprint] | None, qty: int
) -> pricing.Placement:
    units = sum(line.uses for line in group) * qty
    if placed is None:
        return pricing.Placement(part, units, tht=None, joints=None)
    return pricing.Placement(
        part,
        units,
        tht=any(footprint.tht for footprint in placed),
        joints=sum(footprint.joints for footprint in placed) * qty,
    )


def _line(placement: pricing.Placement, group: list[BomLine], qty: int, feeder_fee: bool) -> Line:
    part = placement.part
    need = placement.units
    charged = pricing.charged(part, need)
    unit = pricing.unit_usd(part, charged)
    return Line(
        lcsc=part.lcsc,
        designators=tuple(d for line in group for d in line.designators),
        mpn=part.mpn,
        tier=part.tier,
        preferred=part.preferred,
        need=need,
        charged=charged,
        unit_usd=unit,
        total_usd=round(charged * unit, 2),
        feeder_fee=feeder_fee,
        tht=placement.tht,
        joints=placement.joints,
    )
