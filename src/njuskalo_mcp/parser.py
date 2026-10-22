"""Parse Njuskalo search pages and ad (detail) pages.

Search pages embed their data as JSON in ``window.__INITIAL_STATE__``.
Ad pages are parsed defensively: embedded JSON first, then JSON-LD, then the
visible spec table, so a redesign of one layer doesn't break everything.
"""
from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup

BASE_URL = "https://www.njuskalo.hr"
STATE_MARKER = "window.__INITIAL_STATE__"
LISTING_KEYS = ("regularListings", "promotedListings", "superVauListings", "latestListings")
AD_ID_RE = re.compile(r"oglas-(\d+)")
# Rows of the loan calculator on ad pages; they look like specs but aren't about the car.
LOAN_ROWS = {"Iznos", "Minimalna vrijednost", "Maksimalna vrijednost", "Rok otplate", "Anuitet*",
             "Fiksna kamatna stopa", "EKS", "Ukupni iznos otplate kredita"}


def extract_initial_state(html: str) -> dict | None:
    """Return the parsed ``window.__INITIAL_STATE__`` object, or None."""
    idx = html.find(STATE_MARKER)
    if idx == -1:
        return None
    brace = html.find("{", idx)
    if brace == -1:
        return None
    try:
        state, _ = json.JSONDecoder().raw_decode(html, brace)
    except json.JSONDecodeError:
        return None
    return state if isinstance(state, dict) else None


def ad_id_from(value: str | int) -> str | None:
    """Pull the numeric ad ID out of an ID, URL, or slug."""
    text = str(value).strip()
    if text.isdigit():
        return text
    match = AD_ID_RE.search(text)
    return match.group(1) if match else None


def _listing_url(item: dict) -> str:
    url = item.get("url") or item.get("href") or ""
    if url:
        return url if url.startswith("http") else BASE_URL + url
    slug, cat, ad_id = item.get("titleSlug"), item.get("categorySlug"), item.get("id")
    if slug and cat and ad_id:
        return f"{BASE_URL}/{cat}/{slug}-oglas-{ad_id}"
    return ""


def _abstracts(item: dict) -> dict[str, str]:
    """Short spec snippets shown on the search card (year, km, fuel...)."""
    out: dict[str, str] = {}
    for i, abstract in enumerate(item.get("abstracts") or []):
        if not isinstance(abstract, dict):
            continue
        value = str(abstract.get("value") or "").strip()
        if value:
            out[str(abstract.get("caption") or f"info_{i}").strip()] = value
    return out


def listings_from_state(state: dict) -> list[dict]:
    """Normalise every listing on a search page, de-duplicated by ID."""
    page_data = (state.get("browseListingsStore") or {}).get("pageData") or {}
    seen: set[str] = set()
    results: list[dict] = []
    for key in LISTING_KEYS:
        for item in page_data.get(key) or []:
            if not isinstance(item, dict) or item.get("id") is None:
                continue
            ad_id = str(item["id"])
            if ad_id in seen:
                continue
            seen.add(ad_id)
            url = _listing_url(item)
            if url and not url.startswith(f"{BASE_URL}/auti/"):
                continue  # the "latest ads" box mixes in bikes, tyres, phones...
            results.append(
                {
                    "id": ad_id,
                    "title": item.get("title", ""),
                    "price": item.get("priceFormatted") or item.get("price") or "",
                    "location": item.get("location", ""),
                    "posted": item.get("createdAtFormatted") or item.get("createdAt") or "",
                    "info": _abstracts(item),
                    "url": url,
                    "promoted": key != "regularListings",
                }
            )
    return results


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _spec_table(soup: BeautifulSoup) -> dict[str, str]:
    """Collect label/value pairs from the ad's spec table, whatever its markup."""
    specs: dict[str, str] = {}
    for dl in soup.find_all("dl"):
        for dt in dl.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if dd:
                specs[_clean(dt.get_text(" ")).rstrip(":")] = _clean(dd.get_text(" "))
    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) == 2:
            specs[_clean(cells[0].get_text(" ")).rstrip(":")] = _clean(cells[1].get_text(" "))
    # Older layout: alternating label/value wrappers (also used by njuskalo-notifier).
    wraps = soup.select(".ClassifiedDetailBasicDetails-textWrapContainer")
    for label, value in zip(wraps[::2], wraps[1::2]):
        specs[_clean(label.get_text(" ")).rstrip(":")] = _clean(value.get_text(" "))
    return {k: v for k, v in specs.items() if k and v and len(k) < 60 and k not in LOAN_ROWS}


def _json_ld(soup: BeautifulSoup) -> dict:
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for obj in data if isinstance(data, list) else [data]:
            if isinstance(obj, dict) and obj.get("@type") in ("Car", "Vehicle", "Product", "Offer"):
                return obj
    return {}


def _find_ad_in_state(node: Any, ad_id: str, depth: int = 0) -> dict | None:
    """Find the dict describing this ad anywhere in the embedded state."""
    if depth > 8:
        return None
    if isinstance(node, dict):
        if str(node.get("id")) == ad_id and ("title" in node or "description" in node):
            return node
        children = node.values()
    elif isinstance(node, list):
        children = node
    else:
        return None
    for child in children:
        found = _find_ad_in_state(child, ad_id, depth + 1)
        if found:
            return found
    return None


