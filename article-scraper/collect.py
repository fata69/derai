"""Cron CLI: article URL -> exact ArticleResponse -> DERAI HTTP ingestion."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

shared = Path(__file__).resolve().parents[1] / "connector-lab"
staged = Path(__file__).resolve().parent / "connector-lab-candidate"
sys.path.insert(0, str(shared if shared.is_dir() else staged))
from derai_ingest import IngestError, NoRedirect, persist_to_derai


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="URL artikel publik (mode ini untuk berita)")
    parser.add_argument("--persist", action="store_true", help="kirim lewat API backend DERAI")
    parser.add_argument("--topic-id")
    parser.add_argument("--tenant-id")
    parser.add_argument("--workspace-id")
    parser.add_argument("--idempotency-key")
    parser.add_argument("--base-url", default=os.getenv("ARTICLE_BASE_URL", "http://127.0.0.1:18011"))
    args = parser.parse_args()
    if args.persist and not all((args.topic_id, args.tenant_id, args.workspace_id, args.idempotency_key)):
        parser.error("--persist memerlukan --topic-id, --tenant-id, --workspace-id, --idempotency-key")
    try:
        key = os.getenv("SCRAPER_API_KEY", "")
        if not key:
            parser.error("Isi SCRAPER_API_KEY pada environment")
        req = Request(args.base_url.rstrip("/") + "/v1/articles/scrape",
                      data=json.dumps({"url": args.url}).encode(),
                      headers={"Content-Type": "application/json", "X-API-Key": key})
        with build_opener(NoRedirect()).open(req, timeout=45) as response:
            result = json.load(response)
        if args.persist:
            result = persist_to_derai(os.environ, topic_id=args.topic_id, tenant_id=args.tenant_id,
                                      workspace_id=args.workspace_id, platform="online_news",
                                      content=result, idempotency_key=args.idempotency_key)
        print(json.dumps(result, ensure_ascii=False))
    except (IngestError, HTTPError, URLError, OSError, ValueError) as exc:
        # Never include provider response bodies, token values, or exception URLs.
        print(str(exc) if isinstance(exc, IngestError) else "Pengambilan artikel gagal", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
