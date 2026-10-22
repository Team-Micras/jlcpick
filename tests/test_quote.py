import io
import json
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path
from typing import Any
from urllib.request import Request

import pytest
from conftest import recorded, run

from jlcpick import quote
from jlcpick.cli import main

pytestmark = pytest.mark.usefixtures("network")

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests/fixtures"
MAINBOARD = [
    "quote",
    str(FIXTURES / "MicrasMainBoard-kicad-bom.csv"),
    "--pcb",
    str(FIXTURES / "MicrasMainBoard.kicad_pcb"),
]


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The bodies posted to JLCPCB's board calculator, answered from the recording."""
    bodies: list[dict[str, Any]] = []

    def urlopen(request: Request, timeout: float) -> io.BytesIO:
        if request.host == "cart.jlcpcb.com":
            assert isinstance(request.data, bytes)
            bodies.append(json.loads(request.data))
        return recorded(request, timeout)

    monkeypatch.setattr("jlcpick.sources.http.urlopen", urlopen)
    return bodies


def quote_json(capsys: pytest.CaptureFixture[str], *argv: str) -> dict[str, Any]:
    run(*argv, "--json")
    return json.loads(capsys.readouterr().out)


def board(outline: str, thickness: str = "1.6") -> str:
    Path("board.kicad_pcb").write_text(
        f"(kicad_pcb (general (thickness {thickness}))"
        ' (layers (0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user))'
        f" {outline})\n"
    )
    Path("bom.csv").write_text("C25744\n")
    return "board.kicad_pcb"


def test_quote_prints_the_mainboard_like_the_documented_example(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command, *expected = (ROOT / "docs/example-quote.txt").read_text().split("\n", 1)

    run(*MAINBOARD, "--qty", "5")

    assert command.startswith("$ jlcpick quote MicrasMainBoard-kicad-bom.csv --pcb")
    assert capsys.readouterr().out == expected[0]


def test_quote_asks_jlc_for_the_board_the_site_priced_for_order_10973279a(
    sent: list[dict[str, Any]],
) -> None:
    site = json.loads((FIXTURES / "quote/mainboard_request.json").read_text())["pcbGoodsRequest"]

    run(*MAINBOARD, "--qty", "5")

    [body] = sent
    board_keys = ("stencilLayer", "stencilWidth", "stencilLength", "stencilPly", "stencilCounts")
    assert {key: body["pcbGoodsRequest"][key] for key in board_keys} == {
        key: site[key] for key in board_keys
    }
    assert body["pcbGoodsRequest"]["adornColor"] == "Green"


def test_quote_json_adds_the_boards_to_the_assembly_and_weighs_the_extended_parts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    order = quote_json(capsys, *MAINBOARD, "--qty", "5")

    pcba, extended = order["pcba"], order["extended"]
    assert order["board"] == {
        "width_mm": 50.0,
        "length_mm": 90.0,
        "layers": 4,
        "thickness_mm": 1.0,
        "kicad_thickness_mm": 1.0412,
        "color": "green",
        "usd": 8.0,
        "build_time": "3-4 days",
    }
    assert order["total_usd"] == pytest.approx(8.0 + pcba["total_usd"])
    extra = sum(
        (line["charged"] - line["need"]) * line["unit_usd"]
        for line in pcba["lines"]
        if line["tier"] == "extended"
    )
    assert (extended["feeder_usd"], extended["extra_units_usd"]) == (
        pcba["fees"]["feeder_usd"],
        pytest.approx(extra, abs=0.006),
    )
    assert extended["share_pct"] == pytest.approx(
        100 * extended["usd"] / order["total_usd"], abs=0.05
    )
    assert all(line["swap"] is None for line in pcba["lines"])


def test_quote_standard_counts_no_feeder_fee_against_extended_parts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    order = quote_json(capsys, *MAINBOARD, "--assembly", "standard")

    assert order["pcba"]["fees"]["feeder_usd"] > 0
    assert order["extended"]["feeder_usd"] == 0


def test_quote_exclude_leaves_the_part_out_of_the_assembly(
    capsys: pytest.CaptureFixture[str],
) -> None:
    order = quote_json(capsys, *MAINBOARD, "--exclude", "IC1")

    assert "C5271073" not in [line["lcsc"] for line in order["pcba"]["lines"]]


def test_quote_measures_an_outline_whose_arc_bulges_past_its_ends(
    sent: list[dict[str, Any]],
) -> None:
    outline = (
        '(gr_rect (start 0 0) (end 40 20) (layer "Edge.Cuts"))'
        ' (gr_arc (start 40 0) (mid 50 10) (end 40 20) (layer "Edge.Cuts"))'
        ' (gr_line (start 0 0) (end 99 99) (layer "F.SilkS"))'
    )

    run("quote", "bom.csv", "--pcb", board(outline, thickness="1.5"), "--color", "white")

    pcb = sent[0]["pcbGoodsRequest"]
    assert (pcb["stencilWidth"], pcb["stencilLength"], pcb["stencilLayer"]) == (50.0, 20.0, 2)
    assert (pcb["stencilPly"], pcb["adornColor"]) == ("1.6", "White")


def test_quote_exits_1_on_a_board_without_an_outline() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["quote", "bom.csv", "--pcb", board("")])

    assert exit_info.value.code == ("jlcpick: no board outline: draw it on the Edge.Cuts layer")


def test_quote_exits_1_when_the_calculator_fails(
    monkeypatch: pytest.MonkeyPatch, network: Callable[..., None]
) -> None:
    answer = b'{"success": false, "code": 500, "message": "System error.", "data": null}'
    monkeypatch.setattr("jlcpick.sources.http.urlopen", lambda request, timeout: io.BytesIO(answer))

    with pytest.raises(SystemExit) as exit_info:
        main([*MAINBOARD])

    assert exit_info.value.code == "jlcpick: JLCPCB's board calculator failed: System error."


def test_skill_documents_every_quote_field() -> None:
    skill = (ROOT / "skills/jlcpick/SKILL.md").read_text()
    names = {f.name for kind in (quote.Quote, quote.Board, quote.Extended) for f in fields(kind)}
    assert sorted(name for name in names if f"`{name}`" not in skill) == []
