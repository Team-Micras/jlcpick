"""Part data from the JLCPCB parts search, and bare board prices from its order calculator."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from jlcpick.sources.http import SourceError, fetch_json

SEARCH_PAGE = 50
SEARCH_URL = (
    "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
)
CALCULATOR_URL = (
    "https://cart.jlcpcb.com/api/overseas-core-platform/shoppingCart/calculationGoodsCostsNew"
)
THICKNESSES_MM = (0.4, 0.6, 0.8, 1.0, 1.2, 1.6, 2.0)
COLORS = ("green", "purple", "red", "yellow", "blue", "white", "black")
NO_BARCODE = {
    "serviceConfigAccessId": "dae19911cec340a584ca3c0c5c21fa6d",
    "configOptionAccessId": "fa510a5b5dab4a5199fe2d46b7b40bff",
}


@dataclass(frozen=True)
class PriceBreak:
    """Unit price in US$ from ``from_qty`` units up to the next break."""

    from_qty: int
    usd: float


@dataclass(frozen=True)
class Part:
    """A JLCPCB part as the assembly service sees it today.

    ``min_qty`` and ``loss_qty`` are the assembly minimum and the attrition extra charged for
    every non-basic part. ``params`` are JLC's own attributes, such as ``Resistance``.
    """

    lcsc: str
    mpn: str
    manufacturer: str
    package: str
    category: str
    tier: Literal["basic", "extended"]
    preferred: bool
    stock: int
    prices: tuple[PriceBreak, ...]
    min_qty: int
    loss_qty: int
    params: Mapping[str, str]
    datasheet: str | None
    description: str


@dataclass(frozen=True)
class Matches:
    """The basic or preferred parts a search returned, and how many parts matched in all."""

    parts: tuple[Part, ...]
    total: int

    @property
    def cut(self) -> bool:
        """True when JLC found more parts than one page holds."""
        return self.total > SEARCH_PAGE


@dataclass(frozen=True)
class BoardPrice:
    """What JLCPCB charges to make the bare boards, before shipping, and its build time.

    ``thickness_mm`` is the option JLC priced: the one of `THICKNESSES_MM` nearest the board's.
    """

    usd: float
    build_time: str
    thickness_mm: float


def board_price(
    layers: int, width_mm: float, length_mm: float, thickness_mm: float, qty: int, color: str
) -> BoardPrice:
    """Price ``qty`` bare boards as JLCPCB's order page does, with its defaults: HASL, 1 oz copper.

    ``color`` is one of `COLORS`, the solder mask; JLC prices a color it does not know as green.
    The calculator refuses a request without any service option, so it gets `NO_BARCODE`, the
    page's default.
    """
    thickness = min(THICKNESSES_MM, key=lambda option: abs(option - thickness_mm))
    pcb = {
        "stencilLayer": layers,
        "stencilWidth": width_mm,
        "stencilLength": length_mm,
        "stencilPly": f"{thickness:.1f}",
        "stencilCounts": qty,
        "stencilNumber": 1,
        "plateType": 1,
        "cuprumThickness": 1,
        "adornPut": "HASL(with lead)",
        "adornColor": color.capitalize(),
        "charFontColor": "Black" if color == "white" else "White",
    }
    body = {
        "calculationCostsType": 1,
        "pcbGoodsRequest": pcb,
        "orderServiceConfigVos": [NO_BARCODE],
    }
    response = fetch_json(CALCULATOR_URL, body)
    try:
        if response.get("code") != 200:
            raise SourceError(f"JLCPCB's board calculator failed: {response.get('message')}")
        data = response["data"]
        build_time = next(date["name"] for date in data["achieveDateList"] if date["checked"])
        return BoardPrice(
            round(float(data["orderCountTolls"]["dummyMoney"]), 2), build_time, thickness
        )
    except (KeyError, TypeError, AttributeError, StopIteration, ValueError) as error:
        raise SourceError("JLCPCB's board calculator answered in an unexpected format") from error


def part(lcsc: str) -> Part:
    """Look up ``lcsc``; raise `SourceError` when JLCPCB has no part with that exact code."""
    found, _ = _search(lcsc, {"pageSize": 10})
    try:
        item = next((item for item in found if item["componentCode"] == lcsc), None)
        if item is None:
            raise SourceError(f"{lcsc}: JLCPCB has no part with this code")
        return _part(item)
    except (KeyError, TypeError, AttributeError) as error:
        raise SourceError(f"{lcsc}: JLCPCB answered in an unexpected format") from error


def basic_or_preferred(keyword: str) -> Matches:
    """The first 50 basic or preferred parts with a price that JLCPCB's text search finds."""
    found, total = _search(keyword, {"pageSize": SEARCH_PAGE, "componentLibraryType": "base",
                                     "preferredComponentFlag": True})  # fmt: skip
    try:
        return Matches(tuple(_part(item) for item in found if item["componentPrices"]), total)
    except (KeyError, TypeError, AttributeError) as error:
        raise SourceError(f"{keyword}: JLCPCB answered in an unexpected format") from error


def _search(keyword: str, filters: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    response = fetch_json(SEARCH_URL, {"keyword": keyword, "currentPage": 1, **filters})
    try:
        if response.get("code") != 200:
            raise SourceError(f"JLCPCB search failed: {response.get('message')}")
        page = response["data"]["componentPageInfo"]
        return page["list"] or [], page["total"]
    except (KeyError, TypeError, AttributeError) as error:
        raise SourceError(f"{keyword}: JLCPCB answered in an unexpected format") from error


def _part(item: dict[str, Any]) -> Part:
    prices = sorted(item["componentPrices"], key=lambda price: price["startNumber"])
    if not prices:
        raise SourceError(f"{item['componentCode']}: no price")
    return Part(
        lcsc=item["componentCode"],
        mpn=item["componentModelEn"],
        manufacturer=item["componentBrandEn"],
        package=item["componentSpecificationEn"],
        category=item["firstSortName"],
        tier="basic" if item["componentLibraryType"] == "base" else "extended",
        preferred=item["preferredComponentFlag"],
        stock=item["stockCount"],
        prices=tuple(PriceBreak(p["startNumber"], p["productPrice"]) for p in prices),
        min_qty=item["leastPatchNumber"],
        loss_qty=item["lossNumber"],
        params={
            a["attribute_name_en"]: a["attribute_value_name"] for a in item["attributes"] or []
        },
        datasheet=item["dataManualUrl"] or None,
        description=item["describe"] or "",
    )
