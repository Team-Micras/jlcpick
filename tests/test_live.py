import json
from pathlib import Path

import pytest
from conftest import run


@pytest.mark.live
def test_live_get_c25744(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    run("get", "C25744", "--json", "--out", "lib")

    assert Path("lib/C25744.kicad_mod").read_text().count("(pad ") == 2
    assert Path("lib/C25744.step").read_bytes().startswith(b"ISO-10303-21")


@pytest.mark.live
def test_live_bom_swaps_an_extended_18pf_for_the_basic_c1549(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("bom.csv").write_text("C5137554\n")

    run("bom", "bom.csv", "--json")

    [line] = json.loads(capsys.readouterr().out)["lines"]
    assert (line["swap"]["verdict"], line["swap"]["to"]["lcsc"]) == ("swap", "C1549")


@pytest.mark.live
def test_live_quote_prices_the_mainboard_boards_that_cost_us_8_00_on_2026_10_21(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pcb = Path(__file__).parent / "fixtures/MicrasMainBoard.kicad_pcb"
    monkeypatch.chdir(tmp_path)
    Path("bom.csv").write_text("C25744\n")

    run("quote", "bom.csv", "--pcb", str(pcb), "--qty", "5", "--json")

    board = json.loads(capsys.readouterr().out)["board"]
    assert board["usd"] > 0
    assert board["build_time"]
