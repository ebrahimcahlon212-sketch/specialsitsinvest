"""Legacy publication checks warn until phase 3 supplies evidence.

New publication paths must explicitly request strict=True. Environment settings
cannot turn a legacy research workflow into a blocking gate.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from refclass.quality import GateError, validate


def preflight(directory, evidence_path=None, *, strict=False):
    path = Path(evidence_path) if evidence_path and Path(evidence_path).exists() else Path(directory) / "quality.json"
    try:
        if not path.exists() and not strict:
            return None  # Evidence is not produced by legacy research steps.
        if not path.exists():
            raise GateError(f"Quality gate evidence missing. {path}")
        return validate(json.loads(path.read_text()), deal_root=Path(directory).resolve().parent)
    except (ValueError, TypeError, KeyError, OSError, AttributeError) as exc:
        if strict:
            raise GateError(f"Quality gate stopped publication. {exc}") from exc
        print(f"Warning. Quality gates unverified. {exc}", file=sys.stderr)
        return None


if __name__ == "__main__":
    try:
        preflight(sys.argv[1], strict="--strict" in sys.argv[2:])
    except (GateError, OSError) as exc:
        sys.exit(f"Stopped. {exc}")


def warn_check(check, *args, **kwargs):
    """Run a check on actual legacy inputs without changing its output contract."""
    try:
        return check(*args, **kwargs)
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        print(f"Warning. {exc}", file=sys.stderr)
        return None
