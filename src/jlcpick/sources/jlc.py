"""Part data from the JLCPCB parts search."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from jlcpick.sources.http import SourceError, fetch_json

SEARCH_URL = (
    "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood/selectSmtComponentList"
)


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


def part(lcsc: str) -> Part:
    """Look up ``lcsc``; raise `SourceError` when JLCPCB has no part with that exact code."""
    response = fetch_json(SEARCH_URL, {"keyword": lcsc, "currentPage": 1, "pageSize": 10})
    if response.get("code") != 200:
        raise SourceError(f"JLCPCB search failed: {response.get('message')}")
    found = response["data"]["componentPageInfo"]["list"] or []
    item = next((item for item in found if item["componentCode"] == lcsc), None)
    if item is None:
        raise SourceError(f"{lcsc}: JLCPCB has no part with this code")
    return _part(item)


def _part(item: dict[str, Any]) -> Part:
    prices = sorted(item["componentPrices"], key=lambda price: price["startNumber"])
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
    )
