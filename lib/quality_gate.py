"""Publication boundary shared by legacy commands.

Evidence supplied in quality.json is always enforced. Strict mode also blocks
missing evidence. Legacy mode preserves older inputs but never certifies them.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from refclass.quality import GateError, validate


def preflight(directory, evidence_path=None):
    path = Path(evidence_path) if evidence_path and Path(evidence_path).exists() else Path(directory) / "quality.json"
    mode = os.environ.get("QUALITY_GATES", "strict")
    if mode not in ("legacy", "strict"):
        raise GateError("Quality gates mode must be legacy or strict")
    if not path.exists():
        if mode == "strict":
            raise GateError(f"Quality gate evidence missing. {path}")
        print(f"Quality gates unverified. No evidence in {path}. Legacy compatibility mode.", file=sys.stderr)
        return None
    try:
        return validate(json.loads(path.read_text()))
    except (ValueError, TypeError, KeyError) as exc:
        raise GateError(f"Quality gate stopped publication. {exc}") from exc


if __name__ == "__main__":
    try:
        preflight(sys.argv[1])
    except (GateError, OSError) as exc:
        sys.exit(f"Stopped. {exc}")
