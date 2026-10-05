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
    parser.add_argument("--business-browser", action="store_true", help="Run the knowledge, learning and print browser acceptance")
    parser.add_argument("--fusion-browser", action="store_true", help="Run the built React SOP and evidence browser acceptance")
    parser.add_argument("--pc-browser", action="store_true", help="Run the unified PC workspace and companion acceptance")
    parser.add_argument("--knowledge-browser", action="store_true", help="Run four anonymous knowledge companions and empty recovery")
    parser.add_argument("--solution-evidence", type=Path, help="Keep only synthetic companion test artifacts in this new local directory")
    parser.add_argument("--skip-tests", action="store_true", help="Browser debugging only; does not constitute full acceptance")
    parser.add_argument("--test-label", action="append", help="Run selected Django test labels; default is tests")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--geometry-trial", type=Path, help="Private, locally reviewed small sample input")
    parser.add_argument("--geometry-output", type=Path, help="New private directory for small sample evidence")
    parser.add_argument("--skill-trial", type=Path, help="Reviewed private sample through the offline skill")
    parser.add_argument("--skill-root", type=Path)
    parser.add_argument("--skill-output", type=Path)
    args = parser.parse_args()
    if args.skip_tests and not (args.browser or args.business_browser or args.fusion_browser or args.pc_browser or args.knowledge_browser):
        parser.error("--skip-tests is restricted to a browser debugging run")
    if bool(args.legacy_package) != bool(args.data_root):
        parser.error("--legacy-package and --data-root must be supplied together")
    if bool(args.geometry_trial) != bool(args.geometry_output):
        parser.error("--geometry-trial and --geometry-output must be supplied together")
    if any((args.skill_trial, args.skill_root, args.skill_output)) and not all((args.skill_trial, args.skill_root, args.skill_output)):
        parser.error("--skill-trial, --skill-root and --skill-output must be supplied together")
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
        if args.solution_evidence:
            env["SWB_SOLUTION_TEST_EVIDENCE"] = str(args.solution_evidence.resolve())
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
            ["test", *(args.test_label or ["tests"]), "--noinput", "-v", "1"],
        ):
            if command[0]=='test' and args.skip_tests:
                continue
            if args.skip_tests and command[:3] == ['migrate', 'persistence', '0001']:
                continue  # Browser debugging still migrates its fresh owned DB.
            run([sys.executable, "manage.py", *command], env=env)
        if args.legacy_package:
            run([sys.executable, "scripts/verify_legacy_import.py", "--package", str(args.legacy_package.resolve()),
                 "--data-root", str(args.data_root.resolve())], env=env)
        if args.geometry_trial:
            run([sys.executable, "scripts/verify_geometry_trial.py", "--trial", str(args.geometry_trial.resolve()),
                 "--output", str(args.geometry_output.resolve())], env=env)
        if args.skill_trial:
            run([sys.executable, "scripts/verify_skill_trial.py", "--trial", str(args.skill_trial.resolve()),
                 "--skill-root", str(args.skill_root.resolve()), "--output", str(args.skill_output.resolve())], env=env)
        if args.browser:
            run([sys.executable, "scripts/verify_web.py", "--owner", owner], env=env)
        if args.business_browser:
            run([sys.executable, "scripts/verify_business.py", "--owner", owner], env=env)
        if args.fusion_browser:
            run([sys.executable, "scripts/verify_fusion.py", "--owner", owner], env=env)
        if args.pc_browser:
            run([sys.executable, "scripts/verify_pc.py", "--owner", owner], env=env)
        if args.knowledge_browser:
            run([sys.executable, "scripts/verify_knowledge.py", "--owner", owner], env=env)
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
