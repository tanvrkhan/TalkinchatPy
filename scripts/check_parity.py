#!/usr/bin/env python3
"""Validate the committed Howdies-to-TalkinChat command parity manifest."""

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "parity" / "howdies-f2567a1.json"


def validate(data):
    errors = []
    if data.get("source_commit") != "f2567a1":
        errors.append("source_commit must be f2567a1")
    if data.get("primary_prefix") != ",":
        errors.append("primary_prefix must be comma")
    if set(data.get("accepted_prefixes", ())) != {",", "!"}:
        errors.append("accepted_prefixes must contain comma and exclamation")

    claimed = set()
    commands = data.get("commands", ())
    if len(commands) < 100:
        errors.append("manifest does not contain the complete command baseline")
    for index, item in enumerate(commands):
        label = item.get("name") or f"command[{index}]"
        if not item.get("fallback"):
            errors.append(f"{label}: fallback is required")
        if "capabilities" not in item:
            errors.append(f"{label}: capabilities are required")
        if item.get("status") not in {"planned", "enabled", "disabled"}:
            errors.append(f"{label}: invalid status")
        for name in [item.get("name", ""), *item.get("aliases", ())]:
            normalized = name.casefold()
            if not normalized:
                errors.append(f"{label}: empty name or alias")
            elif normalized in claimed:
                errors.append(f"{label}: duplicate name or alias {name}")
            claimed.add(normalized)
    return errors


def main():
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"parity manifest could not be read: {exc}", file=sys.stderr)
        return 2
    errors = validate(data)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"parity manifest valid: {len(data['commands'])} commands")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
