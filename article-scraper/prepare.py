"""Stage the pinned upstream source for local Docker builds."""

import argparse
import os
from pathlib import Path
import secrets
import subprocess


ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT / ".runtime" / "upstream"
SOURCE = "https://github.com/aqshaaqso/article-scraper-engine-api.git"
REV = "8596ede07e9f30573013637636c1d716f2e432fc"


def git(*args: str) -> str:
    return subprocess.check_output(["git", "-C", str(UPSTREAM), *args], text=True).strip()


def prepare() -> None:
    UPSTREAM.mkdir(parents=True, exist_ok=True)
    if not (UPSTREAM / ".git").is_dir():
        if any(UPSTREAM.iterdir()):
            raise SystemExit(f"Direktori build bukan checkout kosong: {UPSTREAM}")
        git("init", "-q")
        git("config", "core.autocrlf", "false")
        git("remote", "add", "origin", SOURCE)
    if git("remote", "get-url", "origin") != SOURCE:
        raise SystemExit("Remote checkout build tidak sesuai sumber kontrak")
    head = subprocess.run(
        ["git", "-C", str(UPSTREAM), "rev-parse", "--verify", "HEAD"],
        text=True, capture_output=True, check=False,
    ).stdout.strip()
    if head and head != REV:
        raise SystemExit("Checkout build berada di revisi lain; gunakan direktori build baru")
    if not head:
        git("fetch", "-q", "--depth=1", "origin", REV)
        git("checkout", "-q", "--detach", REV)

    diff = ROOT / "discovery.patch"
    check = ["apply", "--check", str(diff)]
    # Verify the patch and reject any differences besides that patch.
    if not git("status", "--porcelain"):
        git(*check)
        git("apply", str(diff))
    elif subprocess.run(
        ["git", "-C", str(UPSTREAM), "apply", "--check", "--reverse", str(diff)],
        capture_output=True, check=False,
    ).returncode:
        raise SystemExit("Checkout build berubah; gunakan direktori build baru")
    if git("status", "--porcelain") != "M cmd/worker/main.go\n M internal/search/search.go":
        raise SystemExit("Checkout build memiliki perubahan tambahan")
    # Compare all working tree changes with exactly the pinned patch.
    expected = subprocess.check_output(
        ["git", "-C", str(UPSTREAM), "diff", "--no-ext-diff", "--no-color", "--full-index", "HEAD"],
        text=True,
    ).strip()
    if expected != diff.read_text(encoding="utf-8").strip():
        raise SystemExit("Isi checkout build tidak cocok dengan patch yang dipatok")
    print(f"Upstream {REV} + discovery.patch siap di {UPSTREAM}")


def init_env() -> None:
    path = ROOT / ".env"
    settings = (ROOT / ".env.example").read_text(encoding="utf-8")
    for name in ("SCRAPER_API_KEY", "ARTICLE_DB_MIGRATOR_PASSWORD",
                 "ARTICLE_DB_API_PASSWORD", "ARTICLE_DB_WORKER_PASSWORD"):
        settings = settings.replace(f"{name}=\n", f"{name}={secrets.token_hex(24)}\n")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(".env sudah ada; dipertahankan")
        return
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(settings)
    print(".env dibuat dengan kredensial lokal baru")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init-env", action="store_true", help="buat .env bila belum ada")
    args = parser.parse_args()
    prepare()
    if args.init_env:
        init_env()
