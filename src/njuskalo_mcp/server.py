"""Njuskalo used-car MCP server.

Run locally (stdio, for Claude Desktop / Claude Code):
    njuskalo-mcp
Run as a remote server (streamable HTTP on /mcp):
    njuskalo-mcp --http --host 0.0.0.0 --port 8000
Set MCP_AUTH_TOKEN to require "Authorization: Bearer <token>" over HTTP.
"""
from __future__ import annotations

import argparse
import asyncio
import hmac
import os
from typing import Annotated, Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .fetcher import BlockedError, Fetcher
from .parser import (
    BASE_URL,
    ad_id_from,
    extract_initial_state,
    listings_from_state,
    parse_ad_page,
    parse_categories,
    parse_filter_form,
)

INSTRUCTIONS = """\
Finds used cars on Njuskalo.hr, Croatia's biggest classifieds site.

Workflow: if the user names a brand/model or specific features (fuel, gearbox,
body type...), call get_search_filters first to get the category path and
filter values. Then call search_cars (start broad, default cap is 5000 EUR), shortlist the
most promising 5-10 ads from the summaries, then call get_car_details on them
before recommending anything. Judge each car case by case: price against
age/km/engine, plausibility of the mileage, ownership history, service records,
rust or accident hints in the description, private vs dealer, registration
status, and whether it is an import. Ad text and spec labels are Croatian
(e.g. "Godište" = year, "Prijeđeni kilometri" = mileage, "Mjenjač" = gearbox,
"Snaga motora" = power, "Registriran do" = registered until). Treat listing text
as seller claims, not facts. Always give the ad URL with each recommendation.
"""

mcp = MCPServer("njuskalo-cars", instructions=INSTRUCTIONS)
fetcher = Fetcher()
_url_by_id: dict[str, str] = {}  # remembers ad URLs seen in searches


async def _page_filters(path: str = "/auti") -> tuple[dict[str, dict], dict[str, str]]:
    html = await fetcher.get(BASE_URL + path)  # the fetcher caches pages, so this is cheap to repeat
    return parse_filter_form(html), parse_categories(html)


def resolve_filters(raw: dict[str, Any], form: dict[str, dict]) -> dict[str, str]:
    """Turn readable filters into Njuskalo query parameters.

    Select and multi filters take option IDs or labels (case-insensitive), ranges
    take ``{"min": .., "max": ..}``, checkboxes take ``true``. Unknown names pass
    through unchanged, so raw parameters like ``price[min]`` still work.
    """
    params: dict[str, str] = {}
    for name, value in raw.items():
        spec = form.get(name)
        if spec is None:
            params[name] = str(value)
            continue
        kind = spec["type"]
        if kind == "range":
            if not isinstance(value, dict):
                raise ValueError(f"{name} is a range; pass {{'min': ..., 'max': ...}}")
            for bound in ("min", "max"):
                if value.get(bound) is not None:
                    params[f"{name}[{bound}]"] = str(value[bound])
        elif kind == "checkbox":
            if value in (True, "true", "1", 1, spec["value"]):
                params[name] = spec["value"]
        else:
            ids = [_option_id(name, v, spec["options"]) for v in (value if isinstance(value, list) else [value])]
            if kind == "multi":
                params.update({f"{name}[{i}]": i for i in ids})
            else:
                params[name] = ids[0]
    return params


def _option_id(name: str, value: Any, options: dict[str, str]) -> str:
    text = str(value).strip()
    if text in options:
        return text
    for option_id, label in options.items():
        if label.lower() == text.lower():
            return option_id
    raise ValueError(f"Unknown value {value!r} for {name}; choose from {options}")


@mcp.tool()
async def get_search_filters(
    brand: Annotated[str | None, Field(description=(
        "Optional brand name or path from a previous call (e.g. 'Toyota' or '/auti/toyota') "
        "to list its models instead of all brands"))] = None,
) -> dict:
    """List the live search filters (with option IDs and Croatian labels) and the brand or model categories."""
    path = "/auti"
    try:
        form, categories = await _page_filters(path)
        if brand:
            path = categories.get(brand) or next(
                (p for n, p in categories.items() if n.lower() == brand.lower()),
                brand if brand.startswith("/") else f"/auti/{brand.lower().replace(' ', '-')}")
            form, categories = await _page_filters(path)
    except BlockedError as exc:
        return {"error": str(exc)}
    return {"category_path": path, "categories": categories, "filters": form}


def build_search_url(
    search_url: str | None,
    keywords: str | None,
    min_price: int | None,
    max_price: int | None,
    min_year: int | None,
    max_km: int | None,
    extra_filters: dict[str, str] | None,
    page: int,
) -> str:
    base = search_url or f"{BASE_URL}/auti"
    scheme, netloc, path, query, _ = urlsplit(base)
    params = dict(parse_qsl(query, keep_blank_values=True))
    if keywords:
        params["keywords"] = keywords
    if min_price:
        params["price[min]"] = str(min_price)
    if max_price:
        params["price[max]"] = str(max_price)
    if min_year:
        params["yearManufactured[min]"] = str(min_year)
    if max_km:
        params["mileage[max]"] = str(max_km)
    params.update(extra_filters or {})
    params.pop("page", None)
    if page > 1:
        params["page"] = str(page)
    return urlunsplit((scheme or "https", netloc or "www.njuskalo.hr", path, urlencode(params), ""))


