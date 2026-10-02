#!/usr/bin/env python3
"""Run synthetic acceptance in an owned, network-disabled, temporary PostgreSQL.

Requires Docker and the pinned image already cached. Never pulls images, binds
ports, touches existing containers, or uses the caller's database configuration.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

import psycopg


ROOT = Path(__file__).resolve().parents[1]
IMAGE = "postgres@sha256:16bc17c64a573ef34162af9298258d1aec548232985b33ed7b1eac33ba35c229"


def run(args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-package", type=Path)
    parser.add_argument("--browser", action="store_true", help="Run synthetic phone browser acceptance on loopback")
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args()
    if bool(args.legacy_package) != bool(args.data_root):
        parser.error("--legacy-package and --data-root must be supplied together")
    run(["docker", "image", "inspect", IMAGE], stdout=subprocess.DEVNULL)
    base = Path(tempfile.mkdtemp(prefix="swb-synthetic-pg-"))
    socket_dir = base / "socket"
    socket_dir.mkdir(mode=0o777)
    socket_dir.chmod(0o777)  # Private parent; only the owned container can traverse it.
    owner = uuid.uuid4().hex
    (base / "owner").write_text(owner)
    name = f"swb-synthetic-{owner}"
    cid = None
    try:
        started = run(["docker", "run", "--detach", "--name", name,
            "--label", f"study-workbench.test-owner={owner}", "--network", "none",
            "--memory", "512m", "--cpus", "1",
            "--tmpfs", "/var/lib/postgresql/data:rw,nosuid,nodev",
            "--mount", f"type=bind,src={socket_dir},dst=/var/run/postgresql",
            "--env", "POSTGRES_HOST_AUTH_METHOD=trust", "--env", "POSTGRES_DB=swb_synthetic", IMAGE],
            text=True, capture_output=True)
        cid = started.stdout.strip()
        env = {key: value for key, value in os.environ.items() if not key.startswith("SWB_")}
        env.update(SWB_DB_HOST=str(socket_dir), SWB_DB_NAME="swb_synthetic",
                   SWB_DB_USER="postgres", SWB_SECRET_KEY="synthetic-tests-only-no-service",
                   DJANGO_SETTINGS_MODULE="app.settings", SWB_TEST_OWNER=owner, SWB_DATA_ROOT=str(base / "web-data"))
        deadline = time.monotonic() + 30
        while True:
            try:
                with psycopg.connect(host=str(socket_dir), dbname="swb_synthetic", user="postgres", connect_timeout=1) as conn:
                    version = conn.execute("SELECT version()").fetchone()[0]
                break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    run(["docker", "logs", cid])
                    raise RuntimeError("Owned synthetic PostgreSQL did not become ready")
                time.sleep(0.25)
        print(f"Synthetic database: {version}; network=none; no published ports", flush=True)
        for command in (
            ["check"],
            ["makemigrations", "--check", "--dry-run"],
            ["migrate", "--noinput"],
            ["migrate", "persistence", "0001", "--noinput"],
            ["migrate", "--noinput"],
            ["test", "tests", "--noinput", "-v", "1"],
        ):
            run([sys.executable, "manage.py", *command], env=env)
        if args.browser:
            run([sys.executable, "scripts/verify_web.py", "--owner", owner], env=env)
        if args.legacy_package:
            run([sys.executable, "scripts/verify_legacy_import.py", "--package", str(args.legacy_package.resolve()),
                 "--data-root", str(args.data_root.resolve())], env=env)
    finally:
        # A failed docker run can still create a container. Verify the random
        # ownership label before removing either its ID or its unique name.
        candidate = cid or name
        info = subprocess.run(["docker", "inspect", candidate], text=True, capture_output=True)
        if info.returncode == 0:
            details = json.loads(info.stdout)[0]
            if details["Config"]["Labels"].get("study-workbench.test-owner") == owner:
                subprocess.run(["docker", "exec", candidate, "chmod", "0777", "/var/run/postgresql"], capture_output=True)
                subprocess.run(["docker", "stop", "--time", "10", candidate], capture_output=True)
                run(["docker", "rm", "--force", candidate], stdout=subprocess.DEVNULL)
        shutil.rmtree(base)
        print("Owned synthetic container and temporary files removed", flush=True)


if __name__ == "__main__":
    main()
