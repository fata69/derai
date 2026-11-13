"""Validate an external DERAI Compose override without printing resolved secrets."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SERVICE = "collection-scheduler"
OVERRIDE = "derai-collection-scheduler/compose.derai.yaml"
IMAGE = "derai-collection-scheduler-fata:server"


def render(parent: Path, override: bool) -> dict:
    command = [
        "docker",
        "compose",
        "-p",
        "derai-platform",
        "--env-file",
        ".env",
        "--env-file",
        ".env.external",
        "-f",
        "compose.yaml",
        "-f",
        "compose.external.yaml",
    ]
    if override:
        command.extend(["-f", OVERRIDE])
    return json.loads(
        subprocess.run(
            [*command, "config", "--format", "json"],
            cwd=parent,
            capture_output=True,
            check=True,
        ).stdout
    )


def verify(parent: Path) -> None:
    original, candidate = render(parent, False), render(parent, True)
    old = original["services"].pop(SERVICE)
    new = candidate["services"].pop(SERVICE)
    if original != candidate:
        raise ValueError("Override changes more than the scheduler service")
    if new.get("image") != IMAGE or new.get("command") != ["derai-scheduler", "run"]:
        raise ValueError("Unexpected scheduler image or command")
    if new.get("volumes") or new.get("ports") or new.get("entrypoint"):
        raise ValueError("Scheduler override retains a volume, published port, or entrypoint")
    env = new.get("environment", {})
    if env != old.get("environment", {}) or not env.get("DATABASE_URL"):
        raise ValueError("Scheduler database or runtime environment changed")
    for key in ("networks", "extra_hosts", "restart", "depends_on"):
        if new.get(key) != old.get(key):
            raise ValueError(f"Scheduler {key} changed")
    if (
        new.get("build", {}).get("context") != str(parent / "derai-collection-scheduler")
        or new.get("build", {}).get("target") != "runtime"
        or new.get("runtime") != "runc"
    ):
        raise ValueError("Unexpected scheduler build target or CPU runtime")
    print(
        json.dumps(
            {
                "service": SERVICE,
                "image": IMAGE,
                "other_services_unchanged": True,
                "environment_unchanged": True,
                "verified": True,
            }
        )
    )


if __name__ == "__main__":
    try:
        verify(Path(__file__).resolve().parents[2])
    except ValueError as exc:
        # JSON parser messages contain location only; custom checks contain no values.
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except (OSError, KeyError, subprocess.CalledProcessError) as exc:
        print(
            f"Cannot verify the parent Compose configuration: {type(exc).__name__}", file=sys.stderr
        )
        raise SystemExit(1) from None
