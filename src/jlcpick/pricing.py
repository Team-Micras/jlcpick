"""JLCPCB assembly pricing: the units JLC charges, their unit price and the order's fees.

Every fee comes from the page at `FEES_SOURCE` as it read on `FEES_AS_OF`; change them together.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from jlcpick.sources.jlc import Part

FEES_AS_OF = "2026-09-09"
FEES_SOURCE = "https://jlcpcb.com/help/article/pcb-assembly-price"

type Assembly = Literal["economic", "standard"]
type Bands = tuple[tuple[int, float], ...]


@dataclass(frozen=True)
class Schedule:
    """One assembly option's fees in US$; ``bands`` are ``(from_count, usd)`` rates."""

    setup: float
    stencil: float
    per_side: bool
    feeder: float
    smt_joint: Bands


SCHEDULES: dict[Assembly, Schedule] = {
    "economic": Schedule(
        setup=8.18, stencil=1.53, per_side=False, feeder=3.07, smt_joint=((1, 0.0016),)
    ),
    "standard": Schedule(
        setup=25.56,
        stencil=8.21,
        per_side=True,
        feeder=1.53,
        smt_joint=((1, 0.0016), (50_001, 0.0013), (100_001, 0.0012)),
    ),
}
MANUAL_JOINT: Bands = ((1, 0.0164), (10_001, 0.015), (30_001, 0.012))
MANUAL_LABOR = 3.58
STANDARD_MIN_GAP = 14.93


@dataclass(frozen=True)
class Placement:
    """A distinct part of the order; ``joints`` covers every board.

    ``tht`` and ``joints`` are None without a board file, and the part is priced as SMT.
    """

    part: Part
    tht: bool | None
    joints: int | None


@dataclass(frozen=True)
class Fees:
    """The order's assembly fees in US$, each rounded to the cent as JLC shows them."""

    setup_usd: float
    stencil_usd: float
    feeder_parts: tuple[str, ...]
    feeder_each_usd: float
    feeder_usd: float
    smt_joints: int | None
    smt_joints_usd: float
    manual_joints: int | None
    manual_usd: float
    handling_usd: float
    total_usd: float


def charged(part: Part, need: int) -> int:
    """Units JLC bills for ``need`` placed: basic by use, the rest with attrition and a minimum."""
    return need if part.tier == "basic" else max(need + part.loss_qty, part.min_qty)


def unit_usd(part: Part, qty: int) -> float:
    """Unit price at the break ``qty`` reaches, or the first break below it."""
    return _rate(tuple((price.from_qty, price.usd) for price in part.prices), qty)


def fees(assembly: Assembly, placements: Sequence[Placement], sides: int) -> Fees:
    """Fees of assembling ``placements`` on ``sides`` sides.

    Hand-soldered (THT) parts use no feeder. Economic charges the feeder fee only for extended
    parts that are not preferred; Standard charges it for every SMT part, and charges the
    shortfall when it costs less than `STANDARD_MIN_GAP` over Economic.
    """
    schedule = SCHEDULES[assembly]
    smt = [p for p in placements if not p.tht]
    manual = [p for p in placements if p.tht]
    sides_billed = sides if schedule.per_side else 1
    feeder_parts = tuple(
        p.part.lcsc
        for p in smt
        if assembly == "standard" or (p.part.tier == "extended" and not p.part.preferred)
    )
    smt_joints = _joints(smt)
    manual_joints = _joints(manual)
    usd = {
        "setup_usd": schedule.setup * sides_billed if placements else 0.0,
        "stencil_usd": schedule.stencil * sides_billed if smt else 0.0,
        "feeder_usd": schedule.feeder * len(feeder_parts),
        "smt_joints_usd": (smt_joints or 0) * _rate(schedule.smt_joint, smt_joints or 0),
        "manual_usd": (manual_joints or 0) * _rate(MANUAL_JOINT, manual_joints or 0)
        + (MANUAL_LABOR if manual else 0.0),
    }
    rounded = {name: round(value, 2) for name, value in usd.items()}
    handling = 0.0
    if assembly == "standard":
        gap = sum(rounded.values()) - fees("economic", placements, sides).total_usd
        handling = round(max(0.0, STANDARD_MIN_GAP - gap), 2)
    return Fees(
        **rounded,
        feeder_parts=feeder_parts,
        feeder_each_usd=schedule.feeder,
        smt_joints=smt_joints,
        manual_joints=manual_joints,
        handling_usd=handling,
        total_usd=round(sum(rounded.values()) + handling, 2),
    )


def _joints(placements: Sequence[Placement]) -> int | None:
    counts = [p.joints for p in placements]
    return None if None in counts else sum(c for c in counts if c is not None)


def _rate(bands: Bands, count: int) -> float:
    return next((usd for start, usd in reversed(bands) if count >= start), bands[0][1])
