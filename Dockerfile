# Premier Analytics: one container serving the API, WebSocket stream, MCP tools and the React UI.

# ---- build the frontend ----
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- runtime ----
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml ./
COPY src/ src/
RUN pip install ".[llm]" && useradd --create-home app
COPY --from=web /web/dist web/dist
USER app
ENV PA_STATIC=/app/web/dist PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health')"
CMD ["sh", "-c", "uvicorn premier_analytics.server:app --host 0.0.0.0 --port ${PORT} --timeout-graceful-shutdown 5"]
