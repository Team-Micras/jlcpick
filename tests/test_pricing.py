"""Fee scenarios of Bouni's common/test_bom_estimator_pricing.py, at the 2026-09-09 fees."""

import pytest

from jlcpick import pricing
from jlcpick.sources.jlc import Part, PriceBreak


def part(
    lcsc: str, tier: str = "basic", preferred: bool = False, min_qty: int = 0, loss_qty: int = 0
) -> Part:
    return Part(
        lcsc=lcsc,
        mpn="",
        manufacturer="",
        package="",
        category="",
        tier="basic" if tier == "basic" else "extended",
        preferred=preferred,
        stock=0,
        prices=(PriceBreak(1, 0.30), PriceBreak(10, 0.20)),
        min_qty=min_qty,
        loss_qty=loss_qty,
        params={},
        datasheet=None,
    )


def smt(lcsc: str, tier: str = "extended", joints: int = 1, preferred: bool = False):
    return pricing.Placement(part(lcsc, tier, preferred), tht=False, joints=joints)


def test_an_extended_smt_part_pays_its_fee_once_and_the_price_at_its_break() -> None:
    extended = part("C123", "extended")
    charged = pricing.charged(extended, 2 * 5)

    fees = pricing.fees("economic", [smt("C123", joints=10)], sides=1)

    assert charged * pricing.unit_usd(extended, charged) == pytest.approx(2.00)
    assert (fees.setup_usd, fees.stencil_usd, fees.feeder_usd, fees.smt_joints_usd) == (
        8.18,
        1.53,
        3.07,
        0.02,
    )
    assert fees.total_usd == 12.80


def test_a_tht_part_pays_hand_soldering_and_no_feeder_or_stencil() -> None:
    tht = pricing.Placement(part("C777", "extended"), tht=True, joints=10)

    fees = pricing.fees("economic", [tht], sides=1)

    assert (fees.stencil_usd, fees.feeder_parts, fees.manual_usd) == (0.0, (), 3.74)
    assert fees.total_usd == 11.92


def test_standard_charges_a_feeder_for_every_smt_part() -> None:
    placements = [smt("CEXT1", joints=2), smt("CBAS1", "basic", joints=1)]

    fees = pricing.fees("standard", placements, sides=1)

    assert fees.feeder_parts == ("CEXT1", "CBAS1")
    assert (fees.setup_usd, fees.stencil_usd, fees.feeder_usd) == (25.56, 8.21, 3.06)
    assert (fees.handling_usd, fees.total_usd) == (0.0, 36.83)


def test_preferred_is_exempt_from_the_feeder_only_in_economic() -> None:
    preferred = [smt("C8734", preferred=True)]

    assert pricing.fees("economic", preferred, sides=1).feeder_usd == 0.0
    assert pricing.fees("standard", preferred, sides=1).feeder_usd == 1.53


def test_standard_on_two_sides_pays_setup_and_stencil_twice() -> None:
    fees = pricing.fees("standard", [smt("C1", "basic")], sides=2)

    assert (fees.setup_usd, fees.stencil_usd) == (51.12, 16.42)
    assert pricing.fees("economic", [smt("C1", "basic")], sides=2).setup_usd == 8.18


def test_standard_charges_the_shortfall_under_the_gap_to_economic() -> None:
    placements = [smt(f"C{n}") for n in range(10)]

    fees = pricing.fees("standard", placements, sides=1)

    assert pricing.fees("economic", placements, sides=1).total_usd == 40.43
    assert (fees.handling_usd, fees.total_usd) == (6.27, 55.36)


@pytest.mark.parametrize(
    ("tier", "need", "charged"),
    [("basic", 4, 4), ("extended", 4, 20), ("extended", 30, 35)],
)
def test_charged_adds_attrition_and_the_minimum_except_for_basic(
    tier: str, need: int, charged: int
) -> None:
    assert pricing.charged(part("C1", tier, min_qty=20, loss_qty=5), need) == charged


@pytest.mark.parametrize(("qty", "usd"), [(1, 0.30), (9, 0.30), (10, 0.20), (500, 0.20)])
def test_unit_price_is_the_break_the_quantity_reaches(qty: int, usd: float) -> None:
    assert pricing.unit_usd(part("C1"), qty) == usd
