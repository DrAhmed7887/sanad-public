#!/usr/bin/env python3
"""agentSpawn hook: verify the frozen clinical files still match docs/BASELINE.md.

Run as ``python3 -I scripts/hooks/baseline_check.py`` (isolated mode). Standard
library only; no network, no writes. Reads the hook event JSON on stdin (it is
not required, but AgentSpawn still sends ``{"hook_event_name": ...}``), then
recomputes the SHA-256 of every frozen file and compares the leading hex digits
against the prefixes recorded in ``docs/BASELINE.md``.

Frozen files checked here (and ONLY these): docs/EVIDENCE.md, data/SCENARIOS.md,
data/DATA_CARD.md, data/generate.py, data/check_data.py, data/check_results.txt
and every file under data/ward_seed42/. docs/DECISIONS.md and docs/TRACE.md are
in the manifest but change by design after v3, so they are NOT checked here.

Exit 0 when every checked file matches (STDOUT is added to the agent's context
as a short all-clear line). Exit 1 (a plain hook failure, shown to the user as a
warning) if any file is missing or its hash prefix does not match.
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import sys

# Repo root is two directories up from this file: scripts/hooks/<this>.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
BASELINE = REPO_ROOT / "docs" / "BASELINE.md"

# The exact set of frozen files this hook is responsible for. ward_seed42 is a
# directory: every file inside it is frozen. Everything else is listed by path.
FROZEN_FILES = (
    "docs/EVIDENCE.md",
    "data/SCENARIOS.md",
    "data/DATA_CARD.md",
    "data/generate.py",
    "data/check_data.py",
    "data/check_results.txt",
)
FROZEN_DIRS = ("data/ward_seed42",)

# Files in the manifest that this hook must NOT check (they change after v3).
IGNORED_IN_MANIFEST = frozenset({"docs/DECISIONS.md", "docs/TRACE.md"})

# A BASELINE.md row looks like: | `docs/EVIDENCE.md` | `4bb97896afe2ec08…` |
# The hash cell is a hex prefix followed by a horizontal-ellipsis character.
_ROW = re.compile(
    r"^\|\s*`([^`]+)`\s*\|\s*`([0-9a-fA-F]+)\s*\u2026?\s*`\s*\|\s*$"
)


def _sha256_hex(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_baseline(text: str) -> dict[str, str]:
    """Map each manifest file path to its recorded SHA-256 hex prefix."""
    prefixes: dict[str, str] = {}
    for line in text.splitlines():
        m = _ROW.match(line.strip())
        if m:
            prefixes[m.group(1)] = m.group(2).lower()
    return prefixes


def _frozen_targets() -> list[str]:
    """Repo-relative paths the hook must verify, in a stable sorted order."""
    targets = list(FROZEN_FILES)
    for rel in FROZEN_DIRS:
        base = REPO_ROOT / rel
        if base.is_dir():
            for p in base.rglob("*"):
                if p.is_file():
                    targets.append(p.relative_to(REPO_ROOT).as_posix())
    return sorted(set(targets))


def main() -> int:
    # Drain stdin so the CLI does not see a broken pipe; the content is unused.
    try:
        sys.stdin.read()
    except Exception:
        pass

    if not BASELINE.is_file():
        print(f"baseline_check: cannot find {BASELINE}", file=sys.stderr)
        return 1

    prefixes = _parse_baseline(BASELINE.read_text(encoding="utf-8"))
    if not prefixes:
        print("baseline_check: no hash rows parsed from BASELINE.md", file=sys.stderr)
        return 1

    problems: list[str] = []
    checked = 0
    for rel in _frozen_targets():
        if rel in IGNORED_IN_MANIFEST:
            continue
        expected = prefixes.get(rel)
        if expected is None:
            problems.append(f"{rel}: no hash recorded in BASELINE.md")
            continue
        path = REPO_ROOT / rel
        if not path.is_file():
            problems.append(f"{rel}: frozen file is missing")
            continue
        actual = _sha256_hex(path)
        if not actual.startswith(expected):
            problems.append(
                f"{rel}: hash changed (expected {expected}…, got {actual[: len(expected)]}…)"
            )
            continue
        checked += 1

    if problems:
        print(
            "baseline_check: FROZEN BASELINE MISMATCH — do not build until resolved:",
            file=sys.stderr,
        )
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print(f"baseline_check: OK — {checked} frozen clinical files match BASELINE.md v3.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
