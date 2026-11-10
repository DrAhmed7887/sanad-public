"""Tests for the Sanad build-loop hooks (scripts/hooks/*.py).

Each hook is exercised exactly as the Kiro CLI runs it: as a subprocess started
with ``python3 -I`` that receives the hook event JSON on stdin. We assert the
CLI contract (exit codes, STDERR/STDOUT) and two safety properties the hooks
promise: they never write files and they make no network calls.

These are verification checks on the build tooling, not the clinical engine.
"""

from __future__ import annotations

import json
import subprocess
import sys
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOKS = REPO_ROOT / "scripts" / "hooks"
BASELINE_CHECK = HOOKS / "baseline_check.py"
GUARD_FROZEN = HOOKS / "guard_frozen.py"
WORDING_GUARD = HOOKS / "wording_guard.py"

# A banned public phrase, parsed live from the baseline so the test cannot drift
# from docs/EVIDENCE.md. We only use the first one for the positive case.
_BANNED_LINE_MARKER = "**Banned wording:**"


def _run_hook(script: pathlib.Path, event: dict) -> subprocess.CompletedProcess:
    """Run a hook script under ``python3 -I`` with ``event`` as JSON on stdin."""
    return subprocess.run(
        [sys.executable, "-I", str(script)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=60,
    )


def _write_event(path: str) -> dict:
    """A preToolUse/postToolUse event for a write of ``path`` (as the CLI sends)."""
    return {
        "hook_event_name": "preToolUse",
        "cwd": str(REPO_ROOT),
        "tool_name": "fs_write",
        "tool_tags": ["write", "@builtin"],
        "tool_input": {"command": "create", "path": path, "content": ""},
    }


def _first_banned_phrase() -> str:
    text = (REPO_ROOT / "docs" / "EVIDENCE.md").read_text(encoding="utf-8")
    for line in text.splitlines():
        if _BANNED_LINE_MARKER in line:
            start = line.index(_BANNED_LINE_MARKER) + len(_BANNED_LINE_MARKER)
            segment = line[start:]
            # phrases are wrapped in straight or curly double quotes
            for opener, closer in (("\u201c", "\u201d"), ('"', '"')):
                if opener in segment:
                    a = segment.index(opener) + 1
                    b = segment.index(closer, a)
                    return segment[a:b]
    raise AssertionError("no banned-wording line found in docs/EVIDENCE.md")


# --------------------------------------------------------------------------- #
# baseline_check.py (agentSpawn)
# --------------------------------------------------------------------------- #

def test_baseline_check_passes_on_current_repo():
    event = {"hook_event_name": "agentSpawn", "cwd": str(REPO_ROOT)}
    result = _run_hook(BASELINE_CHECK, event)
    assert result.returncode == 0, f"stderr={result.stderr}\nstdout={result.stdout}"
    assert "OK" in result.stdout
    assert "frozen clinical files match" in result.stdout


# --------------------------------------------------------------------------- #
# guard_frozen.py (preToolUse) — blocks (exit 2) protected paths, allows others
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "path",
    [
        "docs/EVIDENCE.md",
        "data/ward_seed42/events.jsonl",
        "docs/UI_FLOW.md",
    ],
)
def test_guard_frozen_blocks_protected_paths(path):
    result = _run_hook(GUARD_FROZEN, _write_event(path))
    assert result.returncode == 2, f"expected block for {path}; stderr={result.stderr}"
    assert "BLOCKED" in result.stderr
    assert path in result.stderr


def test_guard_frozen_blocks_spec_requirements():
    path = ".kiro/specs/ward-board/requirements.md"
    result = _run_hook(GUARD_FROZEN, _write_event(path))
    assert result.returncode == 2, f"stderr={result.stderr}"
    assert path in result.stderr


def test_guard_frozen_allows_engine_source():
    result = _run_hook(GUARD_FROZEN, _write_event("src/sanad/board.py"))
    assert result.returncode == 0, f"stderr={result.stderr}"
    assert result.stderr.strip() == ""


