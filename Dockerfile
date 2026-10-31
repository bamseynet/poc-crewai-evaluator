# One image serves the API and the built web UI, so there is a single thing to deploy.

FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS app
RUN pip install --no-cache-dir uv==0.13.6
WORKDIR /app
ENV UV_LINK_MODE=copy UV_NO_CACHE=1
# Dependencies first, so that source changes do not reinstall them.
COPY pyproject.toml uv.lock README.md .python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev
COPY --from=web /web/dist ./web/dist

RUN useradd --create-home --uid 1000 app
USER app
ENV PATH=/app/.venv/bin:$PATH WEB_DIST=/app/web/dist PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "policy_drafter.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "10"]
