FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations
RUN pip install --upgrade pip && pip install .

RUN mkdir -p /app/var/raw /app/var/models
VOLUME ["/app/var"]

EXPOSE 8080
CMD ["sh", "-c", "alembic upgrade head && mailmind serve --host 0.0.0.0 --port 8080"]
