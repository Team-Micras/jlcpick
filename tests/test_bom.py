import json
import sys
from collections.abc import Callable
from dataclasses import fields, replace
from pathlib import Path
from typing import Any

import pytest
import xlrd
from conftest import mainboard_schematic, run

from jlcpick import bom
from jlcpick.bom_input import BomLine
from jlcpick.cli import main
from jlcpick.pricing import Fees
from jlcpick.sources import jlc

pytestmark = pytest.mark.usefixtures("network")

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests/fixtures"
MAINBOARD = ["bom", str(FIXTURES / "MicrasMainBoard-kicad-bom.csv")]
PCB = ["--pcb", str(FIXTURES / "MicrasMainBoard.kicad_pcb")]


def bom_json(capsys: pytest.CaptureFixture[str], *argv: str) -> dict[str, Any]:
    run(*argv, "--json")
    return json.loads(capsys.readouterr().out)


def csv(text: str) -> str:
    Path("bom.csv").write_text(text)
    return "bom.csv"


def exit_code(*argv: str) -> int | str | None:
    with pytest.raises(SystemExit) as exit_info:
        main(list(argv))
    return exit_info.value.code


def test_bom_prints_the_mainboard_like_the_documented_example(
    capsys: pytest.CaptureFixture[str],
) -> None:
    command, *expected = (ROOT / "docs/example-bom.txt").read_text().split("\n", 1)

    run(*MAINBOARD, *PCB, "--qty", "5")

    assert command.startswith("$ jlcpick bom MicrasMainBoard-kicad-bom.csv --pcb")
    assert capsys.readouterr().out == expected[0]


def test_bom_exports_a_schematic_with_every_field_that_holds_codes(
    capsys: pytest.CaptureFixture[str], kicad_cli: Path
) -> None:
    _, expected = (ROOT / "docs/example-bom.txt").read_text().split("\n", 1)

    run("bom", mainboard_schematic(), *PCB, "--qty", "5", "--kicad-cli", str(kicad_cli))

    assert capsys.readouterr().out == expected
    args = json.loads((kicad_cli.parent / "args.json").read_text())
    assert args[:5] == [
        "sch",
        "export",
        "bom",
        str(Path("MicrasMainBoard.kicad_sch").resolve()),
        "-o",
    ]
    assert args[6:] == [
        "--ref-range-delimiter", "",
        "--fields", "Reference,Value,Footprint,QUANTITY,DNP,LCSC Part #,SUPPLIER PART",
        "--labels", "Refs,Value,Footprint,Qty,DNP,LCSC Part #,SUPPLIER PART",
        "--group-by", "Value,Footprint,LCSC Part #,SUPPLIER PART,DNP",
    ]  # fmt: skip
    assert sorted(p.name for p in Path().iterdir()) == [
        "MicrasMainBoard.kicad_sch",
        "kicad",
        "power.kicad_sch",
    ]


def test_bom_finds_kicad_cli_on_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], kicad_cli: Path
) -> None:
    monkeypatch.setenv("PATH", str(kicad_cli.parent))

    run("bom", mainboard_schematic(), "--no-swaps")

    assert capsys.readouterr().out.startswith("MicrasMainBoard  ×5  Economic")
    assert (kicad_cli.parent / "args.json").exists()


def test_bom_without_kicad_cli_says_how_to_point_at_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))

    assert exit_code("bom", mainboard_schematic()) == (
        "jlcpick: kicad-cli not found to export the schematic's BOM; install KiCad 10, put "
        "kicad-cli on PATH or pass --kicad-cli"
    )


def test_bom_shows_why_kicad_cli_failed(tmp_path: Path) -> None:
    failing = tmp_path / "kicad-cli"
    failing.write_text(
        f"#!{sys.executable}\nprint('Failed to load schematic')\nraise SystemExit(1)\n"
    )
    failing.chmod(0o755)

    code = exit_code("bom", mainboard_schematic(), "--kicad-cli", str(failing))

    assert code == "jlcpick: kicad-cli failed:\nFailed to load schematic\n"


def test_bom_on_a_schematic_without_lcsc_codes_names_the_fields_it_reads() -> None:
    Path("board.kicad_sch").write_text('(kicad_sch (lib_symbols (property "LCSC" "C1")))\n')

    assert str(exit_code("bom", "board.kicad_sch")).startswith(
        "jlcpick: board.kicad_sch: no symbol field holds LCSC codes"
    )


