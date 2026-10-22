# CLAUDE.md

This is an MCP server that lets Claude find the best used car on Njuskalo.hr, by default under €5,000. The server only fetches and structures data. Claude judges each listing case by case; there is no scoring logic in the code.

## Layout

- `src/njuskalo_mcp/server.py` holds the MCPServer (mcp SDK **2.x**; `FastMCP` was renamed `MCPServer`), the `get_search_filters`, `search_cars`, `get_car_details` and `get_car_photos` (MCP image content, downscaled with Pillow) tools, and the stdio/HTTP entry point with optional bearer auth (`MCP_AUTH_TOKEN`).
- `src/njuskalo_mcp/fetcher.py` uses curl_cffi with Chrome impersonation, a serial rate limit (`get` for pages, `get_bytes` for photos), a TTL cache, and Radware/ShieldSquare challenge detection (a challenged session is discarded).
- `src/njuskalo_mcp/parser.py` parses search pages from `window.__INITIAL_STATE__` → `browseListingsStore.pageData.{regular,promoted,...}Listings`. `parse_filter_form` reads the `#listingResults` form and `parse_categories` the `a.CategoryListing-topCategoryLink` brand/model links, so filter IDs are never hardcoded. Ad pages: title/price/seller come from the embedded state (`listingDetailStore.pageData.listing`, with its `owner` object), specs from the `dl` tables (loan-calculator rows dropped), description from `.ClassifiedDetailDescription-text`, photos from `pageData.media.photos` (`og:image` fallback); search cards carry `image` and `isOwnerResidentialSeller`; JSON-LD and DOM selectors are fallbacks only (real pages have no JSON-LD). `tests/fixtures/real_ad_page.html` is a trimmed, anonymised real ad.
- `deploy/home-proxy/` is a tinyproxy image (password, njuskalo.hr-only filter) to run at home and point `NJUSKALO_PROXY` at from a cloud host.
- `tests/` runs against synthetic fixtures; there is no network access in tests.
- `.github/workflows/ci.yml` runs ruff and pytest. `publish.yml` runs tests, then pushes a multi-arch image to `ghcr.io/koderi-dp/njuskalo-scraper-mcp`.

## Constraints

- Njuskalo blocks non-HR and datacenter IPs. Never add a CI step that hits the live site.
- The old Apify scraper from roshtarg-cpu had **no license**, so it was removed and none of its code is reused. Only facts were kept: the `__INITIAL_STATE__` location and the `page` / `keywords` parameters (its `price[from]`/`price[to]` names were wrong; the site uses `price[min]`/`price[max]`).
- Keep requests polite: at least 1.5 s apart, at most 5 pages per search.

## Live-site findings (tested 2026-10-22 from a US Google Cloud IP)

- Search works: field names and `/{cat}/{slug}-oglas-{id}` URLs are correct.
- Verified filters: `price[min]`/`price[max]`, `yearManufactured[min|max]`, `mileage[min|max]`. All other filters and their IDs come from the live form (`tests/fixtures/filters_page.html` is a trimmed real copy).
- `keywords` on `/auti` is **ignored** (returns unfiltered results). Brands are category paths (`/auti/toyota`); `search_cars(category=...)` uses them.
- `get_car_details` is verified against a real ad page: specs from `dl` tables (loan-calculator rows dropped via `LOAN_ROWS`), seller from `listing.owner` (name, private/dealer, phone verified, rating).
- Photo URLs (`image-w920x690/...`) are served to anyone, no challenge, but the claude.ai artifact viewer blocks cross-site images, so photos must be embedded as data URIs; `get_car_photos` exists for that.
- From a Croatian home IP (2026-10-22, server on a TrueNAS behind a Cloudflare Tunnel): search, brand page (34 Toyota models), filtered model search (`/auti/toyota-yaris` + `fuelTypeId`/`transmissionTypeId` resolved from labels) and ad details all worked first time; 6 page views on one session with the 1.5 s spacing, no challenge.
- Radware/ShieldSquare, measured: a session that never runs the site's JS gets a few page views (about 3 cookieless, or 1-5 with cookies depending on IP reputation), then every request is 302'd to an hCaptcha on `validate.perfdrive.com` ("maybe you're on a proxy network"). The challenge sticks to the session's cookies, not the IP: a fresh session gets through again after a 10-15 min window. Render's shared egress IP is challenged on the very first request. Headless Chromium (`HeadlessChrome` UA) is challenged on its first page load from a datacenter IP, so a browser fallback cannot help and was removed; disguising the browser would be evasion and is out of scope. The practical fix is a Croatian home/residential IP (`deploy/home-proxy/` + `NJUSKALO_PROXY`, or running the server at home).

## Still to do

1. Save a real search page into `tests/fixtures/` (the ad page is done) and add a test for it.
2. Find how many page views a home-IP session gets before a challenge (6 are known to be fine).
