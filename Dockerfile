FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml README.md constraints.txt ./
COPY src ./src
RUN pip install --no-cache-dir -c constraints.txt . \
    && useradd --uid 10001 --create-home scheduler

USER scheduler
CMD ["derai-scheduler", "run"]