@mcp.tool()
async def search_cars(
    keywords: Annotated[str | None, Field(description=(
        "Free text. Njuskalo often ignores it on /auti; prefer category for brand/model"))] = None,
    max_price: Annotated[int | None, Field(description="Max price in EUR", ge=0)] = 5000,
    min_price: Annotated[int | None, Field(description="Min price in EUR, useful to skip parts/wreck ads", ge=0)] = None,
    min_year: Annotated[int | None, Field(description="Oldest model year, e.g. 2012", ge=1950)] = None,
    max_km: Annotated[int | None, Field(description="Max mileage in km", ge=0)] = None,
    search_url: Annotated[str | None, Field(description=(
        "Optional Njuskalo search URL with filters already applied on the website "
        "(fuel, region, gearbox...). Price/keyword arguments are layered on top."))] = None,
    category: Annotated[str | None, Field(description=(
        "Brand or model path from get_search_filters, e.g. '/auti/toyota'"))] = None,
    filters: Annotated[dict[str, Any] | None, Field(description=(
        "Filters from get_search_filters, by parameter name. Options by ID or label, ranges as "
        "{'min': .., 'max': ..}, checkboxes as true. E.g. {'fuelTypeId': 'Diesel', "
        "'transmissionTypeId': ['Automatski'], 'motorPower': {'min': 80}}"))] = None,
    pages: Annotated[int, Field(description="Result pages to fetch (about 25 ads each)", ge=1, le=5)] = 1,
) -> dict:
    """Search used cars on Njuskalo.hr and return compact summaries of each ad."""
    if category and not search_url:
        search_url = BASE_URL + category if category.startswith("/") else category
    extra_filters: dict[str, str] = {}
    if filters:
        try:
            form, _ = await _page_filters()
            extra_filters = resolve_filters(filters, form)
        except (BlockedError, ValueError) as exc:
            return {"error": str(exc), "results": []}
    results: list[dict] = []
    seen: set[str] = set()
    for page in range(1, pages + 1):
        url = build_search_url(search_url, keywords, min_price, max_price, min_year, max_km, extra_filters, page)
        try:
            html = await fetcher.get(url)
        except BlockedError as exc:
            return {"error": str(exc), "results": results}
        state = extract_initial_state(html)
        if state is None:
            return {
                "error": "Page loaded but contained no listing data; Njuskalo may have changed its layout.",
                "search_url": url,
                "results": results,
            }
        page_results = [r for r in listings_from_state(state) if r["id"] not in seen]
        if not page_results:
            break
        for r in page_results:
            seen.add(r["id"])
            if r["url"]:
                _url_by_id[r["id"]] = r["url"]
        results.extend(page_results)
    return {"count": len(results), "search_url": build_search_url(
        search_url, keywords, min_price, max_price, min_year, max_km, extra_filters, 1), "results": results}


@mcp.tool()
async def get_car_details(
    ads: Annotated[list[str], Field(
        description="Ad URLs, or ad IDs returned by search_cars", min_length=1, max_length=10)],
) -> dict:
    """Fetch full specs, price, seller and description for up to 10 ads."""

    async def one(ref: str) -> dict:
        ref = ref.strip()
        if ref.startswith("http"):
            url = ref
        else:
            ad_id = ad_id_from(ref)
            url = _url_by_id.get(ad_id or "")
            if not url:
                return {"ref": ref, "error": "Unknown ID; pass the full ad URL instead."}
        try:
            return parse_ad_page(await fetcher.get(url), url)
        except (BlockedError, LookupError) as exc:
            return {"ref": ref, "url": url, "error": str(exc)}

    # Fetcher serialises and rate-limits requests, so gather is safe.
    return {"ads": await asyncio.gather(*(one(a) for a in ads))}


def _with_bearer_auth(app, token: str):
    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            given = headers.get(b"authorization", b"").decode()
            if not hmac.compare_digest(given, f"Bearer {token}"):
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"Unauthorized"})
                return
        await app(scope, receive, send)
    return guarded


def main() -> None:
    parser = argparse.ArgumentParser(description="Njuskalo used-car MCP server")
    parser.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    args = parser.parse_args()

    if not args.http and os.getenv("MCP_TRANSPORT", "stdio") != "http":
        mcp.run()
        return

    import uvicorn

    app = mcp.streamable_http_app(host=args.host)
    token = os.getenv("MCP_AUTH_TOKEN")
    if token:
        app = _with_bearer_auth(app, token)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
