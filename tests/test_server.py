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
        "https://www.njuskalo.hr/auti/volkswagen?foo=1&page=3", "golf", 1000, 5000, 2012, 150000, {"x": "y"}, 2)
    parts = urlsplit(url)
    q = parse_qs(parts.query)
    assert parts.path == "/auti/volkswagen"
    assert q == {"foo": ["1"], "keywords": ["golf"], "price[min]": ["1000"],
                 "price[max]": ["5000"], "yearManufactured[min]": ["2012"],
                 "mileage[max]": ["150000"], "x": ["y"], "page": ["2"]}


@pytest.fixture
def search_html():
    return (FIX / "search_page.html").read_text()


async def test_search_then_details_by_id(monkeypatch, search_html):
    fake = FakeFetcher({"/auti?": search_html, "oglas-51112651": (FIX / "ad_page.html").read_text()})
    monkeypatch.setattr(server, "fetcher", fake)
    res = await server.search_cars(max_price=5000, pages=2)
    assert res["count"] == 3
    assert "price%5Bmax%5D=5000" in fake.urls[0]
    details = await server.get_car_details(["51112651", "999"])
    assert details["ads"][0]["specs"]["Godište"] == "2011."
    assert "error" in details["ads"][1]


async def test_search_reports_block(monkeypatch):
    monkeypatch.setattr(server, "fetcher", FakeFetcher(blocked=True))
    res = await server.search_cars()
    assert res["error"] == "blocked"


async def test_search_resolves_readable_filters(monkeypatch, search_html):
    fake = FakeFetcher({"/auti/toyota?": search_html, "/auti": (FIX / "filters_page.html").read_text()})
    monkeypatch.setattr(server, "fetcher", fake)
    res = await server.search_cars(category="/auti/toyota", filters={
        "fuelTypeId": "diesel", "transmissionTypeId": ["Automatski", "610"],
        "motorPower": {"min": 80}, "onlyFullPrice": True, "x[y]": 1})
    assert res["count"] == 3
    q = parse_qs(urlsplit(fake.urls[-1]).query)
    assert urlsplit(fake.urls[-1]).path == "/auti/toyota"
    assert q["fuelTypeId"] == ["602"]
    assert q["transmissionTypeId[611]"] == ["611"] and q["transmissionTypeId[610]"] == ["610"]
    assert q["motorPower[min]"] == ["80"] and q["onlyFullPrice"] == ["true"] and q["x[y]"] == ["1"]


async def test_search_rejects_unknown_option(monkeypatch):
    monkeypatch.setattr(server, "fetcher", FakeFetcher({"/auti": (FIX / "filters_page.html").read_text()}))
    res = await server.search_cars(filters={"fuelTypeId": "steam"})
    assert "Unknown value 'steam'" in res["error"]


async def test_get_search_filters_for_brand(monkeypatch):
    fake = FakeFetcher({"/auti": (FIX / "filters_page.html").read_text()})
    monkeypatch.setattr(server, "fetcher", fake)
    res = await server.get_search_filters(brand="alfa romeo")
    assert res["category_path"] == "/auti/alfa-romeo"
    assert fake.urls[-1].endswith("/auti/alfa-romeo")
    assert "fuelTypeId" in res["filters"]


async def test_secret_path_hides_everything_else():
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["path"])

    sent = []

    async def send(msg):
        sent.append(msg)

    guarded = server._with_secret_path(app, "/s3cr3t/")
    await guarded({"type": "http", "path": "/mcp"}, None, send)
    await guarded({"type": "http", "path": "/s3cr3tx/mcp"}, None, send)
    await guarded({"type": "http", "path": "/s3cr3t/mcp"}, None, send)
    assert [m["status"] for m in sent if m["type"] == "http.response.start"] == [404, 404]
    assert seen == ["/mcp"]
