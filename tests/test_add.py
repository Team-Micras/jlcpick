import json
import re
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path

import pytest
from conftest import run

from jlcpick import library
from jlcpick.cli import main

KICAD = Path(__file__).parent / "fixtures" / "kicad"
ROOT = Path(__file__).parents[1]
LIBRARY = Path("lib/board.kicad_sym")
R_10K = "Resistor 10kΩ 0402 - 0402WGF1002TCE"


@pytest.fixture(autouse=True)
def project(network: Callable[..., None], monkeypatch: pytest.MonkeyPatch) -> None:
    """A KiCad project folder, with KiCad 10.0.7's own libraries installed."""
    monkeypatch.setenv("KICAD10_SYMBOL_DIR", str(KICAD / "symbols"))
    monkeypatch.setenv("KICAD10_FOOTPRINT_DIR", str(KICAD / "footprints"))
    Path("board.kicad_pro").write_text("{}")


def properties(symbol: str) -> list[tuple[str, str]]:
    return re.findall(r'\(property "([^"]*)" "([^"]*)"', symbol)


def test_add_derives_a_resistor_from_kicads_own_symbol(capsys: pytest.CaptureFixture[str]):
    run("add", "C25744")

    symbols = library.symbols(LIBRARY.read_text())
    kicad = library.symbols((KICAD / "symbols/Device.kicad_sym").read_text())
    assert list(symbols) == ["R", R_10K]
    assert symbols["R"] == kicad["R"]
    assert '\n\t\t(extends "R")\n' in symbols[R_10K]
    assert properties(symbols[R_10K]) == [
        ("Reference", "R"),
        ("Value", "10kΩ"),
        ("Footprint", "Resistor_SMD:R_0402_1005Metric"),
        (
            "Datasheet",
            "https://www.lcsc.com/datasheet/lcsc_datasheet_2411221126_UNI-ROYAL-Uniroyal-Elec-"
            "0402WGF1002TCE_C25744.pdf",
        ),
        (
            "Description",
            "-55℃~+155℃ 10kΩ 50V 62.5mW Thick Film Resistor ±1% ±100ppm/℃ 0402 Chip Resistor - "
            "Surface Mount ROHS",
        ),
        ("MPN", "0402WGF1002TCE"),
        ("Manufacturer", "UNI-ROYAL(Uniroyal Elec)"),
        ("LCSC", "C25744"),
        ("ki_keywords", "R res resistor"),
        ("ki_fp_filters", "R_*"),
    ]
    assert Path("sym-lib-table").read_text() == (
        "(sym_lib_table\n\t(version 7)\n"
        '\t(lib (name "board") (type "KiCad") (uri "${KIPRJMOD}/lib/board.kicad_sym") '
        '(options "") (descr ""))\n)\n'
    )
    assert capsys.readouterr().out == (
        f"C25744     added     {R_10K} · Resistor_SMD:R_0402_1005Metric\n"
    )


def test_add_names_each_kind_of_part_and_extends_each_base_once() -> None:
    run("add", "C25744", "C307331", "C25741", "C2286", "C7420318", "C42441131", "C22383774")

    symbols = library.symbols(LIBRARY.read_text())
    assert list(symbols) == [
        "R",
        R_10K,
        "C",
        "Capacitor 100nF 0402 - CL05B104KB54PNC",
        "Resistor 100kΩ 0402 - 0402WGF1003TCE",
        "LED",
        "LED Red 0603 - KT-0603R",
        "D",
        "Diode SOD-123 - 1N4148W",
        "Polyfuse",
        "Fuse Resettable 100mA 0402 - KASML010",
        "C_Polarized",
        "Capacitor Polarised 220uF SMD,D6.3xL5.4mm - VT1C221M0605",
    ]
    assert ("Value", "1N4148W") in properties(symbols["Diode SOD-123 - 1N4148W"])
    assert ("Footprint", "Capacitor_SMD:CP_Elec_6.3x5.4") in properties(symbols[list(symbols)[-1]])


def test_add_again_changes_no_byte(capsys: pytest.CaptureFixture[str]) -> None:
    run("add", "C25744", "C307331")
    first = LIBRARY.read_bytes(), Path("sym-lib-table").read_bytes()
    capsys.readouterr()

    run("add", "C307331", "C25744")

    assert (LIBRARY.read_bytes(), Path("sym-lib-table").read_bytes()) == first
    assert [line.split()[:2] for line in capsys.readouterr().out.splitlines()] == [
        ["C307331", "unchanged"],
        ["C25744", "unchanged"],
    ]


