import csv
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from conftest import run

from jlcpick.sources import jlc

pytestmark = pytest.mark.usefixtures("network")

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = list(csv.DictReader((FIXTURES / "swap_reference.csv").open(encoding="utf-8")))
REFERENCE_CODES = "".join(f"{row['lcsc']}\n" for row in REFERENCE)
EXTRA = "C77074\nC344010\nC338067\n"


def report(capsys: pytest.CaptureFixture[str], *argv: str) -> dict[str, Any]:
    run("bom", *argv, "--json")
    return json.loads(capsys.readouterr().out)


def tweak(
    monkeypatch: pytest.MonkeyPatch,
    keyword: str,
    edit: Callable[[list[dict[str, Any]]], None],
    *,
    search: bool,
    source: str | None = None,
) -> None:
    """Edit the recorded answer for ``keyword``; ``source`` is a code whose answer replaces it."""
    real = jlc.fetch_json

    def fetch(url: str, body: dict[str, Any] | None = None) -> Any:
        assert body is not None
        if body["keyword"] != keyword or ("componentLibraryType" in body) != search:
            return real(url, body)
        response = real(url, {"keyword": source} if source else body)
        page = response["data"]["componentPageInfo"]
        edit(page["list"])
        page["total"] = len(page["list"])
        return response

    monkeypatch.setattr("jlcpick.sources.jlc.fetch_json", fetch)


def each(**changes: Any) -> Callable[[list[dict[str, Any]]], None]:
    def edit(items: list[dict[str, Any]]) -> None:
        for item in items:
            item.update(changes)

    return edit


def codes(text: str) -> str:
    Path("bom.csv").write_text(text)
    return "bom.csv"


def test_swaps_match_the_reference_of_order_10973279a(capsys: pytest.CaptureFixture[str]) -> None:
    lines = report(capsys, codes(REFERENCE_CODES))["lines"]

    found = {
        line["lcsc"]: (line["swap"]["to"] or {}).get("lcsc", line["swap"]["verdict"])
        for line in lines
    }
    assert found == {row["lcsc"]: row["expected"] for row in REFERENCE}


def test_swaps_explain_each_verdict_of_the_reference(capsys: pytest.CaptureFixture[str]) -> None:
    lines = report(capsys, codes("C5137554\nC338080\nC412252\nC2994645\nC22383774\nC2903562\n"))

    assert {line["lcsc"]: line["swap"]["reason"] for line in lines["lines"]} == {
        "C5137554": "18pF 50V C0G ±5% 0402",
        "C338080": "C45783: voltage 25V vs 35V",
        "C412252": "no basic or preferred 220uF 1206 in stock",
        "C2994645": "shunt below 1 Ω",
        "C22383774": "electrolytic or polymer capacitor",
        "C2903562": "no rule for MOSFETs",
    }


