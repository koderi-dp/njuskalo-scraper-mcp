from pathlib import Path

from njuskalo_mcp.fetcher import looks_blocked
from njuskalo_mcp.parser import (
    ad_id_from,
    extract_initial_state,
    listings_from_state,
    parse_ad_page,
    parse_categories,
    parse_filter_form,
)

FIX = Path(__file__).parent / "fixtures"


def test_initial_state_handles_braces_inside_strings():
    state = extract_initial_state((FIX / "search_page.html").read_text())
    assert state is not None
    assert "browseListingsStore" in state


def test_listings_normalised_and_deduplicated():
    listings = listings_from_state(extract_initial_state((FIX / "search_page.html").read_text()))
    assert [x["id"] for x in listings] == ["51112651", "50712880", "49000001"]
    golf = listings[0]
    assert golf["url"] == "https://www.njuskalo.hr/auti/vw-golf-6-1-6-tdi-oglas-51112651"
    assert golf["info"] == {"Godište": "2011.", "Kilometri": "198000 km"}
    assert golf["promoted"] is False
    assert listings[2]["url"] == "https://www.njuskalo.hr/auti/opel-astra-oglas-49000001"
    assert listings[2]["promoted"] is True


def test_missing_state_returns_none():
    assert extract_initial_state("<html>nothing</html>") is None


def test_ad_id_from():
    assert ad_id_from("51112651") == "51112651"
    assert ad_id_from("https://www.njuskalo.hr/auti/vw-golf-oglas-51112651") == "51112651"
    assert ad_id_from("no id here") is None


def test_parse_ad_page():
    url = "https://www.njuskalo.hr/auti/vw-golf-6-1-6-tdi-oglas-51112651"
    ad = parse_ad_page((FIX / "ad_page.html").read_text(), url)
    assert ad["id"] == "51112651"
    assert ad["title"] == "VW Golf 6 1.6 TDI"
    assert ad["price"] == "4500 EUR"
    assert ad["specs"]["Godište"] == "2011."
    assert ad["specs"]["Mjenjač"] == "Mehanički, 5 brzina"
    assert ad["specs"]["fuelType"] == "Diesel"
    assert "servisna knjiga" in ad["description"]


def test_looks_blocked():
    assert looks_blocked("<html>validate.perfdrive.com</html>")
    assert not looks_blocked("<script>ShieldSquare</script><script>window.__INITIAL_STATE__={}</script>")
    assert looks_blocked("", "https://validate.perfdrive.com/abc")


def test_parse_filter_form_from_real_page():
    form = parse_filter_form((FIX / "filters_page.html").read_text())
    assert form["fuelTypeId"]["options"]["602"] == "Diesel"
    assert form["transmissionTypeId"] == {"type": "multi", "options": {
        "610": "Mehanički mjenjač", "611": "Automatski", "612": "Automatski sekvencijski",
        "613": "Sekvencijski mjenjač"}}
    assert form["price"] == {"type": "range"}
    assert form["yearManufactured"] == {"type": "range"}
    assert form["onlyFullPrice"]["value"] == "true"
    assert "page" not in form and "vehicleIds" not in form


def test_parse_categories():
    cats = parse_categories((FIX / "filters_page.html").read_text())
    assert cats["Alfa Romeo"] == "/auti/alfa-romeo"
    assert cats["Toyota"] == "/auti/toyota"
    assert len(cats) > 80


def test_listings_skip_non_car_ads():
    state = {"browseListingsStore": {"pageData": {"latestListings": [
        {"id": 1, "title": "Golf", "url": "/auti/golf-oglas-1"},
        {"id": 2, "title": "Air pods", "url": "/slusalice/air-pods-oglas-2"},
    ]}}}
    assert [x["id"] for x in listings_from_state(state)] == ["1"]


def test_looks_blocked_detects_captcha_page():
    assert looks_blocked("<script src='https://hcaptcha.com/1/api.js'></script>", "https://www.njuskalo.hr/auti")
    assert looks_blocked("<html></html>", "https://validate.perfdrive.com/abc/?ssc=www.njuskalo.hr")
    assert not looks_blocked("<script>window.__INITIAL_STATE__={}</script>hcaptcha.com", "https://www.njuskalo.hr/auti")
