#!/usr/bin/env bash
# Compare the original DERAI image and the new scheduler using disposable PostgreSQL.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
repo=$PWD
legacy=${1:?Usage: bash scripts/verify-reference.sh LEGACY_IMAGE CANDIDATE_IMAGE}
candidate=${2:?Usage: bash scripts/verify-reference.sh LEGACY_IMAGE CANDIDATE_IMAGE}
tick='2026-11-13T11:37:20+07:00'
utc_tick='2026-11-13T04:37:20Z'
db_name="derai-reference-pg-$$"
fixture_pw=reference-fixture-only
runtime=${DERAI_TEST_OCI_RUNTIME:-runc}
work=$(mktemp -d)
db_container=''
cleanup() {
    if [[ -n "$db_container" ]]; then docker rm -f -v "$db_container" >/dev/null; fi
    rm -f -- "$work/old.json" "$work/new.json"
    rmdir -- "$work"
}
trap cleanup EXIT
docker image inspect "$legacy" "$candidate" >/dev/null
db_container=$(docker create --runtime "$runtime" --name "$db_name" --network none \
    --tmpfs /var/lib/postgresql/data:rw,size=512m -e "POSTGRES_PASSWORD=$fixture_pw" postgres:17)
docker start "$db_container" >/dev/null

for _ in $(seq 1 60); do
    if docker exec "$db_container" pg_isready -h 127.0.0.1 -U postgres >/dev/null; then break; fi
    sleep 1
done

sql() {
    docker exec -i "$db_container" psql -X -qAt -v ON_ERROR_STOP=1 -U postgres "$@"
}
sql -d postgres <<'SQL'
CREATE ROLE derai_app NOLOGIN;
CREATE ROLE derai_worker LOGIN PASSWORD 'reference-fixture-only';
CREATE DATABASE derai_reference_old;
CREATE DATABASE derai_reference_new;
SQL

run() {
    local image=$1 database=$2
    shift 2
    docker run --runtime "$runtime" --rm -i --network "container:$db_container" --entrypoint python \
        -e "DATABASE_URL=postgresql+psycopg://derai_worker@127.0.0.1:5432/$database" \
        -e "PGPASSWORD=$fixture_pw" -e SOCIAL_COLLECTION_ENABLED=true \
        -e "CONNECTOR_ARTICLE_MAX_PAGES=${MAX_PAGES:-1}" \
        --mount "type=bind,source=$repo/scripts/reference-parity.py,target=/fixture/reference-parity.py,readonly" \
        "$image" "$@"
}

for database in derai_reference_old derai_reference_new; do
    docker run --runtime "$runtime" --rm -i --network "container:$db_container" --entrypoint python \
        -e "FIXTURE_DB=$database" -e "PGPASSWORD=$fixture_pw" "$legacy" - <<'PY'
import os
import runpy
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

database = os.environ['FIXTURE_DB']
assert database in {'derai_reference_old', 'derai_reference_new'}
engine = create_engine(f'postgresql+psycopg://postgres@127.0.0.1:5432/{database}')
with engine.begin() as conn:
    assert conn.execute(text('SELECT current_database(), host(inet_server_addr())')).one() == (database, '127.0.0.1')
    with Operations.context(MigrationContext.configure(conn)):
        runpy.run_path('/app/migrations/versions/0001_operational_rls.py')['upgrade']()
PY
    sql -d "$database" -f - < scripts/seed-local-db.sql
    sql -d "$database" -c "SELECT CASE WHEN relrowsecurity AND relforcerowsecurity THEN 'RLS active' ELSE 'RLS missing' END FROM pg_class WHERE oid='public.records'::regclass" | grep -Fx 'RLS active'
done

legacy_tick() { run "$legacy" derai_reference_old /fixture/reference-parity.py legacy-tick --at "$1"; }
new_tick() { run "$candidate" derai_reference_new -m derai_scheduler tick --at "$1"; }
expect() {
    local expected=$1 output
    shift
    output=$("$@")
    printf '%s\n' "$output"
    python3 -c 'import json, sys; assert json.loads(sys.argv[1])["processed"] == int(sys.argv[2])' "$output" "$expected"
}
compare() {
    local expected=$1 database name count
    for name in old new; do
        database="derai_reference_$name"
        count=$(sql -d "$database" -c "SELECT count(*) FROM public.records WHERE kind='job'")
        [[ "$count" == "$expected" ]]
        sql -d "$database" -c "SELECT json_agg(r ORDER BY idempotency_key) FROM public.records r WHERE kind='job'" > "$work/$name.json"
    done
    python3 scripts/compare-contracts.py "$work/old.json" "$work/new.json"
}

echo 'PRD fixture and same-hour UTC replay'
expect 4 legacy_tick "$tick"
expect 4 new_tick "$tick"
compare 4
python3 scripts/compare-contracts.py fixtures/expected-prd-jobs.json "$work/new.json"
expect 0 legacy_tick "$utc_tick"
expect 0 new_tick "$utc_tick"
for database in derai_reference_old derai_reference_new; do
    sql -d "$database" -c "UPDATE public.records SET status='failed' WHERE kind='job'"
done
expect 0 legacy_tick "$tick"
expect 0 new_tick "$tick"
compare 4

echo 'Partial pair and Unicode in a second tenant/workspace'
for database in derai_reference_old derai_reference_new; do
    sql -d "$database" <<'SQL'
DELETE FROM public.records WHERE kind='job' AND name='online-news' AND data::json->>'query'='TNI';
INSERT INTO public.records (id,tenant_id,workspace_id,kind,name,data,status,created_at)
VALUES ('11111111-1111-4111-8111-111111111112','22222222-2222-4222-8222-222222222223',
        '33333333-3333-4333-8333-333333333334','topic','Unicode','{"keywords":[" Straße ","STRASSE"]}',
        'ready','2026-11-13T04:00:00+00:00');
SQL
done
expect 3 legacy_tick "$tick"
expect 3 new_tick "$tick"
compare 6

echo 'Original ingestion on new jobs'
sql -d derai_reference_new <<'SQL'
TRUNCATE public.records;
SQL
sql -d derai_reference_new -f - < scripts/seed-local-db.sql
sql -d derai_reference_new -c "UPDATE public.records SET data='{\"keywords\":[\"TNI\"]}' WHERE kind='topic'"
MAX_PAGES=3 expect 2 new_tick "$tick"
expect 2 run "$legacy" derai_reference_new /fixture/reference-parity.py verify-ingestion --at "$tick"
