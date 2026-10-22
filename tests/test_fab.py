import csv
import io
import json
import os
import shutil
import statistics
import sys
import zipfile
from pathlib import Path

import pytest
import xlrd
from conftest import run

from jlcpick import bom_input
from jlcpick.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
RECORDED = FIXTURES / "kikit"
LEFT_OUT_OF_10973279A = "IC1,IC2,IC3,IC4,IC5,IC6,IC7,J1,M1,M2,M3,P1,R32,R33"
SWAPPED_AFTER_10973279A = {
    "C22": "C5137554 in the order, then the schematic took C1549, the basic 18 pF C0G swap",
    "C23": "C5137554 in the order, then the schematic took C1549, the basic 18 pF C0G swap",
}
CENTERED_BY_ALTIUM = {
    "Q3": "Altium centers the pads' box on the board's axes: for this SOT-23 turned 225°, 0.47 mm"
    " from the part's center, which KiKit places",
    "Q4": "the same as Q3, turned 315°",
}
FAKE_KIKIT = """#!{python}
import json, os, shutil, sys, zipfile
from pathlib import Path

args = sys.argv[1:]
out = Path(args[-1])
patterns = args[args.index("--correctionpatterns") + 1] if "--correctionpatterns" in args else None
Path(os.environ["KIKIT_SEEN"]).write_text(
    json.dumps({{"args": args, "corrections": patterns and Path(patterns).read_text()}})
)
recorded = Path(os.environ["KIKIT_RECORDED"])
shutil.copy(recorded / "bom.csv", out / "bom.csv")
shutil.copy(recorded / "pos.csv", out / "pos.csv")
zipfile.ZipFile(out / "gerbers.zip", "w").close()
"""


