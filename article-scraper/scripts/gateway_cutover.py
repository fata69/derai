"""Scoped gateway cutover on the existing PopOS host; keep its binary/social config."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path.home() / "konektor-medsos"
STATE = ROOT / ".deploy" / "derai-replacement-20261117"
BIN = ROOT / "bin" / "derai-connector-linux-amd64"
PID = ROOT / ".deploy" / "server.pid"
OLD = ("derai-article-middleware-v06", "derai-article-worker-v06",
       "derai-article-postgres-v06", "article-scraper-engine-api-article-scraper-1")


def load_env():
    env = dict(os.environ)
    env.update(dict(line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines()
                    if "=" in line and not line.startswith("#")))
    return env


def request(base, key, path, body=None):
    req = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                  headers={"X-API-Key": key, "Content-Type": "application/json"})
    with urlopen(req, timeout=45) as response:
        return response.status, json.load(response)


def stop(pid):
    proc = Path(f"/proc/{pid}")
    if not proc.exists():
        return
    if (proc / "exe").resolve() != BIN.resolve():
        raise RuntimeError("Gateway PID identity mismatch")
    os.kill(pid, signal.SIGTERM)
    for _ in range(100):
        if not proc.exists() or (proc / "stat").read_text().split()[2] == "Z":
            return
        time.sleep(0.1)
    raise RuntimeError("Gateway did not stop gracefully")


def start(env, name):
    with (STATE / (name + ".log")).open("ab") as log:
        child = subprocess.Popen([str(BIN)], cwd=ROOT, env=env, stdout=log, stderr=log,
                                 start_new_session=True)
    host = "http://" + env["LISTEN_ADDR"]
    for _ in range(60):
        try:
            _, health = request(host, env["CONNECTOR_API_KEY"], "/health")
            if child.poll() is None and health.get("version") == "0.6.0":
                return child.pid, host
        except OSError:
            pass
        if child.poll() is not None:
            break
        time.sleep(0.2)
    if child.poll() is None:
        stop(child.pid)
    raise RuntimeError("Gateway start failed; see private log")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("stage", "promote", "rollback"))
    args = parser.parse_args()
    os.umask(0o077)
    STATE.mkdir(mode=0o700, exist_ok=True)
    env = load_env()
    access = json.loads((STATE / "engine-access.json").read_text())
    base = "http://" + env["LISTEN_ADDR"]
    if args.mode == "stage":
        if (STATE / "promoted.json").exists():
            raise RuntimeError("Already promoted; inspect status first")
        if not (STATE / "gateway.env").exists():
            shutil.copy2(ROOT / ".env", STATE / "gateway.env")
            state = {"binary_sha256": hashlib.sha256(BIN.read_bytes()).hexdigest(),
                     "old_gateway_pid": int(PID.read_text()),
                     "old_containers": json.loads(subprocess.check_output(["docker", "inspect", *OLD]))}
            (STATE / "before.json").write_text(json.dumps(state))
            (STATE / "all-before.json").write_text(subprocess.check_output(
                ["docker", "ps", "--no-trunc", "--format", "{{.Names}} {{.ID}}"], text=True))
        candidate = {**env, "LISTEN_ADDR": "127.0.0.1:18088",
                     "ARTICLE_SCRAPER_BASE_URL": access["base_url"],
                     "ARTICLE_SCRAPER_API_KEY": access["api_key"]}
        pid, staged_base = start(candidate, "stage")
        try:
            key = env["CONNECTOR_API_KEY"]
            before = request(base, key, "/api/v1/capabilities")[1]
            after = request(staged_base, key, "/api/v1/capabilities")[1]
            assert before == after, "Gateway capabilities changed"
            assert request(staged_base, key, "/api/v1/articles/ready")[0] == 200
            code, accepted = request(staged_base, key, "/api/v1/articles/search/jobs",
                                     {"query": "Indonesia", "max_articles": 1, "max_pages": 1})
            assert code == 202 and accepted["result_url"] == "/api/v1/articles/jobs/" + accepted["job_id"]
            for _ in range(90):
                _, job = request(staged_base, key, accepted["result_url"])
                if job["status"] in ("completed", "failed"):
                    break
                time.sleep(0.5)
            assert job["status"] == "completed" and job["succeeded"] == 1
            sample = subprocess.check_output(["docker", "exec", "derai-article-postgres-v06", "psql",
                "-XqAt", "-U", "scraper_migrator", "-d", "article_scraper", "-c",
                "SELECT replace(id::text,'-','') FROM jobs WHERE succeeded>0 ORDER BY created_at DESC LIMIT 1"],
                text=True).strip()
            old = request(base, key, "/api/v1/articles/jobs/" + sample)[1]
            migrated = request(staged_base, key, "/api/v1/articles/jobs/" + sample)[1]
            # New versions add optional fields; all established fields must match.
            assert all(migrated.get(k) == v for k, v in old.items()), "History response changed"
            report = {"passed": True, "capabilities_unchanged": True,
                      "gateway_keyword_articles": 1, "history_job": sample,
                      "new_engine": access["base_url"]}
            (STATE / "stage-report.json").write_text(json.dumps(report, indent=2))
            print(json.dumps(report))
        finally:
            stop(pid)
    elif args.mode == "promote":
        assert json.loads((STATE / "stage-report.json").read_text())["passed"]
        assert not (STATE / "promoted.json").exists(), "Already promoted"
        before = json.loads((STATE / "before.json").read_text())
        assert hashlib.sha256(BIN.read_bytes()).hexdigest() == before["binary_sha256"]
        assert (ROOT / ".env").read_bytes() == (STATE / "gateway.env").read_bytes(), "Gateway config changed"
        rows = (ROOT / ".env").read_text().splitlines()
        replacements = {"ARTICLE_SCRAPER_BASE_URL": access["base_url"], "ARTICLE_SCRAPER_API_KEY": access["api_key"]}
        assert all(sum(row.startswith(k + "=") for row in rows) == 1 for k in replacements)
        rows = [row.split("=", 1)[0] + "=" + replacements[row.split("=", 1)[0]]
                if row.split("=", 1)[0] in replacements else row for row in rows]
        stop(int(PID.read_text()))
        try:
            tmp = ROOT / ".env.next"
            tmp.write_text("\n".join(rows) + "\n")
            tmp.chmod(0o600)
            os.replace(tmp, ROOT / ".env")
            new_env = load_env()
            pid, live = start(new_env, "live")
            PID.write_text(str(pid))
            assert request(live, new_env["CONNECTOR_API_KEY"], "/api/v1/articles/ready")[0] == 200
            report = {"promoted": True, "gateway_pid": pid, "article_engine": access["base_url"],
                      "gateway_binary_unchanged": True}
            (STATE / "promoted.json").write_text(json.dumps(report, indent=2))
            print(json.dumps(report))
        except Exception:
            if "pid" in locals():
                stop(pid)
            shutil.copy2(STATE / "gateway.env", ROOT / ".env")
            pid, _ = start(load_env(), "rollback")
            PID.write_text(str(pid))
            raise
    else:
        before = json.loads((STATE / "before.json").read_text())
        for container in before["old_containers"]:
            name = container["Name"].lstrip("/")
            policy = container["HostConfig"]["RestartPolicy"]["Name"] or "no"
            subprocess.run(["docker", "update", "--restart=" + policy, name], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["docker", "start", OLD[2], OLD[1], OLD[0], OLD[3]], check=True, stdout=subprocess.DEVNULL)
        stop(int(PID.read_text()))
        shutil.copy2(STATE / "gateway.env", ROOT / ".env")
        pid, _ = start(load_env(), "rollback")
        PID.write_text(str(pid))
        print(json.dumps({"rolled_back": True, "gateway_pid": pid}))


if __name__ == "__main__":
    main()
