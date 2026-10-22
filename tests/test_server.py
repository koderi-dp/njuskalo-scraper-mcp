from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from njuskalo_mcp import server
from njuskalo_mcp.fetcher import BlockedError

FIX = Path(__file__).parent / "fixtures"


class FakeFetcher:
    def __init__(self, pages: dict[str, str] | None = None, blocked: bool = False):
        self.pages = pages or {}
        self.blocked = blocked
        self.urls: list[str] = []

    async def get(self, url: str) -> str:
        self.urls.append(url)
        if self.blocked:
            raise BlockedError("blocked")
        for key, html in self.pages.items():
            if key in url:
                return html
        return "<script>window.__INITIAL_STATE__={}</script>"


def test_build_search_url_layers_filters_on_pasted_url():
    url = server.build_search_url(
        "https://www.njuskalo.hr/auti/volkswagen?foo=1&page=3", "golf", 1000, 5000, {"x": "y"}, 2)
    parts = urlsplit(url)
    q = parse_qs(parts.query)
    assert parts.path == "/auti/volkswagen"
    assert q == {"foo": ["1"], "keywords": ["golf"], "price[from]": ["1000"],
                 "price[to]": ["5000"], "x": ["y"], "page": ["2"]}


@pytest.fixture
def search_html():
    return (FIX / "search_page.html").read_text()


async def test_search_then_details_by_id(monkeypatch, search_html):
    fake = FakeFetcher({"/auti?": search_html, "oglas-51112651": (FIX / "ad_page.html").read_text()})
    monkeypatch.setattr(server, "fetcher", fake)
    res = await server.search_cars(max_price=5000, pages=2)
    assert res["count"] == 3
    assert "price%5Bto%5D=5000" in fake.urls[0]
    details = await server.get_car_details(["51112651", "999"])
    assert details["ads"][0]["specs"]["Godište"] == "2011."
    assert "error" in details["ads"][1]


async def test_search_reports_block(monkeypatch):
    monkeypatch.setattr(server, "fetcher", FakeFetcher(blocked=True))
    res = await server.search_cars()
    assert res["error"] == "blocked"
