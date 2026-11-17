#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v api_pw="$ARTICLE_DB_API_PASSWORD" -v worker_pw="$ARTICLE_DB_WORKER_PASSWORD" <<'SQL'
CREATE ROLE scraper_api LOGIN PASSWORD :'api_pw';
CREATE ROLE scraper_worker LOGIN PASSWORD :'worker_pw';
GRANT CONNECT ON DATABASE article_scraper TO scraper_api, scraper_worker;
GRANT USAGE ON SCHEMA public TO scraper_api, scraper_worker;
SQL
