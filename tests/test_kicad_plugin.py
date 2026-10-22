import sys
import zipfile
from pathlib import Path

import jlcpick_plugin
import pytest
from jlcpick_plugin import add, fab, priced, run
from pack import pack

SHEET = """(kicad_sch
  (symbol (property "Reference" "R1") (property "SUPPLIER PART" "C25744"))
  (symbol (property "Reference" "R2") (property "SUPPLIER PART" "C25744"))
  (symbol (property "Reference" "U1") (property "LCSC PART NUMBER" "C8734")))"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A board whose schematic has most LCSC codes in ``SUPPLIER PART``, one in another field."""
    (tmp_path / "board.kicad_pcb").write_text("(kicad_pcb)")
    (tmp_path / "board.kicad_sch").write_text(SHEET)
    return tmp_path / "board.kicad_pcb"


@pytest.fixture
def bin_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """The folder of the plugin's Python, where jlcpick and KiKit get installed."""
    folder = tmp_path / "bin"
    folder.mkdir()
    monkeypatch.setattr(jlcpick_plugin, "BIN", folder)
    return folder


def test_bom_exports_the_schematic_bom_with_its_lcsc_field(project: Path, bin_dir: Path) -> None:
    steps = priced("bom", project, "/app/bin/kicad-cli", Path("/scratch/bom.csv"), 10)

    assert steps == [
        [
            "/app/bin/kicad-cli", "sch", "export", "bom", str(project.with_suffix(".kicad_sch")),
            "-o", "/scratch/bom.csv", "--ref-range-delimiter", "",
            "--fields", "Reference,Value,Footprint,QUANTITY,DNP,SUPPLIER PART",
            "--labels", "Refs,Value,Footprint,Qty,DNP,LCSC",
            "--group-by", "Value,Footprint,SUPPLIER PART,DNP",
        ],
        [str(bin_dir / "jlcpick"), "bom", "/scratch/bom.csv", "--pcb", str(project), "--qty", "10"],
    ]  # fmt: skip


def test_quote_prices_the_exported_bom_with_the_board(project: Path, bin_dir: Path) -> None:
    steps = priced("quote", project, "kicad-cli", Path("/scratch/bom.csv"), 5)

    assert steps[0][-1] == "Value,Footprint,SUPPLIER PART,DNP"
    assert steps[1] == [
        str(bin_dir / "jlcpick"), "quote", "/scratch/bom.csv", "--pcb", str(project), "--qty", "5"
    ]  # fmt: skip


def test_a_schematic_without_lcsc_codes_exports_lcsc(project: Path, bin_dir: Path) -> None:
    project.with_suffix(".kicad_sch").write_text('(kicad_sch (property "SUPPLIER PART" ""))')

    steps = priced("bom", project, "kicad-cli", Path("bom.csv"), 5)

    assert steps[0][-1] == "Value,Footprint,LCSC,DNP"


def test_add_passes_each_code_typed(bin_dir: Path) -> None:
    steps = add(" C25744, c8734\tC1 ")

    assert steps == [[str(bin_dir / "jlcpick"), "add", "C25744", "c8734", "C1"]]


def test_fab_writes_into_the_project_jlcpcb_folder(project: Path, bin_dir: Path) -> None:
    (bin_dir / "kikit").write_text("")
    (bin_dir / "kikit").chmod(0o755)

    steps = fab(project)

    assert steps == [
        [str(bin_dir / "jlcpick"), "fab", str(project), "--out", str(project.parent / "jlcpcb")]
    ]


def test_fab_installs_the_kikit_jlcpick_pins_when_missing(project: Path, bin_dir: Path) -> None:
    steps = fab(project)

    assert steps[0] == [sys.executable, "-m", "pip", "install", "kikit==1.8.1"]
    assert steps[1][1:3] == ["fab", str(project)]


def test_run_returns_the_last_output(tmp_path: Path) -> None:
    steps = [
        [sys.executable, "-c", "print('exported')"],
        [sys.executable, "-c", "import os, sys; print(os.getcwd()); sys.exit(3)"],
    ]

    assert run(steps, tmp_path, lambda: True) == (3, f"{tmp_path}\n")


def test_run_stops_at_the_first_failure(tmp_path: Path) -> None:
    steps = [
        [sys.executable, "-c", "import sys; sys.exit('jlcpick: no LCSC column')"],
        [sys.executable, "-c", "open('ran', 'w')"],
    ]

    assert run(steps, tmp_path, lambda: True) == (1, "jlcpick: no LCSC column\n")
    assert not (tmp_path / "ran").exists()


def test_run_kills_the_step_when_cancelled(tmp_path: Path) -> None:
    steps = [[sys.executable, "-c", "import time; time.sleep(60)"]]

    code, _ = run(steps, tmp_path, lambda: False)

    assert code != 0


def test_pack_writes_the_layout_kicad_installs(tmp_path: Path) -> None:
    pack(tmp_path / "jlcpick.zip")

    assert sorted(zipfile.ZipFile(tmp_path / "jlcpick.zip").namelist()) == [
        "metadata.json",
        "plugins/add.png",
        "plugins/add_action.py",
        "plugins/bom.png",
        "plugins/bom_action.py",
        "plugins/fab.png",
        "plugins/fab_action.py",
        "plugins/jlcpick_plugin.py",
        "plugins/plugin.json",
        "plugins/quote.png",
        "plugins/quote_action.py",
        "plugins/requirements.txt",
    ]
