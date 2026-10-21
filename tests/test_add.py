import json
import math
import re
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path

import pytest
from conftest import STEPS, run
from easyeda2kicad.easyeda.parameters_easyeda import Ee3dModel, Ee3dModelBase

from jlcpick import library
from jlcpick.cli import main
from jlcpick.sources import easyeda

KICAD = Path(__file__).parent / "fixtures" / "kicad"
ROOT = Path(__file__).parents[1]
LIBRARY = Path("lib/board.kicad_sym")
R_10K = "Resistor 10kΩ 0402 - 0402WGF1002TCE"
AO3400A = "MOSFETs SOT-23 - AO3400A"
USB_C = "USB Connectors SMD - GT-USB-7010ASV"
USB_C_FOOTPRINT = "USB-C-SMD_G-SWITCH_GT-USB-7010ASV"


@pytest.fixture(autouse=True)
def project(network: Callable[..., None], monkeypatch: pytest.MonkeyPatch) -> None:
    """A KiCad project folder, with KiCad 10.0.7's own libraries installed."""
    monkeypatch.setenv("KICAD10_SYMBOL_DIR", str(KICAD / "symbols"))
    monkeypatch.setenv("KICAD10_FOOTPRINT_DIR", str(KICAD / "footprints"))
    Path("board.kicad_pro").write_text("{}")


def properties(symbol: str) -> list[tuple[str, str]]:
    return re.findall(r'\(property\s+"([^"]*)"\s+"([^"]*)"', symbol)


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
            "draft": False,
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