def parse_ad_page(html: str, url: str) -> dict:
    """Extract everything useful for judging a car from its ad page."""
    soup = BeautifulSoup(html, "lxml")
    ad_id = ad_id_from(url) or ""
    ld = _json_ld(soup)
    state = extract_initial_state(html) or {}
    ad = _find_ad_in_state(state, ad_id) if ad_id else None
    ad = ad or {}

    title = ad.get("title") or ld.get("name") or ""
    if not title and soup.find("h1"):
        title = _clean(soup.find("h1").get_text(" "))

    description = ad.get("description") or ld.get("description") or ""
    if not description:  # most specific first; a combined selector would return the first node in document order
        for selector in (".ClassifiedDetailDescription-text", "[class*='Description']", "[itemprop='description']"):
            node = soup.select_one(selector)
            if node:
                description = _clean(node.get_text(" "))
                break
    if not description:
        meta = soup.find("meta", attrs={"property": "og:description"})
        description = meta.get("content", "") if meta else ""

    price = ad.get("priceFormatted") or ""
    offers = ld.get("offers")
    if not price and isinstance(offers, dict) and offers.get("price"):
        price = f"{offers['price']} {offers.get('priceCurrency', '')}".strip()
    if not price:
        node = soup.select_one("[class*='price'], [class*='Price']")
        price = _clean(node.get_text(" ")) if node else ""

    specs = _spec_table(soup)
    for key in ("mileageFromOdometer", "vehicleEngine", "fuelType", "vehicleTransmission",
                "modelDate", "productionDate", "brand", "model", "bodyType", "color"):
        value = ld.get(key)
        if isinstance(value, dict):
            value = value.get("value") or value.get("name")
        if value and key not in specs:
            specs[key] = str(value)

    return {
        "id": ad_id,
        "url": url,
        "title": _clean(str(title)),
        "price": _clean(str(price)),
        "specs": specs,
        "description": _clean(str(description))[:4000],
        "seller": _seller(ad, soup),
    }


def _seller(ad: dict, soup: BeautifulSoup) -> dict:
    """Who is selling: from the embedded state's owner object, else the owner box in the DOM."""
    owner = ad.get("owner") if isinstance(ad.get("owner"), dict) else None
    if owner:
        is_store = bool(owner.get("isStore") or ad.get("isOwnerStore"))
        return {
            "name": owner.get("profileName") or owner.get("userName") or "",
            "type": "dealer" if is_store else "private",
            "phone_verified": bool(owner.get("isPhoneVerified")),
            "rating": owner.get("averageRatingAsSeller"),
            "reviews": owner.get("numberOfReviewsAsSeller"),
            "profile_url": BASE_URL + owner["profileUrl"] if owner.get("profileUrl") else "",
        }
    name = soup.select_one(".ClassifiedDetailOwnerDetails-title")
    info = " ".join(_clean(n.get_text(" ")) for n in soup.select(".ClassifiedDetailOwnerDetails-contactEntry"))
    return {
        "name": _clean(name.get_text(" ")) if name else "",
        "type": "private" if "nije trgovac" in info else ("dealer" if info else ""),
        "phone_verified": "verificirao broj telefona" in info,
    }


# Form fields that the server sets itself or that need a JS widget to fill in.
_SKIP_FIELDS = {"page", "categoryId", "vehicleIds", "geo[lat]", "geo[lng]", "geo[autoComplete]", "geo[radius]"}
_GROUP_RE = re.compile(r"^(\w+)\[(\w+)\]$")


def _label_for(soup: BeautifulSoup, el) -> str:
    label = soup.find("label", attrs={"for": el.get("id")}) if el.get("id") else None
    return _clean(label.get_text(" ")) if label else ""


def parse_filter_form(html: str) -> dict[str, dict]:
    """Describe every filter in the search page's form, keyed by query parameter.

    Each filter is one of: ``select`` (one of ``options``), ``multi`` (any of
    ``options``, sent as ``name[id]=id``), ``range`` (``name[min]``/``name[max]``)
    or ``checkbox`` (send ``value`` to enable).
    """
    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form", id="listingResults") or soup
    filters: dict[str, dict] = {}
    for el in form.find_all(["select", "input"]):
        name = el.get("name")
        if not name or name in _SKIP_FIELDS or el.get("type") == "hidden":
            continue
        group = _GROUP_RE.match(name)
        if el.name == "select":
            options = {o.get("value"): _clean(o.get_text(" ")) for o in el.find_all("option") if o.get("value")}
            if group and group.group(2) in ("min", "max"):
                filters.setdefault(group.group(1), {"type": "range"})
            elif options:
                filters[name] = {"type": "select", "label": _label_for(soup, el), "options": options}
        elif group and group.group(2) in ("min", "max"):
            filters.setdefault(group.group(1), {"type": "range"})
        elif group and el.get("type") == "checkbox":
            entry = filters.setdefault(group.group(1), {"type": "multi", "options": {}})
            entry["options"][el.get("value") or group.group(2)] = _label_for(soup, el)
        elif el.get("type") == "checkbox":
            filters[name] = {"type": "checkbox", "label": _label_for(soup, el), "value": el.get("value") or "1"}
    return filters


def parse_categories(html: str) -> dict[str, str]:
    """Map category names (brands on /auti, models on a brand page) to their URL paths."""
    soup = BeautifulSoup(html, "lxml")
    return {
        _clean(a.get_text(" ")): a["href"]
        for a in soup.select("a.CategoryListing-topCategoryLink[href]")
        if a["href"].startswith("/")
    }
