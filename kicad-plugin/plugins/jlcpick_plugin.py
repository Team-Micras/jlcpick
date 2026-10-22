"""KiCad 10 PCB editor actions that run the jlcpick CLI on the open board and show its report."""

import os
import re
import signal
import subprocess
import sys
from collections.abc import Callable
from contextlib import suppress
from importlib.metadata import requires
from pathlib import Path
from shutil import which

BIN = Path(sys.executable).parent
NO_WX = (
    "jlcpick: the plugin shows its reports with wxPython, which KiCad's Python lacks; "
    "install it (python3-wxgtk4.0 on Debian and Ubuntu)"
)
NO_FAB_EXTRA = (
    "The jlcpick installed for the plugin names no KiKit to install for fab; update the plugin, "
    "or Recreate Plugin Environment in Preferences → Plugins"
)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def priced(command: str, pcb: Path, kicad_cli: str, qty: int) -> list[list[str]]:
    """Run ``bom`` or ``quote`` on the board's schematic, exported with KiCad's ``kicad-cli``."""
    schematic = str(pcb.with_suffix(".kicad_sch"))
    return [
        [str(BIN / "jlcpick"), command, schematic, "--pcb", str(pcb), "--qty", str(qty),
         "--kicad-cli", kicad_cli]
    ]  # fmt: skip


def add(codes: str) -> list[list[str]]:
    """Add the LCSC codes typed, separated by spaces or commas."""
    return [[str(BIN / "jlcpick"), "add", *re.findall(r"[^,\s]+", codes)]]


def fab(pcb: Path) -> list[list[str]]:
    """Write the JLCPCB files into the project's ``jlcpcb`` folder, installing KiKit first when
    it is missing; raise `LookupError` when the jlcpick installed names no KiKit."""
    files = [str(BIN / "jlcpick"), "fab", str(pcb), "--out", str(pcb.parent / "jlcpcb")]
    if which("kikit", path=str(BIN)):
        return [files]
    extras = (r.partition(";") for r in requires("jlcpick") or [])
    kikit = next((name.strip() for name, _, marker in extras if "fab" in marker), None)
    if kikit is None:
        raise LookupError(NO_FAB_EXTRA)
    return [[sys.executable, "-m", "pip", "install", "--no-input", kikit], files]


def run(steps: list[list[str]], cwd: Path, keep_going: Callable[[], bool]) -> tuple[int, str]:
    """Run ``steps`` until one fails; return its exit code and output, or the last one's.

    ``keep_going`` is asked about ten times a second; when it says no, the step is stopped with
    the processes it started: on Linux and macOS interrupted first, so jlcpick removes its
    temporary folders, and killed two seconds later.
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
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"},
            creationflags=NO_WINDOW,
            start_new_session=True,
        )
        while True:
            try:
                output = process.communicate(timeout=0.1)[0]
                break
            except subprocess.TimeoutExpired:
                if not keep_going():
                    _kill(process)
        code = process.returncode
        if code:
            break
    return code, output


def _kill(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        kill = ["taskkill", "/F", "/T", "/PID", str(process.pid)]
        subprocess.run(kill, capture_output=True, creationflags=NO_WINDOW)
    else:
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGINT)
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=2)
            os.killpg(process.pid, signal.SIGKILL)


def main(action: str) -> None:
    """Run ``action`` on the board open in KiCad's PCB editor and show what jlcpick printed."""
    try:
        import wx
        from wx.lib.dialogs import ScrolledMessageDialog
    except ImportError:
        sys.exit(NO_WX)
    from kipy import KiCad
    from kipy.errors import ApiError

    kicad = KiCad()
    board = kicad.get_board()
    pcb = Path(board.get_project().path) / board.name
    app = wx.App()
    title = f"jlcpick {action}"
    saved = ""
    if action == "add":
        codes = wx.GetTextFromUser("LCSC codes, e.g. C25744 C8734:", title)
        if not codes.strip():
            return
        steps = add(codes)
    else:
        qty = 0
        if action != "fab":
            qty = wx.GetNumberFromUser("Boards to make and assemble:", "", title, 5, 1, 100000)
            if qty < 0:
                return
        try:
            board.save()
        except ApiError as error:
            warning = f"Could not save {pcb.name}, so jlcpick did not run:\n{error}"
            wx.MessageBox(warning, title, wx.OK | wx.ICON_WARNING)
            return
        saved = f"Saved {pcb.name}.\n\n"
        try:
            if action == "fab":
                steps = fab(pcb)
            else:
                steps = priced(action, pcb, kicad.get_kicad_binary_path("kicad-cli"), qty)
        except LookupError as error:
            wx.MessageBox(str(error), title, wx.OK | wx.ICON_WARNING)
            return
    progress = wx.ProgressDialog(
        title,
        f"{saved}Running jlcpick {action} on {pcb.name}…",
        style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT | wx.PD_ELAPSED_TIME,
    )
    code, output = run(steps, pcb.parent, lambda: progress.Pulse()[0])
    cancelled = progress.WasCancelled()
    progress.Destroy()
    if cancelled:
        return
    caption = f"{title} (exit {code})" if code else title
    dialog = ScrolledMessageDialog(None, saved + output, caption, size=(900, 600))
    dialog.text.SetFont(wx.Font(wx.FontInfo(10).Family(wx.FONTFAMILY_TELETYPE)))
    dialog.text.SetInsertionPoint(0)
    dialog.ShowModal()
    app.Destroy()
