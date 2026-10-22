# CLAUDE.md

This is an MCP server that lets Claude find the best used car on Njuskalo.hr, by default under €5,000. The server only fetches and structures data. Claude judges each listing case by case; there is no scoring logic in the code.

## Layout

- `src/njuskalo_mcp/server.py` holds the MCPServer (mcp SDK **2.x**; `FastMCP` was renamed `MCPServer`), the `search_cars` and `get_car_details` tools, and the stdio/HTTP entry point with optional bearer auth (`MCP_AUTH_TOKEN`).
- `src/njuskalo_mcp/fetcher.py` uses curl_cffi with Chrome impersonation, a serial rate limit, a TTL cache, Radware/ShieldSquare block detection, and an optional Playwright fallback (`[browser]` extra).
- `src/njuskalo_mcp/parser.py` parses search pages from `window.__INITIAL_STATE__` → `browseListingsStore.pageData.{regular,promoted,...}Listings`. Ad pages are parsed from embedded state, then JSON-LD, then the spec table (`dl`, `tr`, legacy `.ClassifiedDetailBasicDetails-*`).
- `tests/` runs against synthetic fixtures; there is no network access in tests.
- `.github/workflows/ci.yml` runs ruff and pytest. `publish.yml` runs tests, then pushes a multi-arch image to `ghcr.io/koderi-dp/njuskalo-scraper-mcp`.

## Constraints

- Njuskalo blocks non-HR and datacenter IPs. Never add a CI step that hits the live site.
- The old Apify scraper from roshtarg-cpu had **no license**, so it was removed and none of its code is reused. Only facts were kept: the `__INITIAL_STATE__` location and the `price[from]` / `price[to]` / `page` / `keywords` parameters.
- Keep requests polite: at least 1.5 s apart, at most 5 pages per search.

## Unverified against the live site (do these first, from a Croatian IP)

1. Run `search_cars` and confirm the listing field names (`title`, `priceFormatted`, `location`, `abstracts`, `titleSlug`, `categorySlug`) and the constructed URLs `/{cat}/{slug}-oglas-{id}`.
2. Save a real search page and a real ad page into `tests/fixtures/` and add tests for them.
3. Check which `get_car_details` extraction path actually fires on real ad pages (state, JSON-LD, or table) and tighten the seller and price selectors.
4. Find the real query parameter names for year, mileage, and fuel filters. They could become first-class `search_cars` arguments; until then, users pass `search_url` or `extra_filters`.
5. Check whether plain curl_cffi gets through Radware from a home IP, or whether the Playwright fallback is needed.
