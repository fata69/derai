"""Copy terminal engine job history while preserving the new service's own rows."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import subprocess

TABLES = ("commands", "search_runs", "jobs", "job_items")


def query(container, sql):
    return subprocess.check_output(
        ["docker", "exec", "-i", container, "psql", "-XqAt", "-v", "ON_ERROR_STOP=1",
         "-U", "scraper_migrator", "-d", "article_scraper"], input=sql, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("export", "import"))
    parser.add_argument("--container", required=True)
    parser.add_argument("--file", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "export":
        pairs = [f"'{table}',(SELECT coalesce(jsonb_agg(to_jsonb(t)),'[]'::jsonb) FROM {table} t)"
                 for table in TABLES]
        raw = query(args.container, "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\n"
                    "SELECT jsonb_build_object(" + ",".join(pairs) + ");\nCOMMIT;\n")
        data = json.loads(raw)
        for table in ("commands", "jobs", "job_items"):
            if any(row["status"] in ("queued", "running") for row in data[table]):
                raise SystemExit("Ada pekerjaan aktif; tunggu sebelum menyalin history")
        if any(row["status"] == "running" for row in data["search_runs"]):
            raise SystemExit("Ada discovery aktif; tunggu sebelum menyalin history")
        fd = os.open(args.file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
        print(json.dumps({"exported": {t: len(data[t]) for t in TABLES}}))
        return

    data = json.loads(args.file.read_text(encoding="utf-8"))
    if set(data) != set(TABLES) or any(not isinstance(data[t], list) for t in TABLES):
        raise SystemExit("Snapshot history tidak valid")
    for table in ("commands", "jobs", "job_items"):
        if any(row["status"] in ("queued", "running") for row in data[table]):
            raise SystemExit("Snapshot berisi pekerjaan aktif")
    encoded = base64.b64encode(json.dumps(data).encode()).decode("ascii")
    sql = ["BEGIN; SET LOCAL standard_conforming_strings=on;",
           "CREATE TEMP TABLE snapshot(j jsonb) ON COMMIT DROP;",
           f"INSERT INTO snapshot VALUES (convert_from(decode('{encoded}','base64'),'UTF8')::jsonb);"]
    for table in TABLES:
        if not data[table]:
            continue
        fields = list(data[table][0])
        if any(set(row) != set(fields) for row in data[table]):
            raise SystemExit("Kolom snapshot tidak konsisten")
        if any(not name.replace("_", "").isalnum() for name in fields):
            raise SystemExit("Nama kolom snapshot tidak valid")
        if table == "job_items":
            fields.remove("id")  # Internal serials are not public job identifiers.
        columns = ",".join('"' + name + '"' for name in fields)
        source = f"jsonb_populate_recordset(NULL::public.{table},(SELECT j->'{table}' FROM snapshot))"
        sql.append(f"INSERT INTO public.{table} ({columns}) SELECT {columns} FROM {source} ON CONFLICT DO NOTHING;")
        join = "live.job_id=src.job_id AND live.position=src.position" if table == "job_items" else "live.id=src.id"
        compare = "to_jsonb(live)-'id' IS DISTINCT FROM to_jsonb(src)-'id'" if table == "job_items" else "to_jsonb(live) IS DISTINCT FROM to_jsonb(src)"
        sql.append(f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM {source} src LEFT JOIN public.{table} live ON {join} "
                   f"WHERE live.id IS NULL OR {compare}) THEN RAISE EXCEPTION 'History mismatch: {table}'; END IF; END $$;")
    sql.extend(["COMMIT;", "SELECT 'history_verified';"])
    result = query(args.container, "\n".join(sql))
    if "history_verified" not in result:
        raise SystemExit("Import history belum terverifikasi")
    print(json.dumps({"verified": {t: len(data[t]) for t in TABLES}}))


if __name__ == "__main__":
    main()