def test_bom_without_a_board_assumes_one_side_and_warns(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run(*MAINBOARD)

    captured = capsys.readouterr()
    assert "  joints     n/d\n" in captured.out
    assert "jlcpick: no --pcb: joints n/d, THT unknown, one assembled side assumed\n" in (
        captured.err
    )


def test_bom_json_reports_lines_fees_and_warnings(capsys: pytest.CaptureFixture[str]) -> None:
    report = bom_json(capsys, *MAINBOARD, *PCB, "--qty", "2")

    [usb] = [line for line in report["lines"] if line["lcsc"] == "C2988369"]
    assert usb == {
        "lcsc": "C2988369",
        "designators": ["U2"],
        "mpn": "GT-USB-7010ASV",
        "tier": "extended",
        "preferred": False,
        "need": 2,
        "charged": 4,
        "unit_usd": 0.0882,
        "total_usd": 0.35,
        "feeder_fee": True,
        "tht": False,
        "joints": 32,
        "swap": {"verdict": "no_rule", "reason": "no rule for USB Connectors", "to": None},
    }
    assert (report["qty"], report["sides"], report["fees_as_of"]) == (2, 1, "2026-09-09")
    assert report["warnings"] == [
        "EC1, EC2: no LCSC code, left out of the cost",
        "W1, W2, W3, W4: no LCSC code, left out of the cost",
        "C5271073 (IC1): 1 in stock, JLC charges 2; pre-order it or pick another part",
        "C5267399 (IC2): 0 in stock, JLC charges 2; pre-order it or pick another part",
        "C20033901 (IC6): 0 in stock, JLC charges 2; pre-order it or pick another part",
        "C2938919 (L2): 0 in stock, JLC charges 2; pre-order it or pick another part",
    ]


def test_bom_exclude_drops_a_unique_extended_part_and_its_fee(
    capsys: pytest.CaptureFixture[str],
) -> None:
    full = bom_json(capsys, *MAINBOARD, *PCB)
    without_mcu = bom_json(capsys, *MAINBOARD, *PCB, "--exclude", "IC1")

    [mcu] = [line for line in full["lines"] if line["lcsc"] == "C5271073"]
    assert "C5271073" not in [line["lcsc"] for line in without_mcu["lines"]]
    assert len(full["fees"]["feeder_parts"]) - len(without_mcu["fees"]["feeder_parts"]) == 1
    assert full["fees"]["smt_joints"] - without_mcu["fees"]["smt_joints"] == 69 * 5
    assert full["total_usd"] - without_mcu["total_usd"] == pytest.approx(
        mcu["total_usd"] + 3.07 + round(69 * 5 * 0.0016, 2), abs=0.011
    )


def test_bom_exclude_keeps_the_fee_while_another_designator_uses_the_part(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = bom_json(capsys, *MAINBOARD, "--exclude", "IC3")

    [line] = [line for line in report["lines"] if line["lcsc"] == "C27345609"]
    assert (line["designators"], line["need"], line["feeder_fee"]) == (["IC4"], 5, True)


def test_bom_leaves_out_dnp_lines(capsys: pytest.CaptureFixture[str]) -> None:
    path = csv('"Refs","Qty","DNP","LCSC"\n"R1,R2","2","","C25744"\n"U1","1","DNP","C8734"\n')

    report = bom_json(capsys, "bom", path, "--qty", "1")

    assert [(line["lcsc"], line["need"]) for line in report["lines"]] == [("C25744", 2)]


def test_bom_keeps_a_line_whose_dnp_cell_says_no(capsys: pytest.CaptureFixture[str]) -> None:
    path = csv('"Refs","Qty","DNP","LCSC"\n"R1","1","No","C25744"\n"R2","1","Yes","C25796"\n')

    report = bom_json(capsys, "bom", path, "--qty", "1")

    assert [line["lcsc"] for line in report["lines"]] == ["C25744"]


def test_bom_reads_an_altium_bom_with_a_supplier_part_column(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = bom_json(capsys, "bom", str(FIXTURES / "MicrasMainBoard-BOM.csv"))

    [usb] = [line for line in report["lines"] if line["lcsc"] == "C2988369"]
    assert (usb["designators"], usb["need"]) == (["U2"], 5)


@pytest.mark.parametrize("text", ["C25744\nC25744\nC25796\n", "LCSC\nC25744\nc25744\nC25796\n"])
def test_bom_reads_a_list_of_codes_as_one_use_per_row(
    capsys: pytest.CaptureFixture[str], text: str
) -> None:
    report = bom_json(capsys, "bom", csv(text), "--qty", "10")

    assert [(line["lcsc"], line["need"], line["charged"]) for line in report["lines"]] == [
        ("C25796", 10, 20),
        ("C25744", 20, 20),
    ]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("Refs,Value\nR1,10k\n", "the BOM has no LCSC column; name one of: lcsc, lcsc part,"),
        ("Value,LCSC\n10k,C25744\n", "the BOM has no designator column, such as Refs"),
        ("Refs,LCSC\nR1,25744\n", "row 2: '25744' is not an LCSC code like C25744"),
        ("C25744\nC999999999\n", "C999999999: JLCPCB has no part with this code"),
        ("Refs,Qty,LCSC\nC5-C8,4,C25744\n", "row 2: Qty 4 but 1 designators; ranges like C5-C8"),
    ],
)
def test_bom_exits_1_on_a_bad_bom(text: str, message: str) -> None:
    code = exit_code("bom", csv(text))

    assert str(code).startswith(f"jlcpick: {message}")


def test_bom_exits_1_on_a_part_without_a_price(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = json.loads((FIXTURES / "parts/C25744_jlc.json").read_text())
    for item in answer["data"]["componentPageInfo"]["list"]:
        item["componentPrices"] = []
    monkeypatch.setattr("jlcpick.sources.jlc.fetch_json", lambda url, body=None: answer)

    assert exit_code("bom", csv("C25744\n")) == "jlcpick: C25744: no price"


def test_bom_exclude_accumulates_when_repeated(capsys: pytest.CaptureFixture[str]) -> None:
    path = csv("Refs,LCSC\nR1,C25744\nR2,C25796\nR3,C25783\n")

    report = bom_json(capsys, "bom", path, "--exclude", "R1", "--exclude", "R2")

    assert [line["lcsc"] for line in report["lines"]] == ["C25783"]


def test_bom_exits_1_on_an_unknown_excluded_designator() -> None:
    code = exit_code(*MAINBOARD, "--exclude", "IC1,U99,X1")

    assert code == "jlcpick: --exclude: not in the BOM: U99, X1"


def test_bom_exits_1_on_a_bom_that_is_not_utf8() -> None:
    Path("bom.csv").write_bytes(b"Refs,LCSC,Value\nR1,C25744,10k\xb5\n")

    assert exit_code("bom", "bom.csv") == (
        "jlcpick: bom.csv: not UTF-8 text; save it as UTF-8 and try again"
    )


def test_bom_exits_1_when_the_board_is_not_a_kicad_board() -> None:
    Path("board.kicad_pcb").write_text("(kicad_sch)")

    assert exit_code(*MAINBOARD, "--pcb", "board.kicad_pcb") == "jlcpick: not a KiCad board file"


@pytest.mark.parametrize("argv", [["--qty", "0"], ["--assembly", "turbo"]])
def test_bom_exits_2_on_invalid_usage(argv: list[str]) -> None:
    assert exit_code(*MAINBOARD, *argv) == 2


def test_bom_fail_on_extended_exits_3_after_the_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = exit_code("bom", csv("C25744\nC27345609\n"), "--fail-on-extended")

    captured = capsys.readouterr()
    assert code == 3
    assert captured.out.startswith("bom  ×5  Economic")
    assert captured.err.endswith("jlcpick: extended parts paying the feeder fee: C27345609\n")


def test_bom_fail_on_extended_passes_basic_and_preferred_parts_in_economic() -> None:
    run("bom", csv("C25744\nC7420318\n"), "--fail-on-extended")


def test_bom_fail_on_extended_fails_on_a_preferred_part_in_standard(
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = csv("C25744\nC7420318\n")

    code = exit_code("bom", path, "--assembly", "standard", "--fail-on-extended")

    assert code == 3
    assert capsys.readouterr().err.endswith("paying the feeder fee: C7420318\n")


def test_bom_standard_lists_the_fees_it_does_not_include(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run("bom", csv("C25744\n"), "--assembly", "standard")

    assert "  not included: packing, fixture and the per-board batch fee" in capsys.readouterr().out


def test_bom_x_ray_charges_leadless_packages(capsys: pytest.CaptureFixture[str]) -> None:
    report = bom_json(capsys, "bom", csv("Refs,LCSC\nIC1,C5271073\nC1,C25744\n"), "--qty", "5")

    assert (report["fees"]["xray_units"], report["fees"]["xray_usd"]) == (5, 8.2)


def test_bom_text_names_x_ray_apart_from_the_total_only_when_there_is_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run("bom", csv("Refs,LCSC\nC1,C25744\n"), "--no-swaps")
    without = capsys.readouterr().out
    run("bom", csv("Refs,LCSC\nIC1,C5271073\n"), "--no-swaps")
    out, err = capsys.readouterr()
    report = bom_json(capsys, "bom", csv("Refs,LCSC\nIC1,C5271073\n"), "--no-swaps")

    assert "x-ray" not in without
    assert "  x-ray      if JLC requires it: +US$ 8.20   5 leadless × 1.64" in out
    assert "x-ray" not in out.split("\n")[3]
    assert report["fees"]["xray_usd"] == 8.2
    assert report["total_usd"] == round(report["parts_usd"] + 8.18 + 1.53 + 3.07, 2)
    assert "C5271073 (IC1): 1 in stock, JLC charges 5; pre-order it or pick another part" in err


def test_bom_standard_on_a_board_with_a_bottom_part_pays_two_sides(
    capsys: pytest.CaptureFixture[str],
) -> None:
    Path("board.kicad_pcb").write_text(
        "(kicad_pcb\n"
        ' (footprint "R" (layer "F.Cu") (property "Reference" "R1") (pad "1" smd) (pad "2" smd))\n'
        ' (footprint "R" (layer "B.Cu") (property "Reference" "R2") (attr smd)'
        ' (pad "1" smd) (pad "2" smd) (pad "" np_thru_hole))\n'
        ' (footprint "J" (layer "F.Cu") (property "Reference" "J1") (attr through_hole)'
        ' (pad "1" thru_hole) (pad "2" thru_hole) (pad "MP" np_thru_hole))\n'
        ")\n"
    )
    path = csv("Refs,LCSC\nR1,C25744\nR2,C25744\nJ1,C158050\n")

    run("bom", path, "--pcb", "board.kicad_pcb", "--qty", "1", "--assembly", "standard")

    assert "  fees       setup 2 × 25.56 = 51.12 · stencil 2 × 8.21 = 16.42 · feeders 2" in (
        capsys.readouterr().out
    )
    report = bom_json(capsys, "bom", path, "--pcb", "board.kicad_pcb", "--qty", "1")
    assert (report["fees"]["smt_joints"], report["fees"]["manual_joints"]) == (4, 2)


def test_bom_reads_the_designators_of_a_kicad_7_board(capsys: pytest.CaptureFixture[str]) -> None:
    Path("board.kicad_pcb").write_text(
        "(kicad_pcb (version 20221018)\n"
        ' (footprint "R" (layer "F.Cu") (fp_text reference "R1" (at 0 0))'
        ' (pad "1" smd) (pad "2" smd))\n'
        ' (footprint "J" (layer "F.Cu") (fp_text reference "J1" (at 0 0)) (attr through_hole)'
        ' (pad "1" thru_hole) (pad "2" thru_hole))\n'
        ")\n"
    )
    path = csv("Refs,LCSC\nR1,C25744\nJ1,C158050\n")

    report = bom_json(capsys, "bom", path, "--pcb", "board.kicad_pcb", "--qty", "1")

    assert (report["fees"]["smt_joints"], report["fees"]["manual_joints"]) == (2, 2)


def order_lines() -> list[tuple[str, str, int, float]]:
    sheet = xlrd.open_workbook(FIXTURES / "10973279A_bom.xls").sheet_by_index(0)
    return [
        (code, designators, int(qty), float(usd))
        for _, designators, _, code, qty, usd in map(sheet.row_values, range(1, sheet.nrows))
    ]


SUSPECT_LOSS = {
    "C2988369": "charged 2 on 2026-10-08; lossNumber of 2026-10-21 makes it 4",
    "C7420318": "charged 16 on 2026-10-08; lossNumber of 2026-10-21 makes it 20",
}


@pytest.mark.parametrize(
    ("code", "designators", "qty", "usd"),
    [
        pytest.param(*line, marks=pytest.mark.xfail(reason=SUSPECT_LOSS[line[0]], strict=True))
        if line[0] in SUSPECT_LOSS
        else line
        for line in order_lines()
    ],
    ids=lambda value: value if isinstance(value, str) and value.startswith("C") else "",
)
def test_bom_charges_order_10973279a_like_jlc(
    code: str, designators: str, qty: int, usd: float, network: Callable[..., None]
) -> None:
    part = replace(jlc.part(code), prices=(jlc.PriceBreak(1, usd / qty),))
    line = BomLine(tuple(designators.split(",")), code, False)

    [priced] = bom.report("10973279A", [line], {code: part}, 2, "economic", None, None).lines

    assert priced.charged == qty


def test_skill_documents_every_bom_report_field() -> None:
    skill = (ROOT / "skills/jlcpick/SKILL.md").read_text()
    names = {
        f.name
        for kind in (bom.Report, bom.Line, bom.Swap, bom.Replacement, Fees)
        for f in fields(kind)
    }
    assert sorted(name for name in names if f"`{name}`" not in skill) == []