def test_add_keeps_a_different_symbol_of_the_same_name_without_force(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run("add", "C25744")
    edited = LIBRARY.read_text().replace('"MPN" "0402WGF1002TCE"', '"MPN" "edited"')
    LIBRARY.write_text(edited)
    capsys.readouterr()

    run("add", "C25744", "--json")

    assert LIBRARY.read_text() == edited
    captured = capsys.readouterr()
    assert json.loads(captured.out)[0]["status"] == "kept"
    assert captured.err == (
        f'jlcpick: C25744: lib/board.kicad_sym already has a different "{R_10K}", kept; '
        "--force replaces it\n"
    )


def test_add_force_replaces_only_that_symbol(capsys: pytest.CaptureFixture[str]) -> None:
    run("add", "C25744", "C307331")
    pristine = LIBRARY.read_text()
    LIBRARY.write_text(pristine.replace('"MPN" "0402WGF1002TCE"', '"MPN" "edited"'))
    capsys.readouterr()

    run("add", "C25744", "--force", "--json")

    assert LIBRARY.read_text() == pristine
    assert json.loads(capsys.readouterr().out) == [
        {
            "lcsc": "C25744",
            "symbol": R_10K,
            "footprint": "Resistor_SMD:R_0402_1005Metric",
            "status": "replaced",
        }
    ]


def test_add_keeps_what_the_library_and_table_already_have() -> None:
    kicad = (KICAD / "symbols/Device.kicad_sym").read_text()
    LIBRARY.parent.mkdir()
    LIBRARY.write_text(kicad)
    table = '(sym_lib_table\n\t(version 7)\n\t(lib (name "other") (type "KiCad") (uri "x"))\n)\n'
    Path("sym-lib-table").write_text(table)

    run("add", "C25744", "--lib", "lib")

    symbols = library.symbols(LIBRARY.read_text())
    assert list(symbols) == [*library.symbols(kicad), R_10K]
    assert LIBRARY.read_text().startswith(kicad[: kicad.rindex(")")])
    assert Path("sym-lib-table").read_text() == table.replace(
        "\n)\n",
        '\n\t(lib (name "board") (type "KiCad") (uri "${KIPRJMOD}/lib/board.kicad_sym") '
        '(options "") (descr ""))\n)\n',
    )


def test_add_refuses_a_package_with_no_kicad_footprint_and_writes_nothing() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["add", "C25744", "C8734"])

    assert exit_info.value.code == (
        "jlcpick: packages.toml has no KiCad footprint for C8734 (LQFP-48(7x7), Microcontrollers "
        "(MCU/MPU/SOC)); converting EasyEDA's is not done yet, `jlcpick get CODE --out DIR` saves "
        "a draft footprint to review"
    )
    assert sorted(p.name for p in Path().iterdir()) == ["board.kicad_pro"]


def test_add_needs_the_project_folder() -> None:
    Path("board.kicad_pro").unlink()

    with pytest.raises(SystemExit) as exit_info:
        main(["add", "C25744"])

    assert exit_info.value.code == (
        "jlcpick: run add in the KiCad project's folder, next to its one .kicad_pro"
    )


def test_add_says_what_to_do_without_kicad(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KICAD10_SYMBOL_DIR")
    monkeypatch.setattr("jlcpick.cli.KICAD_SHARES", ("nowhere",))

    with pytest.raises(SystemExit) as exit_info:
        main(["add", "C25744"])

    assert exit_info.value.code == (
        "jlcpick: KiCad 10's symbols not found; install KiCad 10 or set KICAD10_SYMBOL_DIR"
    )


def test_add_finds_kicad_where_it_is_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KICAD10_SYMBOL_DIR")
    monkeypatch.delenv("KICAD10_FOOTPRINT_DIR")
    monkeypatch.setattr("jlcpick.cli.KICAD_SHARES", ("nowhere", str(KICAD)))

    run("add", "C25744")

    assert R_10K in library.symbols(LIBRARY.read_text())


@pytest.mark.parametrize(
    ("symbol", "footprint"),
    [(s, f) for s, rule in library.PACKAGES.items() for f in rule["footprints"]],
)
def test_every_pin_of_a_stock_symbol_has_a_pad_in_its_footprint(symbol: str, footprint: str):
    nickname, _, name = footprint.partition(":")
    pads = (KICAD / "footprints" / f"{nickname}.pretty" / f"{name}.kicad_mod").read_text()
    base = library.symbols((KICAD / "symbols/Device.kicad_sym").read_text())[
        symbol.partition(":")[2]
    ]

    assert library.missing_pads(base, pads) == []
    assert library.missing_pads(base, pads.replace('(pad "2"', '(pad "3"')) == ["2"]


def test_skill_documents_every_add_field() -> None:
    skill = (ROOT / "skills/jlcpick/SKILL.md").read_text()
    assert [f.name for f in fields(library.Outcome) if f"`{f.name}`" not in skill] == []
