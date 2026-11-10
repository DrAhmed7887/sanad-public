"""Determinism of the generated board HTML (tasks.md task 8).

The generator must produce **byte-identical** output over the same dataset,
independent of the run, the machine or the Python hash seed (AC-GEN-7;
``.kiro/steering/tech.md`` determinism). A demo whose bytes wander on every
build cannot be trusted to replay exactly what the engine computed, and an
auditor cannot pin a capture to a known artefact.

Two guarantees are proved here -- no engine code changes for this task
(tasks.md: "Create ``tests/test_board_determinism.py`` (no code change)"):

* **end-to-end via the real entry point.** Run
  ``PYTHONPATH=src python3 -m sanad.board --out <tmp>`` twice as *subprocesses*
  with **different ``PYTHONHASHSEED`` values** (and a scrambled process
  environment) and assert the two files are byte-for-byte identical. Running
  the module exactly as ``design.md``/``AC-GEN-1`` document it -- not just
  calling :func:`sanad.board.main` in-process -- is what proves no dict/set
  iteration order, no ``hash()`` randomisation and no environment leak can
  change a single byte.
* **canonical embedded JSON.** The ``#board-data`` block (read back out of the
  generated HTML and unescaped the same way the viewer's ``JSON.parse`` sees
  it, design.md §3d) equals
  ``json.dumps(json.loads(s), sort_keys=True, ensure_ascii=False,
  separators=(",", ":"))`` -- i.e. the embedded data is already in canonical
  form, so re-serialising its own parse is a fixed point and nothing in the
  payload depends on insertion order.

The subprocesses are started with ``PYTHONPATH=src`` (not ``-I``) exactly as
``AC-GEN-1`` specifies: ``-I`` drops ``PYTHONPATH`` so the package could not be
imported (design.md Section 1, D28). Each run reads only the fixed dataset
under ``data/ward_seed42/`` and writes HTML to a pytest ``tmp_path``; nothing
is written to ``docs/`` or ``data/`` (safety steering).
"""

from __future__ import annotations

import html as html_mod
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"


# ==========================================================================
# Helpers.
# ==========================================================================


def _run_generator(out_path: Path, hashseed: str, extra_env: dict) -> None:
    """Run the board generator as a subprocess exactly as ``AC-GEN-1`` documents.

    ``PYTHONPATH=src python3 -m sanad.board --out <out_path>`` with
    ``PYTHONHASHSEED`` forced to ``hashseed`` so hash randomisation cannot make
    the output wander. ``-I`` is deliberately **not** used: it would drop
    ``PYTHONPATH`` and the module could not be imported (design.md Section 1).
    """

    env = dict(os.environ)
    # Put src/ on the import path the documented way (AC-GEN-1), not via -I.
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(SRC) + (os.pathsep + existing if existing else "")
    env["PYTHONHASHSEED"] = hashseed
    env.update(extra_env)

    proc = subprocess.run(
        [sys.executable, "-m", "sanad.board", "--out", str(out_path)],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, (
        f"generator failed (rc={proc.returncode})\n"
        f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    assert out_path.is_file(), "generator wrote no output file"


def _board_data_text(html: str) -> str:
    """The still-escaped text inside the ``#board-data`` script block."""

    m = re.search(
        r'<script type="application/json" id="board-data">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert m, "board-data script block not found"
    return m.group(1)


# ==========================================================================
# AC-GEN-7: two subprocess runs with different hash seeds are byte-identical.
# ==========================================================================


def test_two_runs_with_different_hashseed_are_byte_identical(
    tmp_path: Path,
) -> None:
    """Byte-for-byte determinism across runs, machines and hash seeds.

    Two independent subprocess builds -- one with ``PYTHONHASHSEED=0`` and a
    quiet environment, one with ``PYTHONHASHSEED=1`` and extra scrambling env
    vars -- must produce identical bytes. If any result depended on ``hash()``
    randomisation, dict/set iteration order or an environment variable, the two
    files would differ (AC-GEN-7).
    """

    out_a = tmp_path / "a" / "board.html"
    out_b = tmp_path / "b" / "board.html"

    _run_generator(out_a, hashseed="0", extra_env={})
    # A different hash seed and a scrambled environment: nothing may leak in.
    _run_generator(
        out_b,
        hashseed="1",
        extra_env={"LC_ALL": "C", "TZ": "UTC", "SANAD_NOISE": "x"},
    )

    bytes_a = out_a.read_bytes()
    bytes_b = out_b.read_bytes()
    assert bytes_a == bytes_b, (
        "board.html differs between two runs with different PYTHONHASHSEED; "
        f"lengths {len(bytes_a)} vs {len(bytes_b)}"
    )


def test_single_run_is_valid_utf8_html(tmp_path: Path) -> None:
    """Sanity: the subprocess build is a UTF-8 ``<!doctype html>`` file.

    Guards the determinism assertion above: identical *empty* or *broken* files
    would also be "byte-identical", so confirm the artefact is the real page.
    """

    out = tmp_path / "board.html"
    _run_generator(out, hashseed="0", extra_env={})
    text = out.read_bytes().decode("utf-8")
    assert text.startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in text
    assert _board_data_text(text), "embedded board-data is empty"


# ==========================================================================
# AC-GEN-7: the embedded JSON is already canonical (a fixed point of dumps).
# ==========================================================================


def test_embedded_board_data_is_canonical(tmp_path: Path) -> None:
    """The ``#board-data`` payload equals the canonical dump of its own parse.

    Unescape ``<``/``>``/``&`` the way the viewer does (design.md §3d), then
    assert the text equals
    ``json.dumps(json.loads(s), sort_keys=True, ensure_ascii=False,
    separators=(",", ":"))``. This proves the embedded data is written with
    sorted keys and compact separators -- re-serialising cannot reorder a key
    or change a byte -- so the payload is insertion-order-independent and
    deterministic (AC-GEN-7, design.md §3d).
    """

    out = tmp_path / "board.html"
    _run_generator(out, hashseed="0", extra_env={})
    html = out.read_bytes().decode("utf-8")

    escaped = _board_data_text(html)
    # Reverse the tag-safe escaping exactly as the viewer's JSON.parse sees it.
    unescaped = html_mod.unescape(escaped)
    canonical = json.dumps(
        json.loads(unescaped),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert unescaped == canonical, (
        "embedded board-data is not in canonical (sorted-key, compact) JSON "
        "form; it would not be insertion-order-independent"
    )


def test_in_process_render_matches_subprocess(
    board_html: str, tmp_path: Path
) -> None:
    """The documented entry point and the in-process layers agree byte-for-byte.

    The shared ``board_html`` fixture
    (``render_html(build_board_model(load_dataset()))``, the same layers
    :func:`sanad.board.main` calls) must equal the file the
    ``python3 -m sanad.board`` subprocess writes. This ties the fast in-process
    fixtures the other board tests use to the real artefact and confirms
    ``main``'s UTF-8/``\\n`` write adds no nondeterministic byte.
    """

    out = tmp_path / "board.html"
    _run_generator(out, hashseed="0", extra_env={})
    from_file = out.read_bytes().decode("utf-8")

    assert board_html == from_file, (
        "in-process render differs from the subprocess-written file"
    )
