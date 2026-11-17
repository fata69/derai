"""Run real discovery against locally served HTTP dependency fixtures."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from discovery import Discovery, DiscoveryError, Settings

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://127.0.0.1:18732/sources")
args = parser.parse_args()

def transport(url, *, payload=None, headers=None):
    target = args.base_url + urlsplit(url).path
    req = Request(target, data=json.dumps(payload).encode() if payload is not None else None,
                  headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urlopen(req, timeout=3) as response:
            return response.read()
    except (HTTPError, OSError):
        raise DiscoveryError("Fixture HTTP failure") from None

with tempfile.TemporaryDirectory() as directory:
    settings = Settings(("https://sources.example/rss",), ("news.example",),
                        str(Path(directory) / "index.sqlite3"), "compatible", "fixture",
                        "fixture-not-a-secret", "https://sources.example/v1")
    result = Discovery(settings, transport).search("Banjir Jakarta")
    assert result == {"organic_results": [{"link": "https://news.example/berita/real"}]}, result
    print(json.dumps({"simulation": "passed", "rss_and_llm_http_exercised": True}))
