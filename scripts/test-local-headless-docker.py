from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "local-engine" / "docker" / "Dockerfile"
ENTRYPOINT = ROOT / "local-engine" / "docker" / "entrypoint.sh"
COMPOSE = ROOT / "docker-compose.headless.yml"


def _run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=check)


def _static_contract() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    compose = COMPOSE.read_text(encoding="utf-8")

    required_docker = (
        "FROM python:3.12.11-slim-bookworm",
        "ffmpeg",
        "tini",
        "USER 10001:10001",
        'VOLUME ["/data"]',
        "HEALTHCHECK",
        "GALAXY_PORTABLE=0",
        "GALAXY_HOME=/data",
        "GALAXY_DOWNLOAD_DIR=/data/downloads",
    )
    for value in required_docker:
        assert value in dockerfile, f"Dockerfile contract missing: {value}"

    assert "${#token}" in entrypoint and "24" in entrypoint
    assert "refusing symbolic-link runtime path" in entrypoint
    assert "exec python /app/headless_api.py" in entrypoint

    required_compose = (
        "GALAXY_HEADLESS_TOKEN:",
        "GALAXY_BIND_ADDRESS:-127.0.0.1",
        "read_only: true",
        "no-new-privileges:true",
        "cap_drop:",
        "- ALL",
        "/data",
    )
    for value in required_compose:
        assert value in compose, f"Compose contract missing: {value}"


def _wait_for_status(port: int, token: str, *, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/v1/status"
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, dict) and payload.get("ok") is True:
                return payload
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = exc
        time.sleep(0.5)
    raise AssertionError(f"container API did not become ready: {last_error}")


def _live_contract(image: str) -> None:
    image_user = _run(["docker", "image", "inspect", image, "--format", "{{.Config.User}}"]).stdout.strip()
    assert image_user == "10001:10001", f"container must run as non-root user, got {image_user!r}"

    missing_token = _run(["docker", "run", "--rm", image], check=False)
    assert missing_token.returncode != 0
    assert "GALAXY_HEADLESS_TOKEN" in missing_token.stderr

    name = f"galaxy-headless-test-{secrets.token_hex(4)}"
    token = "test-" + secrets.token_hex(24)
    try:
        started = _run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                name,
                "--read-only",
                "--tmpfs",
                "/tmp:size=64m,mode=1777",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "-e",
                f"GALAXY_HEADLESS_TOKEN={token}",
                "-p",
                "127.0.0.1::17837",
                image,
            ]
        )
        assert started.stdout.strip()
        mapping = _run(["docker", "port", name, "17837/tcp"]).stdout.strip().splitlines()[0]
        port = int(mapping.rsplit(":", 1)[1])
        payload = _wait_for_status(port, token)
        assert int(payload.get("protocol") or 0) >= 2
        uid = _run(["docker", "exec", name, "id", "-u"]).stdout.strip()
        assert uid == "10001"
    finally:
        _run(["docker", "rm", "-f", name], check=False)


def run(image: str = "") -> None:
    _static_contract()
    if image:
        _live_contract(image)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default=os.getenv("GALAXY_DOCKER_TEST_IMAGE", ""))
    args = parser.parse_args(argv)
    run(args.image)
    print("Headless Docker/NAS self-test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
