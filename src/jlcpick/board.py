"""Footprints of a ``.kicad_pcb``: name, solder joints, side and through-hole, by designator."""

import re
from dataclasses import dataclass
from typing import Literal

from jlcpick.bom_input import BomError

_TOKEN = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+')
_SOLDERED = ("smd", "thru_hole")

type Sexpr = list[str | Sexpr]


@dataclass(frozen=True)
class Footprint:
    """A placed footprint: ``name`` is its ``Library:Footprint``, ``joints`` counts its distinct
    soldered pad numbers."""

    name: str
    joints: int
    side: Literal["top", "bottom"]
    tht: bool


def footprints(pcb: str) -> dict[str, Footprint]:
    """Read every footprint with a reference from the text of a ``.kicad_pcb``.

    A footprint is through-hole when its attributes say so or, with no ``smd`` attribute, when
    every soldered pad is a plated hole: boards imported from Altium carry no attributes, and an
    SMD USB-C with plated shell legs is still placed by machine.
    """
    found: dict[str, Footprint] = {}
    for node in _parse(pcb):
        if not (isinstance(node, list) and node[:1] == ["footprint"]):
            continue
        children = [child for child in node if isinstance(child, list) and child]
        reference = next(
            (
                c[2]
                for c in children
                if len(c) > 2 and c[:2] in (["property", "Reference"], ["fp_text", "reference"])
            ),
            "",
        )
        if not isinstance(reference, str) or not reference:
            continue
        pads = [c for c in children if c[0] == "pad" and len(c) > 2 and c[2] in _SOLDERED]
        attributes = next((c[1:] for c in children if c[0] == "attr"), [])
        layer = next((c[1] for c in children if c[0] == "layer"), "F.Cu")
        found[reference] = Footprint(
            name=node[1] if isinstance(node[1], str) else "",
            joints=len({pad[1] for pad in pads if pad[1]}),
            side="bottom" if layer == "B.Cu" else "top",
            tht="through_hole" in attributes
            or ("smd" not in attributes and bool(pads) and all(p[2] == "thru_hole" for p in pads)),
        )
    return found


def _parse(pcb: str) -> Sexpr:
    stack: list[Sexpr] = [[]]
    for match in _TOKEN.finditer(pcb):
        token = match.group()
        if token == "(":
            stack.append([])
        elif token == ")" and len(stack) > 1:
            closed = stack.pop()
            stack[-1].append(closed)
        else:
            stack[-1].append(token[1:-1] if token.startswith('"') else token)
    match stack:
        case [[["kicad_pcb", *board]]]:
            return board
    raise BomError("not a KiCad board file")
