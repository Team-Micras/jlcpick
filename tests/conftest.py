import io
import json
import sys
from collections.abc import Callable
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from jlcpick.cli import main

PARTS = Path(__file__).parent / "fixtures" / "parts"
SEARCHES = Path(__file__).parent / "fixtures" / "search"
STEPS = Path(__file__).parent / "fixtures" / "step"
BOARD_PRICE = Path(__file__).parent / "fixtures" / "quote" / "mainboard_response.json"
KICAD_BOM = Path(__file__).parent / "fixtures" / "MicrasMainBoard-kicad-bom.csv"
FAKE_KICAD_CLI = """#!{python}
import json, shutil, sys
from pathlib import Path

args = sys.argv[1:]
Path(__file__).with_name("args.json").write_text(json.dumps(args))
shutil.copy({bom!r}, args[args.index("-o") + 1])
"""


def run(*argv: str) -> None:
    """Run the CLI and fail on a non-zero exit."""
    try:
        main(list(argv))
    except SystemExit as exit_info:
        if exit_info.code not in (None, 0):
            raise


def recorded(request: Request, timeout: float) -> io.BytesIO:
    """Answer like JLCPCB and EasyEDA did when the fixtures were recorded."""
    url = request.full_url
    if url.startswith("https://cart.jlcpcb.com/"):
        return io.BytesIO(BOARD_PRICE.read_bytes())
    if url.startswith("https://jlcpcb.com/"):
        assert isinstance(request.data, bytes)
        body = json.loads(request.data)
        if "componentLibraryType" in body:
            return io.BytesIO((SEARCHES / f"{body['keyword'].replace('/', '_')}.json").read_bytes())
        return io.BytesIO((PARTS / f"{body['keyword']}_jlc.json").read_bytes())
    if url.startswith("https://easyeda.com/api/products/"):
        return io.BytesIO((PARTS / f"{url.split('/')[-2]}_easyeda.json").read_bytes())
    if url.startswith("https://modules.easyeda.com/"):
        return io.BytesIO((STEPS / f"{url.rsplit('/', 1)[-1]}.step").read_bytes())
    raise AssertionError(f"unexpected request to {url}")


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Callable[..., None]:
    """Serve the recorded fixtures instead of the network, from a clean working directory."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("jlcpick.sources.http.PAUSE_S", {})
    monkeypatch.setattr("jlcpick.sources.http.DEFAULT_PAUSE_S", 0)

    def serve(blocked_host: str | None = None) -> None:
        """Answer from the fixtures; ``blocked_host`` and its subdomains answer 403."""

        def urlopen(request: Request, timeout: float) -> io.BytesIO:
            if blocked_host is not None and request.host.endswith(blocked_host):
                raise HTTPError(request.full_url, 403, "Forbidden", Message(), None)
            return recorded(request, timeout)

        monkeypatch.setattr("jlcpick.sources.http.urlopen", urlopen)

    serve()
    return serve


@pytest.fixture
def kicad_cli(tmp_path: Path) -> Path:
    """A fake ``kicad-cli`` that exports the MainBoard's recorded BOM and writes the arguments it
    got to ``args.json`` beside it."""
    folder = tmp_path / "kicad"
    folder.mkdir()
    fake = folder / "kicad-cli"
    fake.write_text(FAKE_KICAD_CLI.format(python=sys.executable, bom=str(KICAD_BOM)))
    fake.chmod(0o755)
    return fake


def mainboard_schematic() -> str:
    """Write the MainBoard's root sheet and a subsheet: the codes are in two fields, one typed in
    lowercase with spaces, and a library symbol holds a third that no placed symbol uses."""
    Path("MicrasMainBoard.kicad_sch").write_text(
        '(kicad_sch (lib_symbols (symbol "Device:R" (property "LCSC" "C25744")))\n'
        '  (symbol (lib_id "Device:R") (property "SUPPLIER PART" "C307331")))\n'
    )
    Path("power.kicad_sch").write_text('(kicad_sch (symbol (property "LCSC Part #" " c8734 ")))\n')
    return "MicrasMainBoard.kicad_sch"
