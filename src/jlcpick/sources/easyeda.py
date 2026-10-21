"""EasyEDA CAD data and the only use of easyeda2kicad."""

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any

from easyeda2kicad.easyeda.easyeda_importer import (
    Easyeda3dModelImporter,
    EasyedaFootprintImporter,
)
from easyeda2kicad.kicad.export_kicad_footprint import ExporterFootprintKicad

from jlcpick.sources.http import fetch, fetch_json

CAD_URL = "https://easyeda.com/api/products/{lcsc}/components?version=6.4.19.5"
STEP_URL = "https://modules.easyeda.com/qAxj6KHrDKw4blvCG8QJPs7Y/{uuid}"
CACHE = Path(".jlcpick/cache")


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
        if not response.get("success"):
            return None
        _write(cad_path, json.dumps(response).encode())
    data = json.loads(cad_path.read_bytes())["result"]
    model = Easyeda3dModelImporter(data, download_raw_3d_model=False).output
    if model is None:
        return RawCad(data, None)
    step_path = CACHE / f"{lcsc}.step"
    if not step_path.exists():
        _write(step_path, fetch(STEP_URL.format(uuid=model.uuid)))
    return RawCad(data, step_path.read_bytes())


def footprint(raw: RawCad, step_path: PurePath) -> str:
    """Convert ``raw`` to a ``.kicad_mod``, its 3D model pointing at ``step_path``."""
    exporter = ExporterFootprintKicad(EasyedaFootprintImporter(raw.cad).get_footprint())
    model = exporter.get_ki_footprint().model_3d
    if model is not None:
        model.name = step_path.stem
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "footprint.kicad_mod"
        exporter.export(str(path), step_path.parent.as_posix(), step_path.suffix[1:])
        return path.read_text(encoding="utf-8")


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
