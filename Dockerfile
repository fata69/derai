FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml README.md constraints.txt ./
COPY src ./src
RUN pip install --no-cache-dir -c constraints.txt . \
    && useradd --uid 10001 --create-home scheduler

FROM base AS tests
RUN pip install --no-cache-dir -c constraints.txt '.[dev]'
COPY tests ./tests
USER scheduler
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]

FROM base AS runtime
USER scheduler
CMD ["derai-scheduler", "run"]
