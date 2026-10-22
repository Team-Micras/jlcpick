from dataclasses import astuple, replace

import pytest

from jlcpick import params
from jlcpick.params import CapSpec, ResSpec
from jlcpick.sources import jlc

pytestmark = pytest.mark.usefixtures("network")


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("C25744", ResSpec(value_ohm=10e3, power_w=0.0625, tolerance=1, tempco_ppm=100)),
        ("C22976", ResSpec(value_ohm=2e6, power_w=0.1, tolerance=1, tempco_ppm=100)),
        ("C2994645", ResSpec(value_ohm=0.05, power_w=3, tolerance=1, tempco_ppm=50)),
        ("C5137554", CapSpec(value_f=18e-12, voltage_v=50, dielectric="C0G", tolerance=5)),
        ("C412252", CapSpec(value_f=220e-6, voltage_v=6.3, dielectric="X5R", tolerance=20)),
        ("C307331", CapSpec(value_f=100e-9, voltage_v=50, dielectric="X7R", tolerance=10)),
        ("C22383774", CapSpec(value_f=220e-6, voltage_v=16, dielectric=None, tolerance=20)),
    ],
)
def test_spec_reads_jlc_attributes(code: str, expected: CapSpec | ResSpec) -> None:
    spec = params.spec(jlc.part(code))

    assert type(spec) is type(expected)
    assert spec is not None
    assert astuple(spec) == pytest.approx(astuple(expected))


@pytest.mark.parametrize("code", ["C2938919", "C42441131", "C20917"])
def test_spec_is_none_for_parts_other_than_resistors_and_capacitors(code: str) -> None:
    assert params.spec(jlc.part(code)) is None


@pytest.mark.parametrize(
    ("text", "unit", "value"),
    [
        ("10kΩ", "Ω", 10e3),
        ("40mΩ", "Ω", 0.04),
        ("2MΩ", "Ω", 2e6),
        ("1µF", "F", 1e-6),
        ("1uF", "F", 1e-6),
        ("100nF", "F", 100e-9),
        ("50V", "V", 50),
        ("±1%", "%", 1),
        ("62.5mW", "W", 0.0625),
        ("1/16W", "W", 0.0625),
        ("±100ppm/℃", "ppm", 100),
        ("-", "V", None),
        ("10kΩ", "F", None),
        (None, "V", None),
    ],
)
def test_quantity_reads_si_prefixes_and_fractions(text: str, unit: str, value: float) -> None:
    assert params.quantity(text, unit) == pytest.approx(value)


def test_spec_turns_an_absolute_tolerance_into_percent() -> None:
    part = jlc.part("C5137554")
    absolute = replace(part, params={**part.params, "Tolerance": "±0.25pF"})

    spec = params.spec(absolute)

    assert isinstance(spec, CapSpec)
    assert spec.tolerance == pytest.approx(1.3889, abs=1e-4)