def test_guard_frozen_allows_tests():
    result = _run_hook(GUARD_FROZEN, _write_event("tests/test_board.py"))
    assert result.returncode == 0, f"stderr={result.stderr}"


# --------------------------------------------------------------------------- #
# wording_guard.py (postToolUse) — flags banned wording, passes clean text
# --------------------------------------------------------------------------- #

def test_wording_guard_flags_banned_phrase(tmp_path):
    phrase = _first_banned_phrase()
    target = REPO_ROOT / "src" / "sanad" / "_wording_guard_probe.py"
    target.write_text(f'# marketing blurb: Sanad {phrase} every night.\n', encoding="utf-8")
    try:
        event = {
            "hook_event_name": "postToolUse",
            "cwd": str(REPO_ROOT),
            "tool_name": "fs_write",
            "tool_tags": ["write", "@builtin"],
            "tool_input": {"path": str(target)},
            "tool_response": {"success": True},
        }
        result = _run_hook(WORDING_GUARD, event)
        assert result.returncode == 0  # postToolUse never blocks
        assert "BANNED WORDING FOUND" in result.stderr
        assert phrase in result.stderr
    finally:
        target.unlink(missing_ok=True)


def test_wording_guard_passes_clean_text():
    target = REPO_ROOT / "src" / "sanad" / "_wording_guard_clean_probe.py"
    clean = '"""No configured rule triggered on the available data."""\n'
    target.write_text(clean, encoding="utf-8")
    try:
        event = {
            "hook_event_name": "postToolUse",
            "cwd": str(REPO_ROOT),
            "tool_name": "fs_write",
            "tool_tags": ["write", "@builtin"],
            "tool_input": {"path": str(target)},
            "tool_response": {"success": True},
        }
        result = _run_hook(WORDING_GUARD, event)
        assert result.returncode == 0, f"stderr={result.stderr}"
        assert "BANNED WORDING FOUND" not in result.stderr
        assert "OK" in result.stdout
    finally:
        target.unlink(missing_ok=True)


def test_wording_guard_ignores_non_public_file():
    # A .txt outside src/ is neither under src/ nor .html/.md: it is not scanned.
    target = REPO_ROOT / "notes_probe.txt"
    phrase = _first_banned_phrase()
    target.write_text(phrase, encoding="utf-8")
    try:
        event = {
            "hook_event_name": "postToolUse",
            "cwd": str(REPO_ROOT),
            "tool_name": "fs_write",
            "tool_tags": ["write", "@builtin"],
            "tool_input": {"path": str(target)},
            "tool_response": {"success": True},
        }
        result = _run_hook(WORDING_GUARD, event)
        assert result.returncode == 0
        assert "BANNED WORDING FOUND" not in result.stderr
    finally:
        target.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# Safety properties shared by all three hooks
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("script", [BASELINE_CHECK, GUARD_FROZEN, WORDING_GUARD])
def test_hooks_do_not_write_files(script):
    """Running a hook must not create, delete or modify any repo file."""
    before = {p for p in REPO_ROOT.rglob("*") if p.is_file()}
    before_mtimes = {p: p.stat().st_mtime_ns for p in before}

    if script is BASELINE_CHECK:
        event = {"hook_event_name": "agentSpawn", "cwd": str(REPO_ROOT)}
    else:
        event = _write_event("src/sanad/board.py")
    _run_hook(script, event)

    after = {p for p in REPO_ROOT.rglob("*") if p.is_file()}
    assert before == after, f"{script.name} changed the set of files on disk"
    for p in before:
        assert p.stat().st_mtime_ns == before_mtimes[p], f"{script.name} modified {p}"


@pytest.mark.parametrize("script", [BASELINE_CHECK, GUARD_FROZEN, WORDING_GUARD])
def test_hooks_make_no_network_calls(script):
    """Static guarantee: hook sources import no networking modules."""
    source = script.read_text(encoding="utf-8")
    for forbidden in ("import socket", "import urllib", "import http", "import ftplib",
                      "import requests", "import asyncio", "socket.socket"):
        assert forbidden not in source, f"{script.name} references {forbidden!r}"
