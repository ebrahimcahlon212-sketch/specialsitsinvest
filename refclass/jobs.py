"""Hold a kernel lock across a run.sh job, including its child steps."""
import fcntl
import hashlib
import os
from pathlib import Path
import sys


def job_key(args):
    """Lock a job identity, not the entire kit or read-only commands."""
    if not args or args[0] in {"help", "--help", "-h", "version", "doctor", "knowledge"}:
        return None
    if args[0] == "refclass":
        return None  # Database writes have their own lock.
    if len(args) > 1 and args[1] in {"ask", "view", "ledger"}:
        return None
    identity = args[:2] if len(args) > 1 else [args[0], "run"]
    return hashlib.sha256("\0".join(identity).encode()).hexdigest()[:24]


def main():
    script, *args = sys.argv[1:]
    root = Path(script).resolve().parent
    key = job_key(args)
    env = os.environ.copy()
    if key:
        path = root / ".locks" / (key + ".lock")
        path.parent.mkdir(exist_ok=True)
        inherited = False
        try:
            fd = int(env.get("KIT_RUN_LOCK_FD", "-1"))
            inherited = os.path.samestat(os.fstat(fd), path.stat())
        except (ValueError, OSError):
            pass
        if not inherited:
            fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Stopped. Run lock failed. This job is already running.", file=sys.stderr)
            return 1
        os.set_inheritable(fd, True)
        env["KIT_RUN_LOCK_FD"] = str(fd)
    env["KIT_RUN_LOCK_PID"] = str(os.getpid())
    os.execvpe("bash", ["bash", script, *args], env)


if __name__ == "__main__":
    sys.exit(main())
