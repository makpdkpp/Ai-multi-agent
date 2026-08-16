FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY pyproject.toml ./
COPY src ./src
RUN pip install --prefix=/install .

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/home/app/.local/bin:$PATH

RUN groupadd --system app && useradd --system --gid app --create-home app
WORKDIR /app

COPY --from=builder /install /usr/local
COPY alembic.ini ./
COPY migrations ./migrations

USER app
EXPOSE 8000

CMD ["uvicorn", "agentdesk_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.12-slim AS test
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY tests ./tests
COPY migrations ./migrations
RUN pip install -e ".[dev]"
CMD ["pytest"]
