"""EasyEDA CAD data and the only use of easyeda2kicad."""

import json
import math
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any

from easyeda2kicad.easyeda.easyeda_importer import (
    Easyeda3dModelImporter,
    EasyedaFootprintImporter,
    EasyedaSymbolImporter,
)
from easyeda2kicad.easyeda.parameters_easyeda import Ee3dModel
from easyeda2kicad.kicad.export_kicad_footprint import ExporterFootprintKicad
from easyeda2kicad.kicad.export_kicad_symbol import ExporterSymbolKicad
from easyeda2kicad.kicad.parameters_kicad_footprint import Ki3dModelBase

from jlcpick.sources.http import SourceError, fetch, fetch_json

CAD_URL = "https://easyeda.com/api/products/{lcsc}/components?version=6.4.19.5"
STEP_URL = "https://modules.easyeda.com/qAxj6KHrDKw4blvCG8QJPs7Y/{uuid}"
CACHE = Path(".jlcpick/cache")
KICAD_10_SYMBOLS = 20251024
_NUMBER = r"[-+0-9.Ee]+"
_POINT = re.compile(
    rf"#(\d+)\s*=\s*CARTESIAN_POINT\s*\(\s*'[^']*'\s*,\s*"
    rf"\(\s*({_NUMBER})\s*,\s*({_NUMBER})\s*,\s*({_NUMBER})\s*\)"
)
_VERTEX = re.compile(r"VERTEX_POINT\s*\(\s*'[^']*'\s*,\s*#(\d+)")


class StepError(SourceError):
    """EasyEDA's STEP model cannot be read for its position."""


@dataclass(frozen=True)
class RawCad:
    """EasyEDA's component data and its STEP model, if it has one."""

    cad: dict[str, Any]
    step: bytes | None


def cad(lcsc: str) -> RawCad | None:
    """Fetch the CAD data of ``lcsc`` through the cache; None when EasyEDA has none."""
    cad_path = CACHE / f"{lcsc}.json"
    if not cad_path.exists():
        response = fetch_json(CAD_URL.format(lcsc=lcsc))
        try:
            if not response.get("success"):
                if response.get("code") == 404:
                    return None
                raise SourceError(f"{lcsc}: EasyEDA answered {response.get('message')}")
            body = json.dumps({"result": response["result"]})
        except (KeyError, TypeError, AttributeError) as error:
            raise SourceError(f"{lcsc}: EasyEDA answered in an unexpected format") from error
        _write(cad_path, body.encode())
    data = json.loads(cad_path.read_bytes())["result"]
    model = Easyeda3dModelImporter(data, download_raw_3d_model=False).output
    if model is None:
        return RawCad(data, None)
    step_path = CACHE / f"{lcsc}.step"
    if not step_path.exists():
        _write(step_path, fetch(STEP_URL.format(uuid=model.uuid)))
    return RawCad(data, step_path.read_bytes())


def package(raw: RawCad) -> str:
    """EasyEDA's name for the footprint of ``raw``."""
    return EasyedaFootprintImporter(raw.cad).get_footprint().info.name


def symbol(raw: RawCad) -> str:
    """Convert ``raw`` to a KiCad 10 symbol block indented by tabs, without EasyEDA's ``LCSC Part``
    field."""
    converted = EasyedaSymbolImporter(raw.cad).get_symbol()
    converted.info.lcsc_id = ""
    text = ExporterSymbolKicad(converted, version=KICAD_10_SYMBOLS).export("").strip()
    return re.sub(r"(?m)^(?:  )+", lambda indent: "\t" * (len(indent[0]) // 2), text)


def footprint(
    raw: RawCad, step_path: PurePath, *, bare: bool = False, with_model: bool = True
) -> str:
    """Convert ``raw`` to a ``.kicad_mod`` with its 3D model pointing at ``step_path`` and placed
    where EasyEDA places it. ``bare`` leaves out the part's LCSC code, MPN, maker and description,
    so parts of one package share the file; ``with_model=False`` leaves out the 3D model. Raise
    `StepError` when the STEP's position cannot be read.

    easyeda2kicad 1.0.1 leaves the STEP's offset at 0. EasyEDA puts the centre of the model's
    box, turned as the footprint turns it, at its translation and the model's bottom at its
    height; the offset here does that.

    The box is that of the STEP's ``VERTEX_POINT``s, read from the text. It assumes that circular
    edges have vertices at their extremes, that the STEP has no ``MAPPED_ITEM`` or other
    placement transformation, and that it is in millimetres, as every EasyEDA STEP measured is.
    Off a multiple of 90 degrees the box can miss an arc's bulge by about 0.01 mm.
    """
    exporter = ExporterFootprintKicad(EasyedaFootprintImporter(raw.cad).get_footprint())
    ki = exporter.get_ki_footprint()
    if bare:
        ki.info.lcsc_id = ki.info.manufacturer = ki.info.mpn = ki.info.description = ""
    model, source = ki.model_3d, exporter.input.model_3d
    if not with_model:
        ki.model_3d = None
    elif model is not None:
        model.name = step_path.stem
        if source is not None and raw.step is not None:
            model.translation = _step_offset(source, raw.step)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "footprint.kicad_mod"
        exporter.export(str(path), step_path.parent.as_posix(), step_path.suffix[1:])
        return path.read_text(encoding="utf-8")


def _step_offset(model: Ee3dModel, step: bytes) -> Ki3dModelBase:
    text = step.decode("latin-1")
    points = {number: xyz for number, *xyz in _POINT.findall(text)}
    rotation = (model.rotation.x, model.rotation.y, model.rotation.z)
    try:
        vertices = [_rotated(points[number], rotation) for number in _VERTEX.findall(text)]
    except KeyError as error:
        raise StepError(
            f"{model.name}: EasyEDA's STEP model has a vertex without a point"
        ) from error
    if not vertices:
        raise StepError(f"{model.name}: EasyEDA's STEP model has no vertices")
    xs, ys, zs = zip(*vertices, strict=True)
    return Ki3dModelBase(
        x=round(model.translation.x - (min(xs) + max(xs)) / 2, 3) + 0.0,
        y=round(model.translation.y - (min(ys) + max(ys)) / 2, 3) + 0.0,
        z=round(model.translation.z - min(zs), 3) + 0.0,
    )


def _rotated(point: list[str], degrees: tuple[float, ...]) -> tuple[float, float, float]:
    x, y, z = map(float, point)
    a, b, c = map(math.radians, map(float, degrees))
    y, z = y * math.cos(a) - z * math.sin(a), y * math.sin(a) + z * math.cos(a)
    x, z = x * math.cos(b) + z * math.sin(b), -x * math.sin(b) + z * math.cos(b)
    return x * math.cos(c) - y * math.sin(c), x * math.sin(c) + y * math.cos(c), z


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)
