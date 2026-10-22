# CLAUDE.md

This is an MCP server that lets Claude find the best used car on Njuskalo.hr, by default under €5,000. The server only fetches and structures data. Claude judges each listing case by case; there is no scoring logic in the code.

## Layout

- `src/njuskalo_mcp/server.py` holds the MCPServer (mcp SDK **2.x**; `FastMCP` was renamed `MCPServer`), the `get_search_filters`, `search_cars` and `get_car_details` tools, and the stdio/HTTP entry point with optional bearer auth (`MCP_AUTH_TOKEN`).
- `src/njuskalo_mcp/fetcher.py` uses curl_cffi with Chrome impersonation, a serial rate limit, a TTL cache, Radware/ShieldSquare block detection, and an optional Playwright fallback (`[browser]` extra).
- `src/njuskalo_mcp/parser.py` parses search pages from `window.__INITIAL_STATE__` → `browseListingsStore.pageData.{regular,promoted,...}Listings`. `parse_filter_form` reads the `#listingResults` form and `parse_categories` the `a.CategoryListing-topCategoryLink` brand/model links, so filter IDs are never hardcoded. Ad pages are parsed from embedded state, then JSON-LD, then the spec table (`dl`, `tr`, legacy `.ClassifiedDetailBasicDetails-*`).
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
- `get_car_details` parses specs and description from the spec table, but `seller` comes back empty and loan-calculator rows (Iznos, Anuitet*, EKS...) end up in `specs`.
- Radware is not IP-based only: datacenter IPs get through at first, but bursts of requests (especially plain curl) get redirected to `validate.perfdrive.com`. The curl_cffi fetcher was blocked after ~10 quick requests.

## Still to do

1. Save a real search page and a real ad page into `tests/fixtures/` and add tests for them.
2. Verify live that `get_search_filters(brand=...)` returns models from a brand page and that filtered category searches work (untested: blocked during testing). Fix the seller selector, and filter loan rows out of `specs`.
3. Test whether a cloud host stays unblocked under normal use, or needs `NJUSKALO_PROXY` / the Playwright fallback.
