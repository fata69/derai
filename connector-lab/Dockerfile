FROM python:3.14-slim-trixie

ENV HOME=/tmp \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt playwright==1.65.1 \
    && python -m playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/* \
    && chmod -R a+rX /opt/playwright

COPY connector_lab.py .
USER 10001:10001
ENTRYPOINT ["python", "/app/connector_lab.py"]
