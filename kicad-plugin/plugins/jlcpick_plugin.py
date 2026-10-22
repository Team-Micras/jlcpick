"""KiCad 10 PCB editor actions that run the jlcpick CLI on the open board and show its report."""

import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from importlib.metadata import requires
from pathlib import Path
from shutil import which

from jlcpick.bom_input import lcsc_fields

BIN = Path(sys.executable).parent
NO_WX = (
    "jlcpick: the plugin shows its reports with wxPython, which KiCad's Python lacks; "
    "install it (python3-wxgtk4.0 on Debian and Ubuntu)"
)


def priced(command: str, pcb: Path, kicad_cli: str, csv: Path, qty: int) -> list[list[str]]:
    """Export the schematic's BOM to ``csv`` with ``kicad-cli``, then run ``bom`` or ``quote``."""
    sheets = (sheet.read_text(encoding="utf-8") for sheet in pcb.parent.glob("*.kicad_sch"))
    field = next((name for name, _ in lcsc_fields(sheets).most_common(1)), "LCSC")
    export = [
        kicad_cli, "sch", "export", "bom", str(pcb.with_suffix(".kicad_sch")), "-o", str(csv),
        "--ref-range-delimiter", "",
        "--fields", f"Reference,Value,Footprint,QUANTITY,DNP,{field}",
        "--labels", "Refs,Value,Footprint,Qty,DNP,LCSC",
        "--group-by", f"Value,Footprint,{field},DNP",
    ]  # fmt: skip
    return [export, [str(BIN / "jlcpick"), command, str(csv), "--pcb", str(pcb), "--qty", str(qty)]]


def add(codes: str) -> list[list[str]]:
    """Add the LCSC codes typed, separated by spaces or commas."""
    return [[str(BIN / "jlcpick"), "add", *re.findall(r"[^,\s]+", codes)]]


def fab(pcb: Path) -> list[list[str]]:
    """Write the JLCPCB files into the project's ``jlcpcb`` folder, installing KiKit first when
    it is missing."""
    files = [str(BIN / "jlcpick"), "fab", str(pcb), "--out", str(pcb.parent / "jlcpcb")]
    if which("kikit", path=str(BIN)):
        return [files]
    extras = (r.partition(";") for r in requires("jlcpick") or [])
    kikit = next(name.strip() for name, _, marker in extras if "fab" in marker)
    return [[sys.executable, "-m", "pip", "install", kikit], files]


def run(steps: list[list[str]], cwd: Path, keep_going: Callable[[], bool]) -> tuple[int, str]:
    """Run ``steps`` until one fails; return its exit code and output, or the last one's.

    ``keep_going`` is asked about ten times a second; when it says no, the step is killed.
    """
    code, output = 0, ""
    for step in steps:
        process = subprocess.Popen(
            step,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONUTF8": "1"},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        while True:
            try:
                output = process.communicate(timeout=0.1)[0]
                break
            except subprocess.TimeoutExpired:
                if not keep_going():
                    process.kill()
        code = process.returncode
        if code:
            break
    return code, output


def main(action: str) -> None:
    """Run ``action`` on the board open in KiCad's PCB editor and show what jlcpick printed."""
    try:
        import wx
        from wx.lib.dialogs import ScrolledMessageDialog
    except ImportError:
        sys.exit(NO_WX)
    from kipy import KiCad

    kicad = KiCad()
    board = kicad.get_board()
    pcb = Path(board.get_project().path) / board.name
    app = wx.App()
    title = f"jlcpick {action}"
    with tempfile.TemporaryDirectory() as scratch:
        if action == "add":
            codes = wx.GetTextFromUser("LCSC codes, e.g. C25744 C8734:", title)
            if not codes.strip():
                return
            steps = add(codes)
        elif action == "fab":
            steps = fab(pcb)
        else:
            qty = wx.GetNumberFromUser("Boards to make and assemble:", "", title, 5, 1, 100000)
            if qty < 0:
                return
            kicad_cli = kicad.get_kicad_binary_path("kicad-cli")
            steps = priced(action, pcb, kicad_cli, Path(scratch) / "bom.csv", qty)
        progress = wx.ProgressDialog(
            title,
            f"Running jlcpick {action} on {pcb.name}…",
            style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_ELAPSED_TIME,
        )
        code, output = run(steps, pcb.parent, lambda: progress.Pulse()[0])
    cancelled = progress.WasCancelled()
    progress.Destroy()
    if cancelled:
        return
    caption = f"{title} (exit {code})" if code else title
    dialog = ScrolledMessageDialog(None, output, caption, size=(900, 600))
    dialog.text.SetFont(wx.Font(wx.FontInfo(10).Family(wx.FONTFAMILY_TELETYPE)))
    dialog.text.SetInsertionPoint(0)
    dialog.ShowModal()
    app.Destroy()
