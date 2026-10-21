import io
import json
from collections.abc import Callable
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request

import pytest
from conftest import recorded, run

from jlcpick.cli import main

pytestmark = pytest.mark.usefixtures("network")


def test_get_prints_a_basic_passive(capsys: pytest.CaptureFixture[str]) -> None:
    run("get", "c25744")

    assert capsys.readouterr().out == (
        "C25744  0402WGF1002TCE · UNI-ROYAL(Uniroyal Elec)\n"
        "  tier        basic\n"
        "  stock       18,717,873\n"
        "  package     0402 · Chip Resistor - Surface Mount\n"
        "  min order   none, basic is billed by use\n"
        "  prices US$  1+ 0.0012 · 1000+ 0.001 · 3000+ 0.0009 · 10000+ 0.0008 · 50000+ 0.0007"
        " · 50200+ 0.0007\n"
        "  datasheet   https://www.lcsc.com/datasheet/lcsc_datasheet_2411221126_UNI-ROYAL-Uniroyal-"
        "Elec-0402WGF1002TCE_C25744.pdf\n"
    )


def test_get_json_shows_a_preferred_ic(capsys: pytest.CaptureFixture[str]) -> None:
    run("get", "C8734", "--json")

    [part] = json.loads(capsys.readouterr().out)
    assert part["lcsc"] == "C8734"
    assert part["mpn"] == "STM32F103C8T6"
    assert part["package"] == "LQFP-48(7x7)"
    assert part["category"] == "Microcontrollers (MCU/MPU/SOC)"
    assert (part["tier"], part["preferred"]) == ("extended", True)
    assert part["prices"][0] == {"from_qty": 1, "usd": 1.4976}


def test_get_rejects_a_code_jlcpcb_does_not_have() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["get", "C999999999"])

    assert exit_info.value.code == "jlcpick: C999999999: JLCPCB has no part with this code"


def test_get_out_saves_footprint_and_step(capsys: pytest.CaptureFixture[str]) -> None:
    run("get", "C25744", "--out", "lib")

    footprint = Path("lib/C25744.kicad_mod").read_text()
    assert footprint.count("(pad ") == 2
    assert f'(model "{Path("lib").resolve()}/C25744.step"' in footprint
    assert Path("lib/C25744.step").read_bytes().startswith(b"STEP ")
    assert capsys.readouterr().err == ""


def test_get_out_warns_when_easyeda_has_no_step(capsys: pytest.CaptureFixture[str]) -> None:
    run("get", "C399938", "--out", "lib")

    assert "(model " not in Path("lib/C399938.kicad_mod").read_text()
    assert not Path("lib/C399938.step").exists()
    assert capsys.readouterr().err == "jlcpick: C399938: EasyEDA has no STEP model\n"


def test_get_out_warns_when_easyeda_has_no_cad(capsys: pytest.CaptureFixture[str]) -> None:
    run("get", "C9900145630", "--out", "lib")

    captured = capsys.readouterr()
    assert captured.out.startswith("C9900145630  HM-19")
    assert captured.err == "jlcpick: C9900145630: EasyEDA has no CAD data, no footprint or STEP\n"
    assert not Path("lib").exists()


def test_get_out_explains_the_easyeda_block(network: Callable[..., None]) -> None:
    network(blocked_host="easyeda.com")

    with pytest.raises(SystemExit) as exit_info:
        main(["get", "C25744", "--out", "lib"])

    assert str(exit_info.value.code).startswith(
        "jlcpick: easyeda.com refused the request (HTTP 403): it is rate-limiting this machine"
    )


def test_get_out_reuses_cached_cad_while_easyeda_blocks(network: Callable[..., None]) -> None:
    run("get", "C25744", "--out", "first")
    network(blocked_host="easyeda.com")

    run("get", "C25744", "--out", "second")

    assert Path("second/C25744.step").read_bytes() == Path("first/C25744.step").read_bytes()


def test_get_out_pauses_between_easyeda_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    calls: list[tuple[str, float]] = []

    def urlopen(request: Request, timeout: float) -> io.BytesIO:
        calls.append((request.host, clock[0]))
        return recorded(request, timeout)

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    monkeypatch.setattr("jlcpick.sources.http.PAUSE_S", 3.0)
    monkeypatch.setattr("jlcpick.sources.http._last_request", {})
    monkeypatch.setattr("jlcpick.sources.http.time.monotonic", lambda: clock[0])
    monkeypatch.setattr("jlcpick.sources.http.time.sleep", sleep)
    monkeypatch.setattr("jlcpick.sources.http.urlopen", urlopen)

    run("get", "C25744", "--out", "lib")

    [(_, cad_time)] = [call for call in calls if call[0] == "easyeda.com"]
    [(_, step_time)] = [call for call in calls if call[0] == "modules.easyeda.com"]
    assert step_time - cad_time >= 3.0


def test_get_explains_when_the_network_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def urlopen(request: Request, timeout: float) -> io.BytesIO:
        raise URLError("no route")

    monkeypatch.setattr("jlcpick.sources.http.urlopen", urlopen)

    with pytest.raises(SystemExit) as exit_info:
        main(["get", "C25744"])

    assert exit_info.value.code == "jlcpick: cannot reach jlcpcb.com: <urlopen error no route>"


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ({"code": 500, "message": "busy"}, "JLCPCB search failed: busy"),
        ({"code": 200, "data": {}}, "C25744: JLCPCB answered in an unexpected format"),
    ],
)
def test_get_explains_a_bad_jlcpcb_answer(
    monkeypatch: pytest.MonkeyPatch, answer: dict[str, object], message: str
) -> None:
    monkeypatch.setattr(
        "jlcpick.sources.http.urlopen",
        lambda request, timeout: io.BytesIO(json.dumps(answer).encode()),
    )

    with pytest.raises(SystemExit) as exit_info:
        main(["get", "C25744"])

    assert exit_info.value.code == f"jlcpick: {message}"


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ({"success": False, "code": 500, "message": "oops"}, "C25744: EasyEDA answered oops"),
        ({"success": True}, "C25744: EasyEDA answered in an unexpected format"),
    ],
)
def test_get_out_explains_a_bad_easyeda_answer(
    monkeypatch: pytest.MonkeyPatch, answer: dict[str, object], message: str
) -> None:
    def urlopen(request: Request, timeout: float) -> io.BytesIO:
        if request.host == "easyeda.com":
            return io.BytesIO(json.dumps(answer).encode())
        return recorded(request, timeout)

    monkeypatch.setattr("jlcpick.sources.http.urlopen", urlopen)

    with pytest.raises(SystemExit) as exit_info:
        main(["get", "C25744", "--out", "lib"])

    assert exit_info.value.code == f"jlcpick: {message}"
