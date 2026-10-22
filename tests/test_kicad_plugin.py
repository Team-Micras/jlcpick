import json
import sys
import time
import tomllib
import zipfile
from pathlib import Path

import jlcpick_plugin
import pytest
from jlcpick_plugin import add, fab, priced, run
from pack import pack

ROOT = Path(__file__).parents[1]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A board, with its schematic next to it."""
    (tmp_path / "board.kicad_pcb").write_text("(kicad_pcb)")
    (tmp_path / "board.kicad_sch").write_text("(kicad_sch)")
    return tmp_path / "board.kicad_pcb"


@pytest.fixture
def bin_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """The folder of the plugin's Python, where jlcpick and KiKit get installed."""
    folder = tmp_path / "bin"
    folder.mkdir()
    monkeypatch.setattr(jlcpick_plugin, "BIN", folder)
    return folder


@pytest.mark.parametrize("command", ["bom", "quote"])
def test_bom_and_quote_run_on_the_schematic_with_kicads_own_cli(
    command: str, project: Path, bin_dir: Path
) -> None:
    steps = priced(command, project, "/app/bin/kicad-cli", 10)

    assert steps == [
        [
            str(bin_dir / "jlcpick"), command, str(project.with_suffix(".kicad_sch")),
            "--pcb", str(project), "--qty", "10", "--kicad-cli", "/app/bin/kicad-cli",
        ]
    ]  # fmt: skip


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

    assert steps[0] == [sys.executable, "-m", "pip", "install", "--no-input", "kikit==1.8.1"]
    assert steps[1][1:3] == ["fab", str(project)]


def test_fab_says_what_to_do_when_the_jlcpick_installed_names_no_kikit(
    monkeypatch: pytest.MonkeyPatch, project: Path, bin_dir: Path
) -> None:
    monkeypatch.setattr(jlcpick_plugin, "requires", lambda _: ["easyeda2kicad==1.0.1"])

    with pytest.raises(LookupError, match="Recreate Plugin Environment"):
        fab(project)


def test_the_plugin_installs_the_jlcpick_release_it_is_packed_with() -> None:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    metadata = json.loads((ROOT / "kicad-plugin/metadata.json").read_text())
    requirements = (ROOT / "kicad-plugin/plugins/requirements.txt").read_text().splitlines()

    assert [v["version"] for v in metadata["versions"]] == [version]
    assert f"jlcpick @ git+https://github.com/Team-Micras/jlcpick@v{version}" in requirements


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


def test_run_kills_the_step_and_what_it_started_when_cancelled(tmp_path: Path) -> None:
    sleep = "import time; time.sleep(60)"
    child = f"import subprocess, sys; subprocess.Popen([sys.executable, '-c', {sleep!r}]); {sleep}"
    started = time.monotonic()

    code, _ = run([[sys.executable, "-c", child]], tmp_path, lambda: False)

    assert code != 0
    assert time.monotonic() - started < 10


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no SIGINT for a process group")
def test_cancel_leaves_no_temporary_folder(tmp_path: Path) -> None:
    step = (
        "import tempfile, time\n"
        "with tempfile.TemporaryDirectory(dir='.'):\n"
        "    open('started', 'w').close()\n"
        "    time.sleep(60)\n"
    )

    started = tmp_path / "started"

    code, _ = run([[sys.executable, "-c", step]], tmp_path, lambda: not started.exists())

    assert code != 0
    assert [p.name for p in tmp_path.iterdir()] == ["started"]


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
