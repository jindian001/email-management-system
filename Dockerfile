FROM node:22-alpine AS web
WORKDIR /app/web
RUN npm install -g pnpm@12
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
# vite outDir = ../src/mailmind/static，产物落到 /app/src/mailmind/static
RUN pnpm build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations
COPY --from=web /app/src/mailmind/static ./src/mailmind/static
RUN pip install --upgrade pip && pip install .

RUN mkdir -p /app/var/raw /app/var/models
VOLUME ["/app/var"]

EXPOSE 8080
CMD ["sh", "-c", "alembic upgrade head && mailmind serve --host 0.0.0.0 --port 8080"]
