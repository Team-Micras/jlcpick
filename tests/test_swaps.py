import csv
import json
from pathlib import Path
from typing import Any

import pytest
from conftest import run

from jlcpick import params
from jlcpick.params import CapSpec, ResSpec
from jlcpick.sources import jlc

pytestmark = pytest.mark.usefixtures("network")

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = list(csv.DictReader((FIXTURES / "swap_reference.csv").open(encoding="utf-8")))
REFERENCE_CODES = "".join(f"{row['lcsc']}\n" for row in REFERENCE)
EXTRA = "C77074\nC344010\nC338067\n"


def report(capsys: pytest.CaptureFixture[str], *argv: str) -> dict[str, Any]:
    run("bom", *argv, "--json")
    return json.loads(capsys.readouterr().out)


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


def test_swaps_take_a_better_part_the_same_mpn_and_doubt_an_unranked_dielectric(
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
            "verdict": "swap",
            "reason": "same MPN",
            "to": {
                "lcsc": "C20917",
                "mpn": "AO3400A",
                "tier": "basic",
                "preferred": False,
                "saves_usd": 3.14,
            },
        },
        "C338067": {"verdict": "to_check", "reason": "dielectric X7S has no rank", "to": None},
    }
    assert result["saves_usd"] == 8.17


def test_swaps_in_standard_save_only_the_parts(capsys: pytest.CaptureFixture[str]) -> None:
    result = report(capsys, codes("C77074\n"), "--assembly", "standard")

    [line] = result["lines"]
    assert (line["total_usd"], line["swap"]["to"]["saves_usd"]) == (2.91, 1.96)


def test_swaps_print_safe_swaps_and_count_the_rest(capsys: pytest.CaptureFixture[str]) -> None:
    run("bom", codes(EXTRA))

    out = capsys.readouterr().out
    assert out.endswith(
        "  safe swaps (2)" + " " * 66 + "saves US$ 8.17\n"
        "                   GRM21BR61A226ME51L   22uF 10V X5R ±20% 0805  "
        "  →  C45783     basic       5.03\n"
        "                   AO3400A              same MPN                "
        "  →  C20917     basic       3.14\n"
        "  to check (1) · no rule (0) · keep (0)  → --verbose\n"
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


def no_field_worse(old: jlc.Part, new: jlc.Part) -> bool:
    before, after = params.spec(old), params.spec(new)
    if old.mpn.casefold() == new.mpn.casefold():
        return True
    rank = {"C0G": 3, "NP0": 3, "X7R": 2, "X5R": 1, "Y5V": 0}
    if isinstance(before, CapSpec) and isinstance(after, CapSpec):
        return (
            after.value_f == pytest.approx(before.value_f)
            and (after.voltage_v or 0) >= (before.voltage_v or 1e9)
            and (after.tolerance or 1e9) <= (before.tolerance or 0)
            and rank[after.dielectric or ""] >= rank[before.dielectric or ""]
        )
    if isinstance(before, ResSpec) and isinstance(after, ResSpec):
        return (
            after.value_ohm == pytest.approx(before.value_ohm)
            and (after.power_w or 0) >= (before.power_w or 1e9)
            and (after.tolerance or 1e9) <= (before.tolerance or 0)
            and (after.tempco_ppm or 1e9) <= (before.tempco_ppm or 0)
        )
    return False


@pytest.mark.parametrize("bom", [REFERENCE_CODES, EXTRA], ids=["reference", "extra"])
def test_no_swap_makes_a_field_worse(capsys: pytest.CaptureFixture[str], bom: str) -> None:
    lines = report(capsys, codes(bom))["lines"]

    pairs = [(line["lcsc"], line["swap"]["to"]["lcsc"]) for line in lines if line["swap"]["to"]]
    assert pairs
    assert [pair for pair in pairs if not no_field_worse(*map(jlc.part, pair))] == []