@pytest.fixture
def kikit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Put a fake ``kikit`` on PATH that writes the files in ``KIKIT_RECORDED``; return the file
    where it records what it was called with."""
    monkeypatch.chdir(tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "kikit"
    fake.write_text(FAKE_KIKIT.format(python=sys.executable))
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("KICAD10_FOOTPRINT_DIR", str(FIXTURES / "kicad/footprints"))
    monkeypatch.setenv("KIKIT_SEEN", str(tmp_path / "seen.json"))
    recorded = tmp_path / "recorded"
    recorded.mkdir()
    shutil.copy(RECORDED / "MicrasMainBoard-bom.csv", recorded / "bom.csv")
    shutil.copy(RECORDED / "MicrasMainBoard-pos.csv", recorded / "pos.csv")
    monkeypatch.setenv("KIKIT_RECORDED", str(recorded))
    return tmp_path / "seen.json"


def mainboard() -> str:
    shutil.copy(FIXTURES / "MicrasMainBoard.kicad_pcb", "MicrasMainBoard.kicad_pcb")
    Path("MicrasMainBoard.kicad_sch").write_text('(property "SUPPLIER PART" "C307331")\n')
    return "MicrasMainBoard.kicad_pcb"


def board(*footprints: tuple[str, str]) -> str:
    Path("board.kicad_pcb").write_text(
        "(kicad_pcb\n"
        + "".join(
            f' (footprint "{name}" (layer "F.Cu") (property "Reference" "{reference}")'
            ' (pad "1" smd) (pad "2" smd))\n'
            for reference, name in footprints
        )
        + ")\n"
    )
    Path("board.kicad_sch").write_text('(property "LCSC" "C1")\n')
    return "board.kicad_pcb"


def record(bom: str, pos: str) -> None:
    Path("recorded/bom.csv").write_text(bom)
    Path("recorded/pos.csv").write_text(pos)


def rows(path: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(Path(path).read_text())))


def assert_matches_order_10973279a(out: Path) -> None:
    """The BOM and CPL ``out`` holds place what order 10973279A placed, where it placed it."""
    sheet = xlrd.open_workbook(FIXTURES / "10973279A_bom.xls").sheet_by_index(0)
    ordered = {
        d: row[3] for row in map(sheet.row_values, range(1, sheet.nrows)) for d in row[1].split(",")
    }
    listed = {d: r["LCSC"] for r in rows(str(out / "bom.csv")) for d in r["Designator"].split(",")}
    assert {d for d in ordered if listed.get(d) != ordered[d]} == set(SWAPPED_AFTER_10973279A)
    assert listed.keys() == ordered.keys()
    text = (FIXTURES / "10973279A_cpl.csv").read_text(encoding="utf-8-sig")
    accepted = {r["Designator"]: r for r in csv.DictReader(io.StringIO(text[text.index('"Des') :]))}
    placed = {r["Designator"]: r for r in rows(str(out / "pos.csv"))}
    assert placed.keys() == ordered.keys()
    assert {d: float(r["Rotation"]) for d, r in placed.items()} == {
        d: float(accepted[d]["Rotation"]) for d in placed
    }
    dx, dy = (
        statistics.median(float(placed[d][ours]) - float(accepted[d][theirs]) for d in placed)
        for ours, theirs in (("Mid X", "Center-X(mm)"), ("Mid Y", "Center-Y(mm)"))
    )
    off = {
        d
        for d, r in placed.items()
        if abs(float(r["Mid X"]) - dx - float(accepted[d]["Center-X(mm)"])) > 0.05
        or abs(float(r["Mid Y"]) - dy - float(accepted[d]["Center-Y(mm)"])) > 0.05
    }
    assert off == set(CENTERED_BY_ALTIUM)


def test_fab_places_what_order_10973279a_placed(
    kikit: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run("fab", mainboard(), "--exclude", LEFT_OUT_OF_10973279A)

    assert_matches_order_10973279a(Path("jlcpcb"))
    assert capsys.readouterr().err == "jlcpick: no LCSC code, left out: EC1, EC2, W1, W2, W3, W4\n"
    seen = json.loads(kikit.read_text())
    assert seen["args"][:8] == [
        "fab",
        "jlcpcb",
        "--no-drc",
        "--assembly",
        "--schematic",
        "MicrasMainBoard.kicad_sch",
        "--field",
        "SUPPLIER PART",
    ]
    assert seen["corrections"] is None
    assert zipfile.is_zipfile("jlcpcb/gerbers.zip")


def test_fab_corrects_the_rotation_of_kicad_stock_footprints_only(kikit: Path) -> None:
    record("Designator,LCSC\nQ1,C1\nQ2,C1\nR1,C1\n", "Designator,Rotation\nQ1,0\nQ2,0\nR1,0\n")

    run(
        "fab",
        board(
            ("Q1", "Package_TO_SOT_SMD:SOT-23"),
            ("Q2", "MicrasLib:SOT-23-3_L2.9-W1.3-P1.90-LS2.4-BR"),
            ("R1", "Resistor_SMD:R_0402_1005Metric"),
        ),
    )

    assert json.loads(kikit.read_text())["corrections"].splitlines() == [
        '"Pattern","Part","X","Y","Rotation"',
        r'"^Package_TO_SOT_SMD:SOT\-23$",".*","0","0","-90"',
        r'"^Resistor_SMD:R_0402_1005Metric$",".*","0","0","0"',
    ]


@pytest.mark.usefixtures("kikit")
def test_fab_exits_3_on_a_kicad_footprint_whose_rotation_nobody_checked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    record("Designator,LCSC\nD1,C1\nD2,C1\n", "Designator,Rotation\nD1,0\nD2,0\n")

    with pytest.raises(SystemExit) as exit_info:
        main(["fab", board(("D1", "LED_SMD:LED_0603_1608Metric"), ("D2", "MicrasLib:LED0603"))])

    assert exit_info.value.code == 3
    assert capsys.readouterr().err == (
        "jlcpick: no checked rotation for KiCad's footprint, check it in JLC's preview: "
        "D1 (LED_SMD:LED_0603_1608Metric)\n"
    )
    assert Path("jlcpcb/pos.csv").read_text().splitlines() == [
        "Designator,Rotation",
        "D1,0",
        "D2,0",
    ]


@pytest.fixture
def libraries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """KiCad's footprint libraries named in the tests below, all empty."""
    for nickname in ("Connector_USB", "Connector_PinHeader_1.27mm", "Connector_PinHeader_2.54mm"):
        (tmp_path / "libraries" / f"{nickname}.pretty").mkdir(parents=True)
    monkeypatch.setenv("KICAD10_FOOTPRINT_DIR", str(tmp_path / "libraries"))


@pytest.mark.usefixtures("kikit", "libraries")
def test_fab_leaves_footprints_whose_original_offset_was_in_the_boards_axes_unchecked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    record("Designator,LCSC\nJ1,C1\nJ2,C1\n", "Designator,Rotation\nJ1,0\nJ2,0\n")

    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "fab",
                board(
                    ("J1", "Connector_USB:USB_C_Receptacle_XKB_U262-16XN-4BVC11"),
                    ("J2", "Connector_PinHeader_1.27mm:PinHeader_2x05_P1.27mm_Vertical"),
                ),
            ]
        )

    assert exit_info.value.code == 3
    assert json.loads(Path("seen.json").read_text())["corrections"] is None
    assert capsys.readouterr().err == (
        "jlcpick: no checked rotation for KiCad's footprint, check it in JLC's preview: "
        "J1 (Connector_USB:USB_C_Receptacle_XKB_U262-16XN-4BVC11), "
        "J2 (Connector_PinHeader_1.27mm:PinHeader_2x05_P1.27mm_Vertical)\n"
    )


