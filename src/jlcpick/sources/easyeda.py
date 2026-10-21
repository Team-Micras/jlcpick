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
)
from easyeda2kicad.easyeda.parameters_easyeda import Ee3dModel
from easyeda2kicad.kicad.export_kicad_footprint import ExporterFootprintKicad
from easyeda2kicad.kicad.parameters_kicad_footprint import Ki3dModelBase

from jlcpick.sources.http import SourceError, fetch, fetch_json

CAD_URL = "https://easyeda.com/api/products/{lcsc}/components?version=6.4.19.5"
STEP_URL = "https://modules.easyeda.com/qAxj6KHrDKw4blvCG8QJPs7Y/{uuid}"
CACHE = Path(".jlcpick/cache")
_NUMBER = r"[-+0-9.Ee]+"
_POINT = re.compile(
    rf"#(\d+)\s*=\s*CARTESIAN_POINT\s*\(\s*'[^']*'\s*,\s*"
    rf"\(\s*({_NUMBER})\s*,\s*({_NUMBER})\s*,\s*({_NUMBER})\s*\)"
)
_VERTEX = re.compile(r"VERTEX_POINT\s*\(\s*'[^']*'\s*,\s*#(\d+)")


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


def footprint(raw: RawCad, step_path: PurePath) -> str:
    """Convert ``raw`` to a ``.kicad_mod``, its 3D model pointing at ``step_path`` and placed
    where EasyEDA places it.

    easyeda2kicad 1.0.1 leaves the STEP's offset at 0. EasyEDA puts the centre of the model's
    box, turned as the footprint turns it, at its translation and the model's bottom at its
    height; the offset here does that. It assumes the STEP is in millimetres, as every EasyEDA
    STEP measured is.
    """
    exporter = ExporterFootprintKicad(EasyedaFootprintImporter(raw.cad).get_footprint())
    model, source = exporter.get_ki_footprint().model_3d, exporter.input.model_3d
    if model is not None:
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
    vertices = [_rotated(points[number], rotation) for number in _VERTEX.findall(text)]
    if not vertices:
        raise SourceError(f"{model.name}: EasyEDA's STEP model has no vertices")
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
