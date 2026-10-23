FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=http HOST=0.0.0.0 PORT=8000

WORKDIR /app
# Dependencies get their own layer, so a code-only change reuses it from the cache.
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" \
      > requirements.txt \
 && pip install --no-cache-dir -r requirements.txt \
 && useradd --create-home app
COPY README.md ./
COPY src ./src
RUN pip install --no-cache-dir --no-deps .
USER app

EXPOSE 8000
CMD ["njuskalo-mcp"]
