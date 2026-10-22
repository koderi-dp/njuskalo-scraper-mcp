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
from typing import Annotated
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .fetcher import BlockedError, Fetcher
from .parser import BASE_URL, ad_id_from, extract_initial_state, listings_from_state, parse_ad_page

INSTRUCTIONS = """\
Finds used cars on Njuskalo.hr, Croatia's biggest classifieds site.

Workflow: call search_cars (start broad, default cap is 5000 EUR), shortlist the
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
    keywords: Annotated[str | None, Field(description="Free text, e.g. 'golf 7 tdi' or 'toyota yaris'")] = None,
    max_price: Annotated[int | None, Field(description="Max price in EUR", ge=0)] = 5000,
    min_price: Annotated[int | None, Field(description="Min price in EUR, useful to skip parts/wreck ads", ge=0)] = None,
    min_year: Annotated[int | None, Field(description="Oldest model year, e.g. 2012", ge=1950)] = None,
    max_km: Annotated[int | None, Field(description="Max mileage in km", ge=0)] = None,
    search_url: Annotated[str | None, Field(description=(
        "Optional Njuskalo search URL with filters already applied on the website "
        "(fuel, region, gearbox...). Price/keyword arguments are layered on top."))] = None,
    extra_filters: Annotated[dict[str, str] | None, Field(description="Raw Njuskalo query parameters to add")] = None,
    pages: Annotated[int, Field(description="Result pages to fetch (about 25 ads each)", ge=1, le=5)] = 1,
) -> dict:
    """Search used cars on Njuskalo.hr and return compact summaries of each ad."""
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
