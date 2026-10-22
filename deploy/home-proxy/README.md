# Home proxy for the Njuskalo MCP server

Njuskalo's bot protection challenges datacenter IPs almost immediately, so a
server on Render (or any cloud) needs its Njuskalo traffic to leave from a
home connection in Croatia. This folder runs a tiny forward proxy at home that
does exactly that, and nothing else:

- password-protected (`PROXY_USER` / `PROXY_PASSWORD`)
- forwards **only** to `njuskalo.hr` and its subdomains; everything else is refused
- HTTPS passes through untouched (the proxy can't read the traffic)

## Set up

1. On an always-on machine at home (PC, NAS, Raspberry Pi):
   ```bash
   cd deploy/home-proxy
   cp .env.example .env     # set PROXY_PASSWORD (openssl rand -hex 24)
   docker compose up -d --build
   ```
2. On your router, forward TCP port `8888` to that machine.
3. Find your public address: `curl ifconfig.me`. Home IPs change now and then,
   so use a free dynamic-DNS name (DuckDNS, No-IP) if yours does.
4. On the MCP server (Render → Environment), set:
   ```
   NJUSKALO_PROXY=http://njuskalo:<PROXY_PASSWORD>@<your-home-address>:8888
   ```
   Render redeploys by itself; then run one search through the connector.

## Check it

From anywhere outside your network:

```bash
curl -x http://njuskalo:<password>@<your-home-address>:8888 -sI https://www.njuskalo.hr/robots.txt   # 200
curl -x http://njuskalo:<password>@<your-home-address>:8888 -sI https://example.com                   # 403 refused
curl -x http://<your-home-address>:8888 -sI https://www.njuskalo.hr/robots.txt                       # 407 needs login
```

`docker compose logs -f` shows each connection.
