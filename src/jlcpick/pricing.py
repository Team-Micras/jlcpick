"""JLCPCB assembly pricing: the units JLC charges, their unit price and the order's fees.

Every fee comes from the page at `FEES_SOURCE` as it read on `FEES_AS_OF`; change them together.
"""

import re
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
XRAY: Bands = (
    (1, 1.64), (11, 0.82), (51, 0.49), (201, 0.33), (501, 0.25), (1_001, 0.16), (3_001, 0.082)
)  # fmt: skip
LEADLESS = re.compile(r"BGA|QFN|DFN|LGA|WLCSP|FQFPN", re.IGNORECASE)
STANDARD_MIN_GAP = 14.93


@dataclass(frozen=True)
class Placement:
    """A distinct part of the order; ``joints`` covers every board.

    ``units`` is the parts placed on every board. ``tht`` and ``joints`` are None without a board
    file, and the part is priced as SMT.
    """

    part: Part
    units: int
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
    xray_units: int
    xray_each_usd: float
    xray_usd: float
    handling_usd: float
    total_usd: float


def charged(part: Part, need: int) -> int:
    """Units JLC bills for ``need`` placed: basic by use, the rest with attrition and a minimum."""
    return need if part.tier == "basic" else max(need + part.loss_qty, part.min_qty)


def unit_usd(part: Part, qty: int) -> float:
    """Unit price at the break ``qty`` reaches, or the first break below it."""
    return _rate(tuple((price.from_qty, price.usd) for price in part.prices), qty)


def pays_feeder(part: Part, assembly: Assembly) -> bool:
    """Whether ``part``, placed by machine, pays the feeder fee.

    Economic charges it for extended parts that are not preferred; Standard, for every part.
    """
    return assembly == "standard" or (part.tier == "extended" and not part.preferred)


def fees(assembly: Assembly, placements: Sequence[Placement], sides: int) -> Fees:
    """Fees of assembling ``placements`` on ``sides`` sides.

    Hand-soldered (THT) parts use no feeder; SMT parts pay it as `pays_feeder` says. Standard
    charges the shortfall when it costs less than `STANDARD_MIN_GAP` over Economic.
    Every SMT unit whose package is leadless (`LEADLESS`) pays X-ray inspection, at the rate of
    the total count.
    """
    schedule = SCHEDULES[assembly]
    smt = [p for p in placements if not p.tht]
    manual = [p for p in placements if p.tht]
    sides_billed = sides if schedule.per_side else 1
    feeder_parts = tuple(p.part.lcsc for p in smt if pays_feeder(p.part, assembly))
    smt_joints = _joints(smt)
    manual_joints = _joints(manual)
    xray_units = sum(p.units for p in smt if LEADLESS.search(p.part.package))
    usd = {
        "setup_usd": schedule.setup * sides_billed if placements else 0.0,
        "stencil_usd": schedule.stencil * sides_billed if smt else 0.0,
        "feeder_usd": schedule.feeder * len(feeder_parts),
        "smt_joints_usd": (smt_joints or 0) * _rate(schedule.smt_joint, smt_joints or 0),
        "manual_usd": (manual_joints or 0) * _rate(MANUAL_JOINT, manual_joints or 0)
        + (MANUAL_LABOR if manual else 0.0),
        "xray_usd": xray_units * _rate(XRAY, xray_units),
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
        xray_units=xray_units,
        xray_each_usd=_rate(XRAY, xray_units),
        handling_usd=handling,
        total_usd=round(sum(rounded.values()) + handling, 2),
    )


def _joints(placements: Sequence[Placement]) -> int | None:
    counts = [p.joints for p in placements]
    return None if None in counts else sum(c for c in counts if c is not None)


def _rate(bands: Bands, count: int) -> float:
    return next((usd for start, usd in reversed(bands) if count >= start), bands[0][1])
