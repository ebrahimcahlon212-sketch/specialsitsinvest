#!/usr/bin/env python3
"""Pull a model's final deliverable out of its raw command-line output.

Usage: extract_output.py RAW_FILE OUT_FILE

RAW_FILE is plain text (Claude Code, Codex) or Kimi Code stream-json.
The deliverable is the text between the last <<<BEGIN OUTPUT>>> line and the
<<<END OUTPUT>>> line after it. If the markers are missing, the whole reply is
kept so nothing is lost, and the exit status is 2 as a warning.
"""
import json
import re
import sys
from pathlib import Path
from quality_gate import preflight

BEGIN = re.compile(r"^\s*<<<BEGIN OUTPUT>>>\s*$")
END = re.compile(r"^\s*<<<END OUTPUT>>>\s*$")


def assistant_text(obj):
    """Collect assistant text from one stream-json record, whatever its exact shape."""
    found = []

    def take(content):
        if isinstance(content, str):
            found.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, str):
                    found.append(part)
                elif isinstance(part, dict) and part.get("type") in (None, "text", "output_text") \
                        and isinstance(part.get("text"), str):
                    found.append(part["text"])

    def walk(o):
        if isinstance(o, dict):
            if o.get("role") == "assistant" or o.get("type") == "assistant":
                if "content" in o:
                    take(o["content"])
                if isinstance(o.get("message"), dict):
                    msg = o["message"]
                    if "content" in msg:
                        take(msg["content"])
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(obj)
    return found


CHAT_ROLES = {"assistant", "user", "tool", "system"}


def is_chat_record(r):
    return isinstance(r, dict) and (r.get("role") in CHAT_ROLES or r.get("type") in CHAT_ROLES | {"result", "message"})


def to_text(raw):
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if any(BEGIN.match(ln) for ln in lines):
        return raw
    records = []
    for ln in lines:
        try:
            records.append(json.loads(ln))
        except ValueError:
            pass
    if records and len(records) >= max(1, len(lines) // 2) and any(is_chat_record(r) for r in records):
        chunks = []
        for r in records:
            chunks.extend(assistant_text(r))
        return "\n\n".join(c for c in chunks if c.strip())
    return raw


def between_markers(text):
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if BEGIN.match(ln)]
    if not starts:
        return None
    body = []
    for ln in lines[starts[-1] + 1:]:
        if END.match(ln):
            break
        body.append(ln)
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    if len(body) >= 2 and body[0].strip().startswith("```") and body[-1].strip() == "```":
        body = body[1:-1]
    return "\n".join(body).strip() + "\n"


def main():
    if len(sys.argv) != 3:
        sys.exit("Usage: extract_output.py RAW_FILE OUT_FILE")
    try:
        preflight(Path(sys.argv[2]).parent)
    except (ValueError, OSError) as exc:
        sys.exit(f"Stopped. {exc}")
    raw = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    text = to_text(raw)
    result = between_markers(text)
    status = 0
    if result is None or not result.strip():
        result = text.strip() + "\n"
        status = 2
    with open(sys.argv[2], "w", encoding="utf-8") as fh:
        fh.write(result)
    sys.exit(status)


if __name__ == "__main__":
    main()
