from pathlib import Path

import pytest
from conftest import run


@pytest.mark.live
def test_live_get_c25744(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    run("get", "C25744", "--json", "--out", "lib")

    assert Path("lib/C25744.kicad_mod").read_text().count("(pad ") == 2
    assert Path("lib/C25744.step").read_bytes().startswith(b"ISO-10303-21")
