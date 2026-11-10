#!/usr/bin/env python3
"""preToolUse hook: block writes to the frozen clinical files and other protected paths.

Run as ``python3 -I scripts/hooks/guard_frozen.py`` (isolated mode). Standard
library only; no network, no writes. Reads the preToolUse event JSON on stdin,
extracts every target path from ``tool_input`` and, if any resolves to a
protected file, BLOCKS the tool call using the CLI's blocking contract:

    exit 2  → block the write; STDERR is returned to the model so it can react.
    exit 0  → allow the write (every non-protected path).

Protected paths (writes are refused):
  * the frozen clinical files — docs/EVIDENCE.md, data/SCENARIOS.md,
    data/DATA_CARD.md, data/generate.py, data/check_data.py,
    data/check_results.txt and everything under data/ward_seed42/;
  * docs/UI_FLOW.md;
  * any .kiro/specs/<spec>/requirements.md.

The script never writes files and makes no network calls. On a parse error it
fails safe for the agent (exit 0, warning on STDERR) rather than blocking an
unknown call — the explicit frozen list is what it is here to protect.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Explicit frozen files (repo-relative, posix).
FROZEN_FILES = frozenset(
    {
        "docs/EVIDENCE.md",
        "data/SCENARIOS.md",
        "data/DATA_CARD.md",
        "data/generate.py",
        "data/check_data.py",
        "data/check_results.txt",
    }
)
# Any file under one of these directories is frozen.
FROZEN_DIR_PREFIXES = ("data/ward_seed42/",)
# Other protected single files.
PROTECTED_FILES = frozenset({"docs/UI_FLOW.md"})
# Protected pattern: a requirements.md inside any spec folder.
_REQUIREMENTS = re.compile(r"^\.kiro/specs/[^/]+/requirements\.md$")


def _collect_paths(obj: object) -> list[str]:
    """Recursively pull every string value stored under a ``path`` key."""
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "path" and isinstance(value, str):
                found.append(value)
            else:
                found.extend(_collect_paths(value))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_collect_paths(item))
    return found


def _to_repo_relative(raw: str) -> str | None:
    """Return the repo-relative posix path for ``raw``, or None if outside the repo."""
    p = pathlib.Path(raw)
    if not p.is_absolute():
        p = REPO_ROOT / p
    try:
        rel = p.resolve().relative_to(REPO_ROOT)
    except ValueError:
        return None
    return rel.as_posix()


def _reason_protected(rel: str) -> str | None:
    """Return a human reason if ``rel`` is protected, else None."""
    if rel in FROZEN_FILES or any(rel.startswith(d) for d in FROZEN_DIR_PREFIXES):
        return "a frozen clinical baseline file (sign-off gate; see .kiro/steering/safety.md)"
    if rel in PROTECTED_FILES:
        return "docs/UI_FLOW.md is frozen UI copy and must not be edited by the build"
    if _REQUIREMENTS.match(rel):
        return "a spec requirements.md (frozen; requirements are not edited by the builder)"
    return None


def main() -> int:
    raw_event = sys.stdin.read()
    try:
        event = json.loads(raw_event) if raw_event.strip() else {}
    except json.JSONDecodeError as exc:
        # Cannot understand the event: do not block an unknown call, but warn.
        print(f"guard_frozen: could not parse hook event JSON: {exc}", file=sys.stderr)
        return 0

    tool_input = event.get("tool_input", {})
    blocked: list[tuple[str, str]] = []
    for raw in _collect_paths(tool_input):
        rel = _to_repo_relative(raw)
        if rel is None:
            continue
        reason = _reason_protected(rel)
        if reason is not None:
            blocked.append((rel, reason))

    if blocked:
        print(
            "guard_frozen: BLOCKED — this write targets a protected path and was refused:",
            file=sys.stderr,
        )
        for rel, reason in blocked:
            print(f"  - {rel}: {reason}", file=sys.stderr)
        print(
            "Changing any of these requires a new baseline version, a docs/DECISIONS.md "
            "entry and a fresh clinical-lead sign-off. Write your code under src/sanad/ "
            "and tests under tests/ instead.",
            file=sys.stderr,
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
