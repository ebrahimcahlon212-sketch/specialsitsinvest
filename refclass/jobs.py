"""Hold a kernel lock across a run.sh job, including its child steps."""
import fcntl
import os
from pathlib import Path
import sys


def main():
    script, *args = sys.argv[1:]
    root = Path(script).resolve().parent
    readonly = not args or args[0] in ("help", "--help", "-h", "version", "doctor")
    readonly = readonly or (args[:2] in (["refclass", "show"], ["refclass", "gates"]))
    env = os.environ.copy()
    if not readonly:
        path = root / ".locks" / "run.lock"
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
            print("Stopped. Run lock failed. A kit job is already running.", file=sys.stderr)
            return 1
        os.set_inheritable(fd, True)
        env["KIT_RUN_LOCK_FD"] = str(fd)
    env["KIT_RUN_LOCK_PID"] = str(os.getpid())
    os.execvpe("bash", ["bash", script, *args], env)


if __name__ == "__main__":
    sys.exit(main())
