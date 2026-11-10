#!/usr/bin/env python3
"""postToolUse hook: scan freshly written public-facing files for banned wording.

Run as ``python3 -I scripts/hooks/wording_guard.py`` (isolated mode). Standard
library only; no network, no writes. Reads the postToolUse event JSON on stdin,
finds the file(s) that were just written, and — for any file under ``src/`` or
with a ``.html`` or ``.md`` extension — scans the content for the banned public
phrases. The banned phrases are PARSED from docs/EVIDENCE.md at run time (never
hard-coded here) so the single source of truth stays the frozen baseline.

Exit 0 always (postToolUse cannot block; the tool already ran). When a banned
phrase is found, the hit is reported on STDERR so the agent sees the warning and
fixes the wording. Clean files produce a short OK line on STDOUT.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
EVIDENCE = REPO_ROOT / "docs" / "EVIDENCE.md"

# The EVIDENCE.md line that lists the banned phrases, e.g.:
#   - **Banned wording:** "monitors ventilated patients", "identifies ...", ...
_BANNED_LINE = re.compile(r"\*\*Banned wording:\*\*\s*(.+)$")
_QUOTED = re.compile(r"\u201c([^\u201d]+)\u201d|\"([^\"]+)\"")

# File types that are "public-facing" for the purpose of this scan.
_SCANNED_SUFFIXES = (".html", ".md")


def _parse_banned_phrases() -> list[str]:
    """Extract the banned phrases from the frozen baseline (never hard-coded)."""
    if not EVIDENCE.is_file():
        return []
    phrases: list[str] = []
    for line in EVIDENCE.read_text(encoding="utf-8").splitlines():
        m = _BANNED_LINE.search(line)
        if not m:
            continue
        for curly, straight in _QUOTED.findall(m.group(1)):
            phrase = (curly or straight).strip()
            if phrase:
                phrases.append(phrase)
    # De-duplicate while keeping order.
    seen: set[str] = set()
    unique: list[str] = []
    for p in phrases:
        key = p.lower()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


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


def _to_repo_relative(raw: str) -> tuple[pathlib.Path, str] | None:
    p = pathlib.Path(raw)
    if not p.is_absolute():
        p = REPO_ROOT / p
    resolved = p.resolve()
    try:
        rel = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return None
    return resolved, rel


def _should_scan(rel: str) -> bool:
    if rel.startswith("src/"):
        return True
    return rel.endswith(_SCANNED_SUFFIXES)


def main() -> int:
    raw_event = sys.stdin.read()
    try:
        event = json.loads(raw_event) if raw_event.strip() else {}
    except json.JSONDecodeError as exc:
        print(f"wording_guard: could not parse hook event JSON: {exc}", file=sys.stderr)
        return 0

    banned = _parse_banned_phrases()
    if not banned:
        print("wording_guard: no banned phrases parsed from docs/EVIDENCE.md", file=sys.stderr)
        return 0

    tool_input = event.get("tool_input", {})
    hits: list[str] = []
    scanned: list[str] = []
    for raw in _collect_paths(tool_input):
        resolved_rel = _to_repo_relative(raw)
        if resolved_rel is None:
            continue
        resolved, rel = resolved_rel
        if not _should_scan(rel) or not resolved.is_file():
            continue
        scanned.append(rel)
        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lowered = content.lower()
        for phrase in banned:
            if phrase.lower() in lowered:
                hits.append(f'{rel}: contains banned public phrase "{phrase}"')

    if hits:
        print(
            "wording_guard: BANNED WORDING FOUND — fix before this reaches any public "
            "material (README, UI, video, blog, submission):",
            file=sys.stderr,
        )
        for h in hits:
            print(f"  - {h}", file=sys.stderr)
        print(
            "Use the approved rule wording in .kiro/steering/product.md instead; a "
            "silent/non-triggering bed is never 'safe/stable/clear/green'.",
            file=sys.stderr,
        )
        return 0

    if scanned:
        print(f"wording_guard: OK — no banned wording in {', '.join(scanned)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