@pytest.mark.usefixtures("kikit", "libraries")
def test_fab_exits_3_on_a_kicad_through_hole_footprint_that_is_placed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    record("Designator,LCSC\nJ1,C1\n", "Designator,Rotation\nJ1,0\n")
    Path("board.kicad_pcb").write_text(
        '(kicad_pcb (footprint "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"'
        ' (layer "F.Cu") (property "Reference" "J1") (attr through_hole)'
        ' (pad "1" thru_hole) (pad "2" thru_hole)))\n'
    )
    Path("board.kicad_sch").write_text('(property "LCSC" "C1")\n')

    with pytest.raises(SystemExit) as exit_info:
        main(["fab", "board.kicad_pcb"])

    assert exit_info.value.code == 3
    assert capsys.readouterr().err == (
        "jlcpick: KiCad's through-hole footprint is placed by its pin 1, check its position in "
        "JLC's preview: J1 (Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical)\n"
    )


@pytest.mark.usefixtures("kikit")
def test_fab_reads_the_designators_of_a_kicad_7_board(capsys: pytest.CaptureFixture[str]) -> None:
    record("Designator,LCSC\nQ1,C1\n", "Designator,Rotation\nQ1,0\n")
    Path("board.kicad_pcb").write_text(
        '(kicad_pcb (version 20221018) (footprint "Package_TO_SOT_SMD:SOT-23" (layer "F.Cu")'
        ' (fp_text reference "Q1" (at 0 0)) (pad "1" smd) (pad "2" smd) (pad "3" smd)))\n'
    )
    Path("board.kicad_sch").write_text('(property "LCSC" "C1")\n')

    run("fab", "board.kicad_pcb")

    assert '"-90"' in json.loads(Path("seen.json").read_text())["corrections"]
    assert Path("jlcpcb/bom.csv").read_text().splitlines() == ["Designator,LCSC", "Q1,C1"]


@pytest.mark.usefixtures("kikit")
def test_fab_writes_nothing_when_kikit_lists_a_part_the_board_lacks() -> None:
    record('Designator,LCSC\n"R1,R2",C1\n', "Designator,Rotation\nR1,0\nR2,0\n")

    with pytest.raises(SystemExit) as exit_info:
        main(["fab", board(("R1", "MicrasLib:R0402"))])

    assert str(exit_info.value.code) == "jlcpick: KiKit's BOM lists R2, not found on the board"
    assert not Path("jlcpcb/gerbers.zip").exists()
    assert not Path("jlcpcb/bom.csv").exists()


@pytest.mark.usefixtures("kikit")
def test_fab_accepts_excluding_a_part_that_is_do_not_place() -> None:
    record(
        "Designator,LCSC,DNP\nR1,C1,\nR2,C1,Yes\n",
        "Designator,Rotation\nR1,0\n",
    )

    run("fab", board(("R1", "MicrasLib:R0402"), ("R2", "MicrasLib:R0402")), "--exclude", "R2")

    assert Path("jlcpcb/bom.csv").read_text().splitlines() == ["Designator,LCSC,DNP", "R1,C1,"]


@pytest.mark.usefixtures("kikit")
def test_fab_rejects_excluding_a_part_that_is_not_on_the_board() -> None:
    record("Designator,LCSC\nR1,C1\n", "Designator,Rotation\nR1,0\n")

    with pytest.raises(SystemExit) as exit_info:
        main(["fab", board(("R1", "MicrasLib:R0402")), "--exclude", "R9"])

    assert str(exit_info.value.code) == "jlcpick: --exclude: not on the board: R9"


@pytest.mark.usefixtures("kikit")
def test_fab_prefers_the_kikit_next_to_the_python_that_runs_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record("Designator,LCSC\nR1,C1\n", "Designator,Rotation\nR1,0\n")
    beside = Path("venv/bin")
    beside.mkdir(parents=True)
    (beside / "kikit").write_text(
        f"#!{sys.executable}\nprint('from beside')\nraise SystemExit(1)\n"
    )
    (beside / "kikit").chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(beside / "python"))

    with pytest.raises(SystemExit) as exit_info:
        main(["fab", board(("R1", "MicrasLib:R0402"))])

    assert "from beside" in str(exit_info.value.code)


@pytest.mark.usefixtures("kikit")
def test_fab_leaves_parts_without_a_code_and_excluded_ones_out_of_bom_and_cpl() -> None:
    record(
        'Comment,Designator,Footprint,LCSC\n10k,"R1,R2,R3",R0402,C25744\nlogo,G1,Logo,\n',
        "Designator,Mid X,Mid Y,Layer,Rotation\nG1,0,0,T,0\nR1,1,0,T,0\nR2,2,0,T,0\nR3,3,0,T,0\n",
    )

    run(
        "fab", board(*((r, "MicrasLib:R0402") for r in ("G1", "R1", "R2", "R3"))), "--exclude", "R2"
    )

    assert Path("jlcpcb/bom.csv").read_text().splitlines() == [
        "Comment,Designator,Footprint,LCSC",
        '10k,"R1,R3",R0402,C25744',
    ]
    assert Path("jlcpcb/pos.csv").read_text().splitlines() == [
        "Designator,Mid X,Mid Y,Layer,Rotation",
        "R1,1,0,T,0",
        "R3,3,0,T,0",
    ]


