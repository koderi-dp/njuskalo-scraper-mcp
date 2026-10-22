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
    assert golf["image"] == "https://www.njuskalo.hr/image-big/auti/vw-golf-slika-1.jpg"
    assert golf["private_seller"] is True
    assert listings[1]["image"] == "" and listings[1]["private_seller"] is None
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


def test_loan_calculator_rows_are_not_specs():
    html = """<dl><dt>Iznos</dt><dd>3.600,00 €</dd><dt>Anuitet*</dt><dd>40,33 €</dd>
    <dt>Prijeđeni kilometri</dt><dd>128.000 km</dd></dl>"""
    ad = parse_ad_page(html, "https://www.njuskalo.hr/auti/opel-corsa-oglas-51851731")
    assert ad["specs"] == {"Prijeđeni kilometri": "128.000 km"}


def test_parse_real_ad_page():
    url = "https://www.njuskalo.hr/auti/opel-corsa-1.0-12v-oglas-51851731"
    ad = parse_ad_page((FIX / "real_ad_page.html").read_text(), url)
    assert ad["id"] == "51851731"
    assert ad["title"] == "Opel Corsa 1,0 ---128 000 km--"
    assert ad["price"] == "3.600 €"
    assert ad["specs"]["Prijeđeni kilometri"] == "128.000 km"
    assert ad["specs"]["Registriran do"] == "01 / 2027"
    assert "Anuitet*" not in ad["specs"] and "Iznos" not in ad["specs"]
    assert ad["description"].startswith("OPEL CORSA 1,0 BENZIN")
    assert ad["seller"] == {"name": "prodavac123", "type": "private", "phone_verified": True,
                            "rating": 0, "reviews": 0, "profile_url": "https://www.njuskalo.hr/korisnik/prodavac123"}
    assert len(ad["images"]) == 2
    assert ad["images"][0] == "https://www.njuskalo.hr/image-w920x690/auti/opel-corsa-1.0-12v-slika-288682987.jpg"


def test_images_fall_back_to_og_image():
    html = '<meta property="og:image" content="https://www.njuskalo.hr/image-xlsize/auti/x.jpg">'
    ad = parse_ad_page(html, "https://www.njuskalo.hr/auti/x-oglas-1")
    assert ad["images"] == ["https://www.njuskalo.hr/image-xlsize/auti/x.jpg"]


def test_seller_from_dom_when_no_state():
    html = """<div class="ClassifiedDetailOwnerDetails"><h2 class="ClassifiedDetailOwnerDetails-title">Auto Kuća d.o.o.</h2>
    <p class="ClassifiedDetailOwnerDetails-contactEntry">Adresa Zagreb</p></div>"""
    ad = parse_ad_page(html, "https://www.njuskalo.hr/auti/x-oglas-1")
    assert ad["seller"] == {"name": "Auto Kuća d.o.o.", "type": "dealer", "phone_verified": False}
