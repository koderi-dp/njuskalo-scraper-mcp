FROM python:3.12-slim

ARG WITH_BROWSER=false
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=http HOST=0.0.0.0 PORT=8000

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir . \
 && if [ "$WITH_BROWSER" = "true" ]; then \
      pip install --no-cache-dir ".[browser]" && playwright install --with-deps chromium; \
    fi \
 && useradd --create-home app
USER app

EXPOSE 8000
CMD ["njuskalo-mcp"]