@pytest.mark.usefixtures("kikit")
def test_fab_without_kikit_says_how_to_get_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(sys, "executable", "/nowhere/python")

    with pytest.raises(SystemExit) as exit_info:
        main(["fab", board(("R1", "MicrasLib:R0402"))])

    assert "install jlcpick[fab] in a Python that imports pcbnew" in str(exit_info.value.code)


@pytest.mark.usefixtures("kikit")
def test_fab_with_kikit_but_no_pcbnew_says_how_to_get_it() -> None:
    Path("bin/kikit").write_text(
        f"#!{sys.executable}\nraise ModuleNotFoundError(\"No module named 'pcbnew'\")\n"
    )

    with pytest.raises(SystemExit) as exit_info:
        main(["fab", board(("R1", "MicrasLib:R0402"))])

    assert "run fab in the kicad/kicad:10.0.7 Docker image" in str(exit_info.value.code)
    assert not Path("jlcpcb/bom.csv").exists()


def test_fab_reads_codes_typed_in_lowercase_and_not_the_library_symbols_fields(kikit: Path) -> None:
    record("Designator,LCSC\nR1,C25744\n", "Designator,Rotation\nR1,0\n")
    path = board(("R1", "MicrasLib:R0402"))
    Path("board.kicad_sch").write_text(
        '(kicad_sch (lib_symbols (symbol "Device:R" (property "LCSC" "C25744")))\n'
        '  (symbol (lib_id "Device:R") (property "LCSC Part #" " c25744 ")))\n'
    )

    run("fab", path)

    args = json.loads(kikit.read_text())["args"]
    assert args[args.index("--field") + 1] == "LCSC Part #"


def test_fab_and_bom_take_the_same_code_from_a_symbol_with_two_lcsc_fields(kikit: Path) -> None:
    record("Designator,LCSC\nR1,C25744\n", "Designator,Rotation\nR1,0\n")
    path = board(("R1", "MicrasLib:R0402"))
    Path("board.kicad_sch").write_text(
        '(kicad_sch (symbol (property "JLCPCB Part #" "C307331") (property "LCSC" "C25744")))\n'
    )

    run("fab", path)

    args = json.loads(kikit.read_text())["args"]
    assert args[args.index("--field") + 1] == "LCSC,JLCPCB Part #"
    [line] = bom_input.read("Refs,JLCPCB Part #,LCSC\nR1,C307331,C25744\n")
    assert line.lcsc == "C25744"


@pytest.mark.usefixtures("kikit")
def test_fab_names_the_fields_it_reads_the_code_from_when_the_schematic_has_none() -> None:
    path = board(("R1", "MicrasLib:R0402"))
    Path("board.kicad_sch").write_text('(property "MPN" "RC0402")\n')

    with pytest.raises(SystemExit) as exit_info:
        main(["fab", path])

    assert str(exit_info.value.code) == (
        "jlcpick: board.kicad_sch: no symbol field holds LCSC codes; name it one of: lcsc, "
        "lcsc part, lcsc part #, lcsc part number, jlcpcb part #, supplier part"
    )


@pytest.mark.kicad
def test_fab_with_kikit_on_the_mainboard_matches_order_10973279a(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    folder = os.environ.get("JLCPICK_MAINBOARD")
    assert folder, "set JLCPICK_MAINBOARD to a folder with MicrasMainBoard.kicad_pcb and its sheets"
    monkeypatch.chdir(tmp_path)

    run("fab", f"{folder}/MicrasMainBoard.kicad_pcb", "--exclude", LEFT_OUT_OF_10973279A)

    assert_matches_order_10973279a(tmp_path / "jlcpcb")
    with zipfile.ZipFile(tmp_path / "jlcpcb/gerbers.zip") as gerbers:
        job = json.loads(gerbers.read("gerber/MicrasMainBoard.gbrjob"))
        layers = [f"gerber/{f['Path']}" for f in job["FilesAttributes"]]
        assert job["GeneralSpecs"]["LayerNumber"] == 4
        assert [p for p in layers if not gerbers.read(p).rstrip().endswith(b"M02*")] == []
        assert {"gerber/MicrasMainBoard-PTH.drl", "gerber/MicrasMainBoard-NPTH.drl"} <= set(
            gerbers.namelist()
        )
