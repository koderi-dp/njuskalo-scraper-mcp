# njuskalo-mcp

An MCP server that searches used cars on [Njuskalo.hr](https://www.njuskalo.hr/auti) so Claude can compare the listings and pick the best one for you, for example "the best reliable car under €5,000 near Zagreb."

The server only fetches and structures listings. Claude does the judging, using full specs and the seller's description.

## Tools

| Tool | What it does |
|---|---|
| `get_search_filters` | Reads the live filter form on `/auti` and returns every filter with its option IDs and Croatian labels, plus the brand categories (or a brand's models when given `brand`). |
| `search_cars` | Searches `/auti` with `keywords`, `max_price` (default 5000), `min_price`, `min_year`, `max_km`, a brand/model `category`, readable `filters` (option labels or IDs, ranges, checkboxes), an optional pasted `search_url` with filters already set on the site, and up to 5 `pages`. Returns compact summaries: title, price, location, card info (year, km), and URL. |
| `get_car_details` | Takes up to 10 ad URLs or IDs from a search and returns specs, price, seller, and description. |

**Tip:** set other filters like fuel, gearbox, or region on njuskalo.hr itself, copy the URL, and give it to Claude as `search_url`. Price, year, km and keywords are added on top.

## Important: where it can run

Njuskalo uses Radware/ShieldSquare bot protection and **only serves Croatian, non-datacenter IPs**. Run the server from a home connection in Croatia, or set `NJUSKALO_PROXY` to a Croatian residential proxy. A GitHub Actions runner or a cloud VM will be blocked, which is why CI only builds and tests the server and publishes an image; it never scrapes.

## Run locally (stdio)

```bash
pip install git+https://github.com/koderi-dp/njuskalo-scraper-mcp
njuskalo-mcp            # stdio, for Claude Desktop / Claude Code
```

Claude Code:

```bash
claude mcp add njuskalo -- njuskalo-mcp
```

Claude Desktop (`claude_desktop_config.json`):

```json
{ "mcpServers": { "njuskalo": { "command": "njuskalo-mcp" } } }
```

## Run as a remote server (Docker)

Every push to `main` and every `v*` tag publishes `ghcr.io/koderi-dp/njuskalo-scraper-mcp`.

```bash
docker run -d --name njuskalo-mcp -p 8000:8000 \
  -e MCP_AUTH_TOKEN=change-me \
  ghcr.io/koderi-dp/njuskalo-scraper-mcp:latest
```

The MCP endpoint is `http://<host>:8000/mcp`, using streamable HTTP with header `Authorization: Bearer <MCP_AUTH_TOKEN>`. Put it behind HTTPS (reverse proxy) before exposing it outside your LAN.

```bash
claude mcp add --transport http njuskalo http://<host>:8000/mcp \
  --header "Authorization: Bearer change-me"
```

### Publish it from home with a Cloudflare Tunnel

Njuskalo blocks datacenter IPs, so the most reliable setup is an always-on machine on a Croatian home connection (PC, NAS or Raspberry Pi). `docker-compose.yml` runs the server next to `cloudflared`, which gives it a public HTTPS address without opening router ports.

1. Put a domain on Cloudflare (free plan). In Zero Trust → Networks → Tunnels, create a `cloudflared` tunnel and copy its token.
2. Add a public hostname to the tunnel, e.g. `njuskalo.example.com`, with service `http://njuskalo-mcp:8000`.
3. `cp .env.example .env`, then set `TUNNEL_TOKEN` and a long random `MCP_SECRET_PATH` (`openssl rand -hex 24`).
4. `docker compose up -d`

Your MCP URL is `https://njuskalo.example.com/<MCP_SECRET_PATH>/mcp`. In claude.ai, add it under Settings → Connectors → Add custom connector. claude.ai can't send custom headers, so the secret path is what keeps strangers out: treat the whole URL like a password.

To build a larger image with the Playwright browser fallback, use `docker build --build-arg WITH_BROWSER=true .`.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `NJUSKALO_PROXY` | none | Proxy URL, e.g. `http://user:pass@hr-proxy:port`. Cloud IPs get challenged by Njuskalo's bot protection almost at once; `deploy/home-proxy/` runs a proxy on your home connection for this |
| `NJUSKALO_MIN_DELAY` | `1.5` | Seconds between requests |
| `NJUSKALO_CACHE_TTL` | `3600` | Page cache lifetime, in seconds |
| `MCP_AUTH_TOKEN` | none | Bearer token required in HTTP mode |
| `MCP_SECRET_PATH` | none | Serve only under `/<secret>/mcp` (for clients that can't send headers) |
| `MCP_TRANSPORT` | `stdio` | Set to `http` to serve HTTP (the Docker image does this) |
| `HOST` / `PORT` | `127.0.0.1` / `8000` | HTTP bind address |

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

Parser tests use synthetic fixtures in `tests/fixtures/`. When Njuskalo changes its markup, save a real page there and add a test for it.

Be polite: keep the delay, keep page counts low, and respect Njuskalo's terms.
