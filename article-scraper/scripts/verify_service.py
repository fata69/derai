"""Verify running Docker service, optionally compare to the unmodified upstream oracle."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
REV = "8596ede07e9f30573013637636c1d716f2e432fc"


def request(base, key, method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    call = Request(base + path, data, headers={"X-API-Key": key, "Content-Type": "application/json"},
                   method=method)
    try:
        with urlopen(call, timeout=45) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.load(exc)


def wait(base, key, job_id):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        status, job = request(base, key, "GET", "/v1/jobs/" + job_id + "?include_excluded=true")
        assert status == 200, (status, job)
        if job["status"] in {"failed", "completed"}:
            return job
        time.sleep(0.25)
    raise AssertionError("Job did not finish within 120 seconds")


def env_values():
    return dict(line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines()
                if "=" in line and not line.startswith("#"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:18011")
    parser.add_argument("--query", default="Indonesia")
    parser.add_argument("--oracle-url")
    args = parser.parse_args()
    env = env_values()
    key = env["SCRAPER_API_KEY"]
    base = args.base_url
    report = {"upstream": REV, "checks": [], "query": args.query}

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        report["checks"].append(name)

    # All public response models, SQL migrations and extraction logic are unchanged.
    upstream = ROOT / ".runtime" / "upstream"
    for folder in ("src", "migrations", "internal/extractor", "internal/domain", "internal/store"):
        delta = subprocess.check_output(["git", "-C", str(upstream), "diff", "HEAD", "--", folder])
        check("upstream_unchanged:" + folder, delta == b"")
    check("ready_postgresql_schema_4", request(base, key, "GET", "/ready") ==
          (200, {"status": "ready", "database": "postgresql", "schema_version": 4}))
    check("auth_required", request(base, "", "GET", "/v1/jobs")[0] == 401)
    check("invalid_query_422", request(base, key, "POST", "/v1/search/jobs", {"query": "x"})[0] == 422)
    check("invalid_job_id_422", request(base, key, "GET", "/v1/jobs/invalid")[0] == 422)
    check("unknown_job_404", request(base, key, "GET", "/v1/jobs/" + "0" * 32)[0] == 404)

    status, accepted = request(base, key, "POST", "/v1/search/jobs",
                               {"query": args.query, "max_articles": 3, "max_pages": 1})
    check("keyword_accepted_202", status == 202 and accepted["status"] == "queued")
    job = wait(base, key, accepted["job_id"])
    check("keyword_completed_with_articles", job["status"] == "completed" and job["succeeded"] > 0)
    articles = [item["article"] for item in job["items"] if item.get("article")]
    report["live_keyword"] = {k: job[k] for k in ("job_id", "total", "succeeded", "failed")}
    report["article_urls"] = [x["canonical_url"] for x in articles]
    required = {"status", "source_url", "final_url", "canonical_url", "domain", "title", "author",
                "published_at", "modified_at", "publication_time", "modification_time", "source",
                "section", "description", "image_url", "content", "word_count", "content_hash",
                "robots_status", "fetched_at"}
    check("exact_article_field_names", all(set(a) == required for a in articles))
    check("content_hash_sha256", all(hashlib.sha256(a["content"].encode()).hexdigest() == a["content_hash"]
                                     for a in articles))

    # Prove real DB round-trip for exactly the public article object returned by GET.
    job_id = UUID(job["job_id"])
    query = f"SELECT article_json FROM job_items WHERE job_id='{job_id}'::uuid AND status='success' ORDER BY position;"
    stored = subprocess.check_output(["docker", "compose", "exec", "-T", "db", "psql", "-U",
                                      "scraper_migrator", "-d", "article_scraper", "-Atc", query],
                                     cwd=ROOT, encoding="utf-8")
    # Upstream Go writes nanoseconds; FastAPI serializes datetimes at microseconds.
    def comparable_article(article):
        return {**article, "fetched_at": datetime.fromisoformat(article["fetched_at"])}

    check("postgres_article_roundtrip", [comparable_article(json.loads(line))
                                         for line in stored.split("\n") if line] ==
          [comparable_article(article) for article in articles])

    selected = articles[0]["source_url"]
    status, sync_article = request(base, key, "POST", "/v1/articles/scrape", {"url": selected})
    check("single_url_200_same_shape", status == 200 and set(sync_article) == required)
    status, rejected = request(base, key, "POST", "/v1/jobs", {"urls": ["https://127.0.0.1/private"]})
    unsafe = wait(base, key, rejected["job_id"])
    check("ssrf_blocked_by_worker", status == 202 and unsafe["failed"] == 1
          and unsafe["items"][0]["error_code"] == "unsafe_url")

    # Historical controls and exclusion reporting remain in upstream.
    historical_body = {"query": args.query, "start_date": "2020-01-01", "end_date": "2020-01-31",
                       "max_articles": 1, "max_pages": 1}
    status, historical = request(base, key, "POST", "/v1/search/jobs", historical_body)
    check("historical_accepted_with_search_id", status == 202 and bool(historical["search_id"]))
    search_id = historical["search_id"]
    for _ in range(120):
        status, progress = request(base, key, "GET", "/v1/search/runs/" + search_id)
        if progress["status"] in {"discovery_complete", "failed"}:
            break
        time.sleep(0.5)
    check("historical_checkpoint_complete", status == 200 and progress["status"] == "discovery_complete")
    status, completed = request(base, key, "POST", "/v1/search/runs/" + search_id + "/continue")
    check("completed_continue_creates_no_new_job", status == 202 and completed["status"] == "discovery_complete"
          and completed["job_id"] is None)

    if args.oracle_url:
        oracle_key = os.environ["ORACLE_SCRAPER_API_KEY"]
        _, our_spec = request(base, key, "GET", "/openapi.json")
        _, old_spec = request(args.oracle_url, oracle_key, "GET", "/openapi.json")
        check("openapi_exact_equality", our_spec == old_spec)
        status, oracle = request(args.oracle_url, oracle_key, "POST", "/v1/articles/scrape", {"url": selected})
        check("oracle_single_url_200", status == 200)
        # Both fetch the live URL; retrieval time is the only expected varying field.
        ours = {k: v for k, v in sync_article.items() if k != "fetched_at"}
        old = {k: v for k, v in oracle.items() if k != "fetched_at"}
        check("live_article_matches_oracle_except_fetched_at", ours == old)
        report["oracle_article_url"] = selected

    report["result"] = "passed"
    output = ROOT / "artifacts"
    output.mkdir(exist_ok=True)
    (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "example-article.json").write_text(json.dumps(articles[0], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
