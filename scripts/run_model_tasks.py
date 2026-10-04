#!/usr/bin/env python3
"""Run queued model drafting jobs in a separate, sequential process."""
import argparse
import os
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="recover expired work and run one queued job")
    mode.add_argument("--watch", action="store_true", help="poll and process queued jobs sequentially")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    args = parser.parse_args()
    if not 0.25 <= args.poll_seconds <= 60:
        parser.error("--poll-seconds must be between 0.25 and 60")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import django
    django.setup()
    from app.ai.services import execute_next, recover_interrupted
    from app.workflows import services as workflows
    from app.solutions import jobs as solutions

    def work_once():
        recover_interrupted()
        workflows.recover_interrupted()
        solutions.recover_interrupted()
        solution = solutions.execute_next()
        if solution:
            print(f"solution={solution.pk} state={solution.state} error_code={solution.error_code or '-'}", flush=True)
        workflow = workflows.execute_next()
        if workflow:
            print(f"workflow={workflow.pk} state={workflow.state} error_code={workflow.error_code or '-'}", flush=True)
        run = execute_next()
        if run:
            print(f"run={run.pk} status={run.status} error_code={run.error_code or '-'}", flush=True)
        return run is not None or workflow is not None or solution is not None

    if args.once or not args.watch:
        work_once()
        return
    while True:
        try:
            if not work_once():
                time.sleep(args.poll_seconds)
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