def test_add_extends_the_kicad_symbol_named_after_the_mpn(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run("add", "C20917")

    symbols = library.symbols(LIBRARY.read_text())
    kicad = library.symbols((KICAD / "symbols/Transistor_FET.kicad_sym").read_text())
    assert list(symbols) == ["Q_NMOS_GSD", AO3400A]
    assert symbols["Q_NMOS_GSD"] == kicad["Q_NMOS_GSD"]
    assert '\n\t\t(extends "Q_NMOS_GSD")\n' in symbols[AO3400A]
    assert properties(symbols[AO3400A]) == [
        ("Reference", "Q"),
        ("Value", "AO3400A"),
        ("Footprint", "Package_TO_SOT_SMD:SOT-23"),
        (
            "Datasheet",
            "https://www.lcsc.com/datasheet/lcsc_datasheet_1811081213_Alpha---Omega-Semicon-"
            "AO3400A_C20917.pdf",
        ),
        (
            "Description",
            "-55℃~+150℃ 1 N-channel 1.45V 1.4W 30V 48mΩ@2.5V 5.7A 50pF 630pF 75pF 7nC@10V "
            "N-Channel SOT-23 MOSFETs ROHS",
        ),
        ("MPN", "AO3400A"),
        ("Manufacturer", "Alpha & Omega Semicon"),
        ("LCSC", "C20917"),
        ("ki_keywords", "N-Channel MOSFET"),
        ("ki_fp_filters", "SOT?23*"),
    ]
    assert not Path("fp-lib-table").exists()
    assert (
        capsys.readouterr().out == f"C20917     added     {AO3400A} · Package_TO_SOT_SMD:SOT-23\n"
    )


def test_add_converts_easyedas_symbol_footprint_and_step_as_a_draft(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run("add", "C2988369", "--json")

    [outcome] = json.loads(capsys.readouterr().out)
    assert outcome == {
        "lcsc": "C2988369",
        "symbol": USB_C,
        "footprint": f"board:{USB_C_FOOTPRINT}",
        "status": "added",
        "draft": True,
    }
    symbols = library.symbols(LIBRARY.read_text())
    assert list(symbols) == [USB_C]
    assert "(extends" not in symbols[USB_C]
    assert f'\t\t(symbol "{USB_C}_0_1"\n' in symbols[USB_C]
    assert [(name, value[:40]) for name, value in properties(symbols[USB_C])] == [
        ("Reference", "U"),
        ("Value", "GT-USB-7010ASV"),
        ("Footprint", f"board:{USB_C_FOOTPRINT}"),
        ("Datasheet", "https://www.lcsc.com/datasheet/lcsc_data"),
        ("Manufacturer", "G-Switch"),
        ("MPN", "GT-USB-7010ASV"),
        ("Description", "-40℃~+85℃ 1 1.68mm 10,000 Cycles 16P 24V"),
        ("LCSC", "C2988369"),
        ("ki_keywords", "USB Connectors"),
    ]
    footprint = Path(f"lib/board.pretty/{USB_C_FOOTPRINT}.kicad_mod").read_text()
    assert library.missing_pads(symbols[USB_C], footprint) == []
    assert "C2988369" not in footprint
    assert (
        f'(model "${{KIPRJMOD}}/lib/board.3dshapes/{USB_C_FOOTPRINT}.step"\n'
        "\t\t(offset (xyz 0.000 -1.050 0.000))"
    ) in footprint
    assert (
        Path(f"lib/board.3dshapes/{USB_C_FOOTPRINT}.step").read_bytes()
        == (STEPS / "be50d0558ed84d368584cedb268b51a8.step").read_bytes()
    )
    assert Path("fp-lib-table").read_text() == (
        "(fp_lib_table\n\t(version 7)\n"
        '\t(lib (name "board") (type "KiCad") (uri "${KIPRJMOD}/lib/board.pretty") '
        '(options "") (descr ""))\n)\n'
    )


def test_add_says_which_parts_are_drafts(capsys: pytest.CaptureFixture[str]) -> None:
    run("add", "C25744", "C399938")

    captured = capsys.readouterr()
    assert captured.out == (
        f"C25744     added     {R_10K} · Resistor_SMD:R_0402_1005Metric\n"
        "C399938    added     USB Connectors SMD - 918-118A2021Y40006 · "
        "board:USB-C-SMD_918-118A2021Y40006  draft: review footprint and 3D\n"
    )
    assert captured.err == "jlcpick: C399938: EasyEDA has no STEP model\n"
    assert sorted(p.as_posix() for p in Path("lib").rglob("*")) == [
        "lib/board.kicad_sym",
        "lib/board.pretty",
        "lib/board.pretty/USB-C-SMD_918-118A2021Y40006.kicad_mod",
    ]


def placed_step(footprint: str) -> tuple[float, float, float, float]:
    """The x and y extent of the footprint's STEP as KiCad 10 places it, in footprint units."""
    model = re.search(
        r'\(model "\$\{KIPRJMOD\}/([^"]*)"\s*\(offset \(xyz (\S+) (\S+) \S+\)\)', footprint
    )
    turn = re.search(r"\(rotate \(xyz 0 0 (\S+)\)\)", footprint)
    assert model is not None
    assert turn is not None
    number = r"(-?[0-9.]+(?:E-?\d+)?)"
    points = re.findall(
        rf"CARTESIAN_POINT \( 'NONE',  \( {number}, {number},", Path(model[1]).read_text()
    )
    angle = math.radians(-float(turn[1]))
    turned = [
        (
            float(x) * math.cos(angle) - float(y) * math.sin(angle) + float(model[2]),
            -(float(x) * math.sin(angle) + float(y) * math.cos(angle) + float(model[3])),
        )
        for x, y in points
    ]
    xs, ys = [x for x, _ in turned], [y for _, y in turned]
    return min(xs), max(xs), min(ys), max(ys)


def step_sits_on_pads(footprint: str) -> bool:
    """The STEP covers every pad centre and stays within its outline and pads, ±0.25 mm."""
    number = r"(-?[0-9.]+)"
    pads = [
        (float(x), float(y))
        for x, y in re.findall(rf"\(pad \S+ \S+ \S+ \(at {number} {number}", footprint)
    ]
    sizes = re.findall(rf"\(at {number} {number} \S+\) \(size {number} {number}\)", footprint)
    edges = re.findall(
        rf"\(start {number} {number}\) \(end {number} {number}\) \(layer F\.CrtYd\)", footprint
    )
    xs = [float(x) + s * float(w) / 2 for x, _, w, _ in sizes for s in (-1, 1)]
    xs += [float(v) for edge in edges for v in edge[0::2]]
    ys = [float(y) + s * float(h) / 2 for _, y, _, h in sizes for s in (-1, 1)]
    ys += [float(v) for edge in edges for v in edge[1::2]]
    x0, x1, y0, y1 = placed_step(footprint)
    covers = all(x0 <= x <= x1 and y0 <= y <= y1 for x, y in pads)
    inside = (
        min(xs) - 0.25 <= x0
        and x1 <= max(xs) + 0.25
        and min(ys) - 0.25 <= y0
        and y1 <= max(ys) + 0.25
    )
    return covers and inside


@pytest.mark.parametrize(
    ("lcsc", "offset"),
    [
        ("C2988369", "0.000 -1.050 0.000"),
        ("C158050", "0.000 0.000 0.000"),
        ("C5271073", "0.000 0.000 0.010"),
        ("C6186", "-0.100 0.000 0.049"),
    ],
)
def test_add_puts_the_step_on_its_pads(lcsc: str, offset: str) -> None:
    run("add", lcsc)

    [path] = Path("lib/board.pretty").glob("*.kicad_mod")
    footprint = path.read_text()
    assert f"(offset (xyz {offset}))" in footprint
    assert step_sits_on_pads(footprint)


def test_easyeda2kicads_own_step_offset_misses_the_usb_c_outline() -> None:
    run("add", "C2988369")

    footprint = Path(f"lib/board.pretty/{USB_C_FOOTPRINT}.kicad_mod").read_text()
    assert not step_sits_on_pads(footprint.replace("0.000 -1.050 0.000", "0.000 0.000 0.000"))


def test_add_again_changes_no_converted_file(capsys: pytest.CaptureFixture[str]) -> None:
    run("add", "C20917", "C2988369")
    first = {
        p: p.read_bytes() for p in Path().rglob("*") if p.is_file() and ".jlcpick" not in p.parts
    }
    capsys.readouterr()

    run("add", "C2988369", "C20917")

    assert {p: p.read_bytes() for p in first} == first
    assert [line.split()[:2] for line in capsys.readouterr().out.splitlines()] == [
        ["C2988369", "unchanged"],
        ["C20917", "unchanged"],
    ]


def test_add_keeps_an_edited_footprint_unless_forced(capsys: pytest.CaptureFixture[str]) -> None:
    run("add", "C2988369")
    path = Path(f"lib/board.pretty/{USB_C_FOOTPRINT}.kicad_mod")
    pristine, symbol = path.read_text(), LIBRARY.read_text()
    path.write_text(pristine.replace("(layer F.SilkS)", "(layer B.SilkS)"))
    LIBRARY.write_text(symbol.replace('"MPN" "GT-USB-7010ASV"', '"MPN" "edited"'))
    edited = path.read_text(), LIBRARY.read_text()
    capsys.readouterr()

    run("add", "C2988369")

    assert (path.read_text(), LIBRARY.read_text()) == edited
    assert capsys.readouterr().err == (
        f'jlcpick: C2988369: lib/board.kicad_sym already has a different "{USB_C}", kept; '
        "--force replaces it\n"
        f"jlcpick: C2988369: kept lib/board.pretty/{USB_C_FOOTPRINT}.kicad_mod, "
        "it differs from the EasyEDA conversion; --force rewrites it\n"
    )

    run("add", "C2988369", "--force")

    assert (path.read_text(), LIBRARY.read_text()) == (pristine, symbol)
    assert capsys.readouterr().out.split()[1] == "replaced"


def test_add_refuses_a_part_easyeda_has_nothing_for() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["add", "C25744", "C9900145630"])

    assert str(exit_info.value.code).startswith("jlcpick: C9900145630 (")
    assert str(exit_info.value.code).endswith(
        "no KiCad symbol or footprint fits it and EasyEDA has nothing to convert; draw it by hand"
    )
    assert sorted(p.name for p in Path().iterdir()) == ["board.kicad_pro"]


def test_add_refuses_two_codes_whose_footprints_differ_under_one_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("jlcpick.sources.easyeda.package", lambda raw: "SAME")

    with pytest.raises(SystemExit) as exit_info:
        main(["add", "C2988369", "C399938"])

    assert exit_info.value.code == (
        "jlcpick: C2988369 and C399938 both make lib/board.pretty/SAME.kicad_mod, differently; "
        "add only one of them, the other would get this footprint, and draw it by hand"
    )
    assert not Path("lib").exists()


def test_add_refuses_a_converted_symbol_with_a_pin_its_footprint_lacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    convert = easyeda.symbol
    monkeypatch.setattr(
        "jlcpick.sources.easyeda.symbol",
        lambda raw: convert(raw).replace('(number "A1B12"', '(number "A99"'),
    )

    with pytest.raises(SystemExit) as exit_info:
        main(["add", "C2988369"])

    assert exit_info.value.code == (
        "jlcpick: C2988369: EasyEDA's footprint has no pad for pin A99 of its symbol; "
        "nothing written"
    )
    assert not Path("lib").exists()


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


def test_add_finds_kicads_symbols_and_footprints_installed_apart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for kind in ("symbols", "footprints"):
        (tmp_path / kind).mkdir()
        (tmp_path / kind / kind).symlink_to(KICAD / kind)
    monkeypatch.delenv("KICAD10_SYMBOL_DIR")
    monkeypatch.delenv("KICAD10_FOOTPRINT_DIR")
    monkeypatch.setattr(
        "jlcpick.cli.KICAD_SHARES", (str(tmp_path / "symbols"), str(tmp_path / "footprints"))
    )

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


def kicad_library() -> str:
    return (KICAD / "symbols/Device.kicad_sym").read_text()


def test_add_refuses_a_base_symbol_wired_differently_from_kicads(
    capsys: pytest.CaptureFixture[str],
) -> None:
    kicad = library.symbols(kicad_library())["D"]
    swapped = kicad.replace('(number "1"', '(number "x"').replace('(number "2"', '(number "1"')
    LIBRARY.parent.mkdir()
    LIBRARY.write_text(
        '(kicad_symbol_lib\n\t(version 20251024)\n\t(generator "jlcpick")\n\t'
        + swapped.replace('(number "x"', '(number "2"')
        + "\n)\n"
    )
    before = LIBRARY.read_text()

    with pytest.raises(SystemExit) as exit_info:
        main(["add", "C7420318"])

    assert str(exit_info.value.code).startswith(
        "jlcpick: lib/board.kicad_sym already has a `D` wired differently from KiCad's: "
    )
    assert LIBRARY.read_text() == before
    assert not Path("sym-lib-table").exists()


def test_add_puts_back_a_deleted_base_symbol() -> None:
    run("add", "C25744")
    symbols = library.symbols(LIBRARY.read_text())
    LIBRARY.write_text(LIBRARY.read_text().replace(symbols["R"], ""))
    assert "R" not in library.symbols(LIBRARY.read_text())

    run("add", "C25744")

    restored = library.symbols(LIBRARY.read_text())
    assert restored["R"] == symbols["R"]
    assert restored[R_10K] == symbols[R_10K]


def test_add_refuses_two_codes_that_make_the_same_symbol() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["add", "C25744", "C9999999"])

    assert exit_info.value.code == (
        f'jlcpick: C25744 and C9999999 both make the symbol "{R_10K}", '
        "and a library has one symbol per name; add only the one you want"
    )
    assert not LIBRARY.exists()


