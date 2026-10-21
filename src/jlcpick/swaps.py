"""Safe swaps: basic or preferred parts that replace an extended one without any worse field.

The rules, in order: a basic or preferred part with the same MPN; else, for resistors and
capacitors, one in the same JLC category and package, with the same value and every known field
equal or better. Electrolytic and polymer capacitors, shunts below 1 Ω and parts JLC lists a
field of as ``-`` are to check by hand. Other kinds of part have no rule.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields
from typing import Literal

from jlcpick import params
from jlcpick.params import CapSpec, ResSpec
from jlcpick.sources.jlc import Part

type Verdict = Literal["swap", "to_check", "no_rule", "keep"]
type Search = Callable[[str], Sequence[Part]]

DIELECTRIC_RANK = {"C0G": 3, "NP0": 3, "X7R": 2, "X5R": 1, "Y5V": 0}
_FIELDS = {"voltage_v": ("V", True), "power_w": ("W", True), "tolerance": ("%", False),
           "tempco_ppm": ("ppm/°C", False)}  # fmt: skip


@dataclass(frozen=True)
class Suggestion:
    """What to do with a part and why; ``candidates`` are the safe replacements of a swap."""

    verdict: Verdict
    reason: str
    candidates: tuple[Part, ...] = ()


def suggest(part: Part, search: Search) -> Suggestion:
    """Apply the rules to ``part``; ``search`` returns the basic or preferred parts of a keyword."""
    if part.tier == "basic" or part.preferred:
        return Suggestion("keep", f"already {'basic' if part.tier == 'basic' else 'preferred'}")
    mpn = part.mpn.casefold()
    same_mpn = [c for c in _in_stock(search(part.mpn), part) if c.mpn.casefold() == mpn]
    if same_mpn:
        return Suggestion("swap", "same MPN", tuple(same_mpn))
    old = params.spec(part)
    if old is None:
        return Suggestion("no_rule", f"no rule for {part.category}")
    doubt = _doubt(part, old)
    if doubt:
        return Suggestion("to_check", doubt)
    value = part.params["Capacitance" if isinstance(old, CapSpec) else "Resistance"]
    found = _in_stock(search(f"{value} {part.package}"), part)
    judged = [
        (candidate, _compare(old, new))
        for candidate in found
        if candidate.category == part.category
        and candidate.package == part.package
        and (new := params.spec(candidate)) is not None
        and type(new) is type(old)
        and math.isclose(_value(new), _value(old))
    ]
    safe = tuple(candidate for candidate, (worse, unknown) in judged if not worse + unknown)
    if safe:
        return Suggestion("swap", params.summary(part), safe)
    unsure = [f"{c.lcsc}: {', '.join(unknown)}" for c, (worse, unknown) in judged if not worse]
    if unsure:
        return Suggestion("to_check", "; ".join(unsure))
    if judged:
        return Suggestion("keep", "; ".join(f"{c.lcsc}: {', '.join(w)}" for c, (w, _) in judged))
    return Suggestion("keep", f"no basic or preferred {value} {part.package} in stock")


def _in_stock(found: Sequence[Part], part: Part) -> list[Part]:
    return [c for c in found if c.stock > 0 and c.lcsc != part.lcsc]


def _doubt(part: Part, spec: CapSpec | ResSpec) -> str | None:
    category = part.category.casefold()
    if "electrolytic" in category or "polymer" in category:
        return "electrolytic or polymer capacitor"
    if isinstance(spec, ResSpec) and spec.value_ohm < 1:
        return "shunt below 1 Ω"
    missing = [f.name for f in fields(spec) if getattr(spec, f.name) is None]
    if missing:
        return f"JLC lists no {', '.join(_label(name) for name in missing)}"
    if isinstance(spec, CapSpec) and spec.dielectric not in DIELECTRIC_RANK:
        return f"dielectric {spec.dielectric} has no rank"
    return None


def _value(spec: CapSpec | ResSpec) -> float:
    return spec.value_f if isinstance(spec, CapSpec) else spec.value_ohm


def _compare(old: CapSpec | ResSpec, new: CapSpec | ResSpec) -> tuple[list[str], list[str]]:
    """The fields where ``new`` is worse than ``old``, and those it does not list or rank."""
    worse, unknown = [], []
    if isinstance(old, CapSpec) and isinstance(new, CapSpec):
        rank = DIELECTRIC_RANK.get(new.dielectric or "")
        if rank is None:
            unknown.append(f"dielectric {new.dielectric or 'not listed'}")
        elif rank < DIELECTRIC_RANK[old.dielectric or ""]:
            worse.append(f"dielectric {new.dielectric}")
    for name, (unit, higher) in _FIELDS.items():
        if not hasattr(old, name):
            continue
        before, after = getattr(old, name), getattr(new, name)
        if after is None:
            unknown.append(f"{_label(name)} not listed")
        elif (after < before) if higher else (after > before):
            worse.append(f"{_label(name)} {after:g}{unit} vs {before:g}{unit}")
    return worse, unknown


def _label(field: str) -> str:
    return field.split("_")[0]
