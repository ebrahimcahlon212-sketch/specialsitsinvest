"""Launch a logged import with a lock held from submission to completion."""
import argparse
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import subprocess
import sys


def launch(args, root, log_dir=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--db", default=os.environ.get("REFCLASS_DB", str(root / "data/refclass.sqlite")))
    parser.add_argument("--cache", type=Path)
    options, _ = parser.parse_known_args(args)
    lock = (options.cache.resolve() / ".collection.job.lock" if args[0] == "collect" and options.cache
            else Path(str(Path(options.db).resolve()) + ".job.lock"))
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("Run lock failed. This reference-class job is already running.") from exc
        logs = Path(log_dir) if log_dir else Path.home() / "special-sits-kit-logs"
        logs.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        log = logs / f"refclass-{args[0]}-{stamp}.log"
        with log.open("x") as output:
            proc = subprocess.Popen([sys.executable, "-m", "refclass.background", "--worker", *args],
                                    cwd=root, stdin=subprocess.DEVNULL, stdout=output,
                                    stderr=subprocess.STDOUT, start_new_session=True, pass_fds=(fd,))
        return proc.pid, log
    finally:
        # Do not unlock here. The child retains this open file description.
        os.close(fd)


def main():
    if sys.argv[1:2] == ["--worker"]:
        from .__main__ import main as execute
        status = execute(sys.argv[2:])
        print(f"Job finished. Exit status {status}.", flush=True)
        return status
    try:
        pid, log = launch(sys.argv[1:], Path(__file__).resolve().parents[1])
        print(f"Started reference-class job {pid}. Log {log}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"Stopped. {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