def test_swaps_take_a_better_part_and_doubt_a_maker_or_an_unranked_dielectric(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = report(capsys, codes(EXTRA))

    assert {line["lcsc"]: line["swap"] for line in result["lines"]} == {
        "C77074": {
            "verdict": "swap",
            "reason": "22uF 10V X5R ±20% 0805",
            "to": {
                "lcsc": "C45783",
                "mpn": "CL21A226MAQNNNE",
                "tier": "basic",
                "preferred": False,
                "saves_usd": 5.03,
            },
        },
        "C344010": {
            "verdict": "to_check",
            "reason": "same MPN from Alpha & Omega Semicon",
            "to": None,
        },
        "C338067": {"verdict": "to_check", "reason": "dielectric X7S has no rank", "to": None},
    }
    assert result["saves_usd"] == 5.03


def test_swaps_in_standard_save_only_the_parts(capsys: pytest.CaptureFixture[str]) -> None:
    result = report(capsys, codes("C77074\n"), "--assembly", "standard")

    [line] = result["lines"]
    assert (line["total_usd"], line["swap"]["to"]["saves_usd"]) == (2.91, 1.96)


def test_swaps_print_safe_swaps_and_count_the_rest(capsys: pytest.CaptureFixture[str]) -> None:
    run("bom", codes(EXTRA))

    out = capsys.readouterr().out
    assert out.endswith(
        "  safe swaps (1)" + " " * 66 + "saves US$ 5.03\n"
        "                   GRM21BR61A226ME51L   22uF 10V X5R ±20% 0805  "
        "  →  C45783     basic       5.03\n"
        "  to check (2) · no rule (0) · keep (0)  → --verbose\n"
        "\n"
        "  basic (0) → --json\n"
    )


def test_swaps_verbose_lists_why_each_part_stays(capsys: pytest.CaptureFixture[str]) -> None:
    run("bom", codes("Refs,LCSC\nQ6,C2903562\nC46,C338080\nR30,C25908\n"), "--verbose")

    out = capsys.readouterr().out
    assert out.endswith(
        "  safe swaps (0)" + " " * 66 + "saves US$ 0.00\n"
        "\n"
        "  to check (0)\n"
        "\n"
        "  no rule (1)\n"
        "    C2903562   HSBB3072             Q6             no rule for MOSFETs\n"
        "\n"
        "  keep (2)\n"
        "    C338080    C2012X5R1V226MT000E  C46            C45783: voltage 25V vs 35V\n"
        "    C25908     0402WGF5601TCE       R30            already preferred\n"
        "\n"
        "  basic (0) → --json\n"
    )


def test_no_swaps_skips_the_search(capsys: pytest.CaptureFixture[str]) -> None:
    result = report(capsys, codes("C9900145630\n"), "--no-swaps")
    run("bom", codes("C9900145630\n"), "--no-swaps")

    assert (result["lines"][0]["swap"], result["saves_usd"]) == (None, None)
    assert "safe swaps" not in capsys.readouterr().out


SAME_MPN = "C344010\n"
HAND = {
    "C5137554": ("18pF", 50, "C0G", 5, "0402"),
    "C1549": ("18pF", 50, "C0G", 5, "0402"),
    "C77074": ("22uF", 10, "X5R", 20, "0805"),
    "C45783": ("22uF", 25, "X5R", 20, "0805"),
}
RANK = {"C0G": 3, "X7R": 2, "X5R": 1, "Y5V": 0}


def as_listed(code: str) -> tuple[str, int, str, int, str]:
    part = jlc.part(code)
    return (
        part.params["Capacitance"],
        int(part.params["Voltage Rating"].removesuffix("V")),
        part.params["Temperature Coefficient"],
        int(part.params["Tolerance"].strip("±%")),
        part.package,
    )


@pytest.mark.parametrize("bom", [REFERENCE_CODES, EXTRA], ids=["reference", "extra"])
def test_no_swap_makes_a_field_worse(capsys: pytest.CaptureFixture[str], bom: str) -> None:
    lines = report(capsys, codes(bom))["lines"]

    pairs = [(line["lcsc"], line["swap"]["to"]["lcsc"]) for line in lines if line["swap"]["to"]]
    assert pairs
    for old, new in pairs:
        assert (as_listed(old), as_listed(new)) == (HAND[old], HAND[new])
        (value, volts, dielectric, tolerance, package) = HAND[old]
        (new_value, new_volts, new_dielectric, new_tolerance, new_package) = HAND[new]
        assert (new_value, new_package) == (value, package)
        assert new_volts >= volts
        assert new_tolerance <= tolerance
        assert RANK[new_dielectric] >= RANK[dielectric]


def test_same_mpn_from_the_same_maker_and_package_swaps(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    tweak(monkeypatch, "AO3400A", each(componentBrandEn="BORN"), search=True)

    [line] = report(capsys, codes(SAME_MPN))["lines"]

    assert (line["swap"]["verdict"], line["swap"]["to"]["lcsc"]) == ("swap", "C20917")
    assert jlc.part("C344010").package == jlc.part("C20917").package


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (dict(componentBrandEn="BORN", componentSpecificationEn="SOT-23-3"), "no rule for MOSFETs"),
        (dict(componentBrandEn="BORN", componentModelEn=""), "no rule for MOSFETs"),
    ],
    ids=["synthetic-other-package", "synthetic-empty-mpn"],
)
def test_same_mpn_needs_the_same_package_and_a_listed_mpn(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, str],
    reason: str,
) -> None:
    tweak(monkeypatch, "AO3400A", each(**change), search=True)
    if not change.get("componentModelEn", "x"):
        tweak(monkeypatch, "C344010", each(componentModelEn=""), search=False)

    [line] = report(capsys, codes(SAME_MPN))["lines"]

    assert (line["swap"]["verdict"], line["swap"]["reason"]) == ("no_rule", reason)


