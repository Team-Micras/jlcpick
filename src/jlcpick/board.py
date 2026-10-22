"""What a ``.kicad_pcb`` says about its footprints and about the bare board a fab makes."""

import math
import re
from dataclasses import dataclass
from typing import Literal

from jlcpick.bom_input import BomError

_TOKEN = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+')
_SOLDERED = ("smd", "thru_hole")
_POINTS = ("start", "mid", "end", "center")

type Sexpr = list[str | Sexpr]


@dataclass(frozen=True)
class Footprint:
    """A placed footprint: ``name`` is its ``Library:Footprint``, ``joints`` counts its distinct
    soldered pad numbers."""

    name: str
    joints: int
    side: Literal["top", "bottom"]
    tht: bool


@dataclass(frozen=True)
class Fabrication:
    """The bare board: the outline's bounding box, copper layers and thickness, in mm."""

    width_mm: float
    length_mm: float
    layers: int
    thickness_mm: float
    unmeasured: tuple[str, ...] = ()


def fabrication(pcb: str) -> Fabrication:
    """Read the board's size from its Edge.Cuts drawings, and its copper layers and thickness.

    Only the board's own drawings count: Edge.Cuts inside a footprint is not measured, and the
    references of the footprints that have some are in ``unmeasured``.
    """
    board = _parse(pcb)
    nodes = [node for node in board if isinstance(node, list) and node]
    edges = [n for n in nodes if str(n[0]).startswith("gr_") and ["layer", "Edge.Cuts"] in n]
    points = [p for edge in edges for p in _extent(edge)]
    if not points:
        raise BomError("no board outline: draw it on the Edge.Cuts layer")
    general = next((n for n in nodes if n[0] == "general"), [])
    thickness = next((c[1] for c in general if isinstance(c, list) and c[0] == "thickness"), None)
    if not isinstance(thickness, str):
        raise BomError("no board thickness in the file; save the board again in KiCad")
    copper = [
        layer
        for node in nodes
        if node[0] == "layers"
        for layer in node[1:]
        if isinstance(layer, list) and str(layer[1]).endswith(".Cu")
    ]
    xs, ys = [x for x, _ in points], [y for _, y in points]
    return Fabrication(
        width_mm=round(max(xs) - min(xs), 2),
        length_mm=round(max(ys) - min(ys), 2),
        layers=len(copper),
        thickness_mm=float(thickness),
        unmeasured=tuple(
            reference
            for node in nodes
            if node[0] == "footprint"
            for children in [[c for c in node if isinstance(c, list) and c]]
            if any(str(c[0]).startswith("fp_") and ["layer", "Edge.Cuts"] in c for c in children)
            if (reference := _reference(children))
        ),
    )


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
        reference = _reference(children)
        if not reference:
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


def _reference(children: list[Sexpr]) -> str:
    reference = next(
        (
            c[2]
            for c in children
            if len(c) > 2 and c[:2] in (["property", "Reference"], ["fp_text", "reference"])
        ),
        "",
    )
    return reference if isinstance(reference, str) else ""


def _extent(shape: Sexpr) -> list[tuple[float, float]]:
    at = {str(c[0]): _xy(c) for c in shape if isinstance(c, list) and c[0] in _POINTS}
    if shape[0] == "gr_circle":
        (x, y), r = at["center"], math.dist(at["center"], at["end"])
        return [(x - r, y - r), (x + r, y + r)]
    if shape[0] == "gr_arc" and "mid" not in at:
        raise BomError("an arc in the old KiCad 5 format; open and save the board in KiCad")
    if shape[0] == "gr_arc":
        return [at["start"], at["end"], *_arc_extremes(at["start"], at["mid"], at["end"])]
    corners = [
        point
        for c in shape
        if isinstance(c, list) and c[0] == "pts"
        for item in c[1:]
        if isinstance(item, list)
        for point in _pts_item(item)
    ]
    return [*at.values(), *corners]


def _pts_item(item: Sexpr) -> list[tuple[float, float]]:
    if item[0] != "arc":
        return [_xy(item)]
    at = {str(c[0]): _xy(c) for c in item if isinstance(c, list)}
    return [at["start"], at["end"], *_arc_extremes(at["start"], at["mid"], at["end"])]


def _xy(node: Sexpr) -> tuple[float, float]:
    return float(str(node[1])), float(str(node[2]))


def _arc_extremes(
    start: tuple[float, float], mid: tuple[float, float], end: tuple[float, float]
) -> list[tuple[float, float]]:
    (ax, ay), (bx, by), (cx, cy) = start, mid, end
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if d == 0:
        return []
    ux = (
        (ax**2 + ay**2) * (by - cy) + (bx**2 + by**2) * (cy - ay) + (cx**2 + cy**2) * (ay - by)
    ) / d
    uy = (
        (ax**2 + ay**2) * (cx - bx) + (bx**2 + by**2) * (ax - cx) + (cx**2 + cy**2) * (bx - ax)
    ) / d
    r = math.dist((ux, uy), start)
    turn = 2 * math.pi
    a0, am, a1 = (math.atan2(y - uy, x - ux) for x, y in (start, mid, end))
    if (am - a0) % turn > (a1 - a0) % turn:
        a0, a1 = a1, a0
    return [
        (ux + r * math.cos(a), uy + r * math.sin(a))
        for a in (0, math.pi / 2, math.pi, -math.pi / 2)
        if (a - a0) % turn <= (a1 - a0) % turn
    ]


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
