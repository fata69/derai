FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN addgroup --system discovery && adduser --system --ingroup discovery discovery \
 && install -d -o discovery -g discovery /var/lib/discovery
COPY discovery.py ./
USER discovery
CMD ["python", "discovery.py"]