def test_swap_that_costs_more_stays(capsys: pytest.CaptureFixture[str]) -> None:
    [line] = report(capsys, codes("C77074\n"), "--qty", "1000", "--assembly", "standard")["lines"]

    assert line["swap"] == {"verdict": "keep", "reason": "C45783 costs 38.47 more", "to": None}


def test_swap_needs_stock_for_the_whole_order(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    tweak(monkeypatch, "22uF 0805", each(stockCount=4), search=True)

    [line] = report(capsys, codes("C77074\n"))["lines"]

    assert line["swap"] == {"verdict": "keep", "reason": "not enough stock for 5 units", "to": None}


def test_swap_is_basic_or_preferred_whatever_the_search_returns(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    extended = each(componentLibraryType="expand", preferredComponentFlag=False)
    tweak(monkeypatch, "22uF 0805", extended, search=True)

    [line] = report(capsys, codes("C77074\n"))["lines"]

    assert line["swap"]["reason"] == "no basic or preferred 22uF 0805 in stock"


def test_cut_search_is_said_in_the_reason(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    real = jlc.fetch_json

    def fetch(url: str, body: dict[str, Any] | None = None) -> Any:
        response = real(url, body)
        if body and body["keyword"] == "220uF 1206":
            response["data"]["componentPageInfo"]["total"] = 60
        return response

    monkeypatch.setattr("jlcpick.sources.jlc.fetch_json", fetch)

    [line] = report(capsys, codes("C412252\n"))["lines"]

    assert line["swap"]["reason"] == (
        "no basic or preferred 220uF 1206 in stock; search cut at 50 results"
    )


def test_x5r_to_y5v_stays_synthetic(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def y5v(items: list[dict[str, Any]]) -> None:
        for item in items:
            for attribute in item["attributes"]:
                if attribute["attribute_name_en"] == "Temperature Coefficient":
                    attribute["attribute_value_name"] = "Y5V"

    tweak(monkeypatch, "22uF 0805", y5v, search=True)

    [line] = report(capsys, codes("C77074\n"))["lines"]

    assert line["swap"]["verdict"] == "keep"
    assert "dielectric Y5V" in line["swap"]["reason"]


def test_100_to_400_ppm_stays_synthetic(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def candidate(items: list[dict[str, Any]]) -> None:
        for item in items:
            item.update(componentCode="C9999999", componentLibraryType="base")
            for attribute in item["attributes"]:
                if attribute["attribute_name_en"] == "Temperature Coefficient":
                    attribute["attribute_value_name"] = "±400ppm/℃"

    tweak(
        monkeypatch,
        "C25908",
        each(componentLibraryType="expand", preferredComponentFlag=False),
        search=False,
    )
    tweak(monkeypatch, "0402WGF5601TCE", list.clear, search=True, source="C2903562")
    tweak(monkeypatch, "5.6kΩ 0402", candidate, search=True, source="C25908")

    [line] = report(capsys, codes("C25908\n"))["lines"]

    assert line["swap"] == {
        "verdict": "keep",
        "reason": "C9999999: tempco 400ppm/°C vs 100ppm/°C",
        "to": None,
    }