def test_add_keeps_the_first_of_two_codes_with_the_same_mpn_across_calls(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run("add", "C25744")
    first = LIBRARY.read_text()
    capsys.readouterr()

    run("add", "C9999999", "--json")

    assert LIBRARY.read_text() == first
    captured = capsys.readouterr()
    assert json.loads(captured.out)[0]["status"] == "kept"
    assert "C9999999: lib/board.kicad_sym already has a different" in captured.err


def test_add_warns_when_the_table_points_the_library_elsewhere(
    capsys: pytest.CaptureFixture[str],
) -> None:
    Path("sym-lib-table").write_text(
        '(sym_lib_table\n\t(version 7)\n\t(lib (name "board") (type "KiCad") '
        '(uri "${KIPRJMOD}/other.kicad_sym") (options "") (descr ""))\n)\n'
    )

    run("add", "C25744")

    assert capsys.readouterr().err == (
        "jlcpick: sym-lib-table maps `board` to ${KIPRJMOD}/other.kicad_sym, but add wrote "
        "${KIPRJMOD}/lib/board.kicad_sym; point it at the right file\n"
    )


@pytest.mark.parametrize("content", ["", "(kicad_symbol_lib\n\t(version 20251024)\n"])
def test_add_reports_an_empty_or_cut_off_library(content: str) -> None:
    LIBRARY.parent.mkdir()
    LIBRARY.write_text(content)

    with pytest.raises(SystemExit) as exit_info:
        main(["add", "C25744"])

    assert str(exit_info.value.code).startswith(
        "jlcpick: lib/board.kicad_sym: empty or cut off, its parentheses do not balance"
    )
    assert LIBRARY.read_text() == content


def test_add_ignores_a_kicad_of_another_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    old = tmp_path / "kicad9"
    (old / "symbols").mkdir(parents=True)
    (old / "symbols/Device.kicad_sym").write_text(
        kicad_library().replace('(generator_version "10.0")', '(generator_version "9.0")')
    )
    monkeypatch.delenv("KICAD10_SYMBOL_DIR")
    monkeypatch.setattr("jlcpick.cli.KICAD_SHARES", (str(old),))

    with pytest.raises(SystemExit) as exit_info:
        main(["add", "C25744"])

    assert exit_info.value.code == (
        f"jlcpick: KiCad 10's symbols not found (the KiCad found, {old}, is another version); "
        "install KiCad 10 or set KICAD10_SYMBOL_DIR"
    )


def test_add_copies_the_root_of_a_symbol_that_extends_one_that_extends_another() -> None:
    run("add", "C9999998")

    symbols = library.symbols(LIBRARY.read_text())
    name = "Diodes - General Purpose DO-41 - 1N4937"
    assert list(symbols) == ["1N4001", name]
    assert '\n\t\t(extends "1N4001")\n' in symbols[name]
    assert library.pins(symbols["1N4001"]) != []


def test_add_checks_the_pads_against_the_root_of_a_symbol_with_two_parents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KICAD10_FOOTPRINT_DIR", str(Path("footprints")))
    footprint = Path("footprints/Diode_THT.pretty/D_DO-41_SOD81_P10.16mm_Horizontal.kicad_mod")
    footprint.parent.mkdir(parents=True)
    pristine = (KICAD / "footprints" / "Diode_THT.pretty" / footprint.name).read_text()
    footprint.write_text(re.sub(r"\(pad \"?2\"?", '(pad "9"', pristine))

    with pytest.raises(SystemExit) as exit_info:
        main(["add", "C9999998"])

    assert str(exit_info.value.code).startswith("jlcpick: Diode_THT:D_DO-41")
    assert "no pad for pin 2" in str(exit_info.value.code)


def test_add_writes_a_new_symbol_and_keeps_the_footprint_the_user_changed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run("add", "C2988369")
    path = Path(f"lib/board.pretty/{USB_C_FOOTPRINT}.kicad_mod")
    path.write_text(path.read_text().replace("(layer F.SilkS)", "(layer B.SilkS)"))
    saved = path.read_text()
    monkeypatch.setattr("jlcpick.sources.easyeda.package", lambda raw: USB_C_FOOTPRINT)
    capsys.readouterr()

    run("add", "C399938", "--json")

    captured = capsys.readouterr()
    assert [(o["lcsc"], o["status"]) for o in json.loads(captured.out)] == [("C399938", "added")]
    assert path.read_text() == saved
    assert "USB Connectors SMD - 918-118A2021Y40006" in library.symbols(LIBRARY.read_text())
    assert (
        f"kept {path.as_posix()}, it differs from the EasyEDA conversion; --force" in captured.err
    )


def test_add_force_refuses_to_rewrite_a_footprint_another_symbol_uses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run("add", "C2988369")
    monkeypatch.setattr("jlcpick.sources.easyeda.package", lambda raw: USB_C_FOOTPRINT)
    before = {p: p.read_bytes() for p in Path("lib").rglob("*") if p.is_file()}

    with pytest.raises(SystemExit) as exit_info:
        main(["add", "C399938", "--force"])

    assert "also use; nothing written" in str(exit_info.value.code)
    assert USB_C in str(exit_info.value.code)
    assert {p: p.read_bytes() for p in Path("lib").rglob("*") if p.is_file()} == before


def test_add_force_calls_a_new_symbol_added(capsys: pytest.CaptureFixture[str]) -> None:
    run("add", "C25744", "--force")

    assert capsys.readouterr().out.split()[1] == "added"


STEP_BOX = """DATA;
#1 = CARTESIAN_POINT ( 'NONE',  ( 0.0, 0.0, 0.0 ) ) ;
#2 = CARTESIAN_POINT ( 'NONE',  ( 2.0, 1.0, 0.5 ) ) ;
#3 = VERTEX_POINT ( 'NONE', #1 ) ;
#4 = VERTEX_POINT ( 'NONE', #2 ) ;
"""


@pytest.mark.parametrize(
    ("rotation", "offset"),
    [(0, (-1.0, -0.5)), (90, (0.5, -1.0)), (180, (1.0, 0.5))],
)
def test_step_offset_turns_the_box_as_the_footprint_turns_it(
    rotation: int, offset: tuple[float, float]
) -> None:
    model = Ee3dModel("m", "u", Ee3dModelBase(0, 0, 0), Ee3dModelBase(0, 0, rotation))

    placed = easyeda._step_offset(model, STEP_BOX.encode())

    assert (placed.x, placed.y, placed.z) == (offset[0], offset[1], 0.0)


@pytest.mark.parametrize(
    "step",
    [b"DATA;\n", b"DATA;\n#3 = VERTEX_POINT ( 'NONE', #1 ) ;\n"],
    ids=["no vertices", "vertex without a point"],
)
def test_add_goes_on_without_3d_when_the_step_cannot_be_read(
    step: bytes, capsys: pytest.CaptureFixture[str]
) -> None:
    cache = Path(".jlcpick/cache")
    cache.mkdir(parents=True)
    (cache / "C2988369.step").write_bytes(step)

    run("add", "C2988369")

    captured = capsys.readouterr()
    assert captured.err == "jlcpick: C2988369: STEP unreadable, added without 3D\n"
    assert USB_C in library.symbols(LIBRARY.read_text())
    assert "(model " not in Path(f"lib/board.pretty/{USB_C_FOOTPRINT}.kicad_mod").read_text()
    assert not Path("lib/board.3dshapes").exists()


@pytest.mark.parametrize(
    ("text", "safe"),
    [("a*b?c|d", "a_b_c_d"), ("USB 3.0 ", "USB 3.0_"), ("cap. ..", "cap____")],
)
def test_safe_name_replaces_what_windows_refuses(text: str, safe: str) -> None:
    assert library.safe_name(text) == safe


def test_add_names_packages_toml_only_when_it_is_the_table_that_is_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(library, "missing_pads", lambda symbol, footprint: ["2"])

    for code, fix in [("C20917", False), ("C25744", True)]:
        with pytest.raises(SystemExit) as exit_info:
            main(["add", code])
        assert str(exit_info.value.code).endswith("; fix packages.toml") is fix
