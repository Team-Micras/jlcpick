"""The electrical specs of resistors and capacitors, read from JLC's own attributes."""

import re
from dataclasses import dataclass

from jlcpick.sources.jlc import Part

_PREFIX = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3, "": 1.0,
           "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9}  # fmt: skip
CAPACITOR_KEYS = ("Capacitance", "Voltage Rating", "Temperature Coefficient", "Tolerance")
RESISTOR_KEYS = ("Resistance", "Power(Watts)", "Tolerance", "Temperature Coefficient")


@dataclass(frozen=True)
class CapSpec:
    """A capacitor: farads, rated volts, dielectric (``X7R``…) and tolerance in %.

    A field JLC does not list is None.
    """

    value_f: float
    voltage_v: float | None
    dielectric: str | None
    tolerance: float | None


@dataclass(frozen=True)
class ResSpec:
    """A resistor: ohms, rated watts, tolerance in % and temperature coefficient in ppm/°C.

    A field JLC does not list is None.
    """

    value_ohm: float
    power_w: float | None
    tolerance: float | None
    tempco_ppm: float | None


type Spec = CapSpec | ResSpec | None


def spec(part: Part) -> Spec:
    """The part's spec when it is a resistor or capacitor with a value, else None."""
    params = part.params
    if (
        "Capacitor" in part.category
        and (value := quantity(params.get("Capacitance"), "F")) is not None
    ):
        return CapSpec(
            value_f=value,
            voltage_v=quantity(params.get("Voltage Rating"), "V"),
            dielectric=_dielectric(params.get("Temperature Coefficient")),
            tolerance=_tolerance(params.get("Tolerance"), value, "F"),
        )
    if (
        "Resistor" in part.category
        and (value := quantity(params.get("Resistance"), "Ω")) is not None
    ):
        return ResSpec(
            value_ohm=value,
            power_w=quantity(params.get("Power(Watts)"), "W"),
            tolerance=_tolerance(params.get("Tolerance"), value, "Ω"),
            tempco_ppm=quantity(params.get("Temperature Coefficient"), "ppm"),
        )
    return None


def summary(part: Part) -> str:
    """The attributes a swap compares, as JLC writes them, and the package: ``18pF 50V C0G …``."""
    keys = CAPACITOR_KEYS if isinstance(spec(part), CapSpec) else RESISTOR_KEYS
    return " ".join([*(part.params[key] for key in keys if key in part.params), part.package])


def quantity(text: str | None, unit: str) -> float | None:
    """``text`` such as ``10kΩ``, ``1µF``, ``62.5mW``, ``1/16W`` or ``±1%`` in base units.

    None when ``text`` is missing or does not start with a number in ``unit``.
    """
    pattern = rf"±?(\d+(?:\.\d+)?)(?:/(\d+(?:\.\d+)?))?\s*([{''.join(_PREFIX)}]?){unit}"
    match = re.match(pattern, (text or "").strip())
    if match is None:
        return None
    number, divisor, prefix = match.groups()
    return float(number) / float(divisor or 1) * _PREFIX[prefix]


def _tolerance(text: str | None, value: float, unit: str) -> float | None:
    percents = re.findall(r"(\d+(?:\.\d+)?)%", text or "")
    if percents:
        return max(map(float, percents))
    absolute = quantity(text, unit)
    return None if absolute is None or not value else absolute / value * 100


def _dielectric(text: str | None) -> str | None:
    name = (text or "").strip().upper()
    return None if name in ("", "-") else name
