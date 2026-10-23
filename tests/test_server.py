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


def _jpeg(width: int, height: int) -> bytes:
    import io

    from PIL import Image as PILImage

    buf = io.BytesIO()
    PILImage.new("RGB", (width, height), (120, 80, 40)).save(buf, "JPEG")
    return buf.getvalue()


async def test_get_car_photos_returns_downscaled_images(monkeypatch):
    import base64
    import io

    from PIL import Image as PILImage

    class PhotoFetcher(FakeFetcher):
        async def get_bytes(self, url):
            self.urls.append(url)
            return _jpeg(1600, 1200)

    fake = PhotoFetcher({"oglas-51851731": (FIX / "real_ad_page.html").read_text()})
    monkeypatch.setattr(server, "fetcher", fake)
    photos = await server.get_car_photos("https://www.njuskalo.hr/auti/opel-corsa-1.0-12v-oglas-51851731", max_photos=2, max_width=400)
    assert len(photos) == 2
    contents = [p.to_image_content() for p in photos]  # what the MCP client receives
    assert all(c.mime_type == "image/jpeg" for c in contents)
    assert PILImage.open(io.BytesIO(base64.b64decode(contents[0].data))).width == 400
    assert fake.urls[1].endswith("slika-288682987.jpg")


async def test_get_car_photos_unknown_id(monkeypatch):
    monkeypatch.setattr(server, "fetcher", FakeFetcher())
    assert "error" in await server.get_car_photos("999")


async def test_show_shortlist_is_an_mcp_app():
    from mcp import Client

    car = {"name": "Toyota Yaris 1.0", "url": "https://www.njuskalo.hr/auti/yaris-oglas-1", "price": "€4,499",
           "year": "2010", "km": "133,000 km", "image": "https://www.njuskalo.hr/image-big/auti/yaris-slika-1.jpg"}
    async with Client(server.mcp) as client:
        tool = next(t for t in (await client.list_tools()).tools if t.name == "show_shortlist")
        assert tool.meta["ui"]["resourceUri"] == server.SHORTLIST_URI
        page = (await client.read_resource(server.SHORTLIST_URI)).contents[0]
        assert page.mime_type == "text/html;profile=mcp-app"
        assert "ui/initialize" in page.text and "get_car_photos" in page.text and "Kilometraža" in page.text
        assert "https://www.njuskalo.hr" in page.meta["ui"]["csp"]["resourceDomains"]

        result = await client.call_tool("show_shortlist", {
            "cars": [car], "title": "1 car", "language": "hr",
            "skipped": [{"title": "Astra", "reason": "warning light"}]})
    assert result.structured_content["language"] == "hr"
    assert result.structured_content["cars"][0]["image"] == car["image"]
    text = result.content[0].text
    assert "[Toyota Yaris 1.0](https://www.njuskalo.hr/auti/yaris-oglas-1)" in text
    assert "[photo](" in text and "- Astra: warning light" in text
