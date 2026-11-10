"""Offline and no-input guarantees for the rendered board (tasks.md task 3).

:func:`sanad.board.render_html` must produce **one self-contained offline HTML
file** with no network, no persistence and no way to enter patient data, and
:func:`sanad.board.main` must write exactly that one UTF-8 file. This module
proves the guarantees structurally -- the JS is never executed by the suite
(stdlib only), so the checks read the HTML string and the module's AST:

* **scenario-oracle style tests** over the real fixed dataset: ``main`` writes
  exactly one ``<!doctype html>`` UTF-8 file; the HTML references no external
  resource, makes no network call and uses no storage/cookie API; it contains
  no ``<textarea>``, every ``<input>`` is ``type="button"`` and every
  ``<select>`` offers only fixed ``<option>``s; the embedded ``board-data``
  JSON parses and carries no raw ``<`` / ``>`` / ``&``; ``board.py`` imports
  only the stdlib and ``sanad.*``; and the five ``data-screen`` containers and
  one ``data-bed`` tile per bed appear in bed-number order
  (AC-GEN-1..5, AC-NOINPUT-1..3);
* **property-based tests** (hypothesis) over *synthetic* board models: for any
  model, the rendered HTML keeps every offline/no-input guarantee and the
  ``board-data`` escaping invariant holds (no real data, no network --
  ``.kiro/steering/tech.md``).

Reads the fixed dataset read-only (via the shared ``board_model`` fixture) and
writes HTML only to a pytest ``tmp_path``; never writes to ``docs/`` or
``data/`` (safety steering).
"""

from __future__ import annotations

import ast
import html as html_mod
import json
import re
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from sanad import board


# The APIs a self-contained, offline, no-persistence page must never use
# (AC-GEN-3/4/5). Matched as substrings against the whole HTML (CSS + JS + markup).
_BANNED_TOKENS = (
    "<link",
    "<script src",
    "fetch(",
    "XMLHttpRequest",
    "WebSocket",
    "localStorage",
    "sessionStorage",
    "document.cookie",
    "indexedDB",
    "http://",
    "https://",
)

_BOARD_PY = Path(board.__file__)


# ==========================================================================
# Helpers: pull the embedded JSON and the inputs/selects out of the HTML.
# ==========================================================================


def _board_data_text(html: str) -> str:
    """The raw (still-escaped) text inside the ``#board-data`` script block."""

    m = re.search(
        r'<script type="application/json" id="board-data">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert m, "board-data script block not found"
    return m.group(1)


def _input_tags(html: str) -> list[str]:
    return re.findall(r"<input\b[^>]*>", html)


def _select_blocks(html: str) -> list[str]:
    return re.findall(r"<select\b.*?</select>", html, re.DOTALL)


# ==========================================================================
# main: writes exactly one UTF-8 <!doctype html> file.
# ==========================================================================


def test_main_writes_one_utf8_doctype_file(tmp_path: Path) -> None:
    out = tmp_path / "board.html"
    rc = board.main(["--out", str(out)])
    assert rc == 0

    # Exactly one file in the output directory.
    written = list(tmp_path.iterdir())
    assert written == [out], written

    data = out.read_bytes()
    # Valid UTF-8.
    text = data.decode("utf-8")
    # Starts exactly with the doctype and declares the charset.
    assert text.startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in text


def test_main_creates_missing_parent_directory(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "dir" / "board.html"
    assert board.main(["--out", str(out)]) == 0
    assert out.is_file()
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


# ==========================================================================
# Offline: no external resource, no network, no persistence API.
# ==========================================================================


def test_html_has_no_external_or_network_or_storage_api(board_html: str) -> None:
    for token in _BANNED_TOKENS:
        assert token not in board_html, token


def test_only_inline_scripts_and_no_external_styles(board_html: str) -> None:
    # Every <script> is inline: either the JSON data block or the inline viewer;
    # none has a ``src`` attribute.
    for tag in re.findall(r"<script\b[^>]*>", board_html):
        assert "src" not in tag, tag
    # No stylesheet <link> at all (styles are inline in a <style> block).
    assert "<link" not in board_html


# ==========================================================================
# No data entry: no textarea; inputs are buttons; selects are fixed picklists.
# ==========================================================================


def test_no_textarea(board_html: str) -> None:
    assert "<textarea" not in board_html


def test_every_input_is_a_button(board_html: str) -> None:
    tags = _input_tags(board_html)
    # There is at least one control (the clock/role/action buttons).
    assert tags
    for tag in tags:
        assert 'type="button"' in tag, tag
    # No file picker, no text/number/range/password field anywhere.
    for forbidden in ('type="file"', 'type="text"', 'type="number"',
                      'type="range"', 'type="password"', 'type="search"'):
        assert forbidden not in board_html, forbidden


def test_every_select_has_only_fixed_options(board_html: str) -> None:
    blocks = _select_blocks(board_html)
    assert blocks  # the reason/owner/until picklists exist
    for block in blocks:
        inner = block[block.index(">") + 1: block.rindex("</select>")]
        # The select contains nothing but <option>…</option> elements.
        stripped = re.sub(r"<option\b[^>]*>.*?</option>", "", inner, flags=re.DOTALL)
        assert stripped.strip() == "", block
        # And it has at least one fixed option.
        assert "<option" in block, block


# ==========================================================================
# Embedded data: parses and carries no raw <, > or &.
# ==========================================================================


def test_board_data_parses_and_has_no_raw_markup(board_html: str) -> None:
    raw = _board_data_text(board_html)
    # The escaped embedded text must contain no raw <, > or & (design.md §3d):
    # every such character in the data is written as an entity so nothing can
    # close the <script> tag. Any '&' present must begin a valid entity.
    assert "<" not in raw
    assert ">" not in raw
    assert re.search(r"&(?!lt;|gt;|amp;)", raw) is None
    unescaped = html_mod.unescape(raw)
    parsed = json.loads(unescaped)
    assert isinstance(parsed, dict)
    assert set(parsed) >= {"static", "grid_times", "beds", "episodes", "inbox"}


def test_board_data_round_trips_to_the_model(board_html: str, board_model: dict) -> None:
    raw = _board_data_text(board_html)
    parsed = json.loads(html_mod.unescape(raw))
    # The embedded JSON is exactly the canonical dump of the model.
    canonical = json.dumps(
        board_model, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    assert json.dumps(parsed, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")) == canonical


# ==========================================================================
# board.py imports only the stdlib and sanad.* (AC-GEN-2).
# ==========================================================================


def test_board_py_imports_are_stdlib_or_sanad_only() -> None:
    tree = ast.parse(_BOARD_PY.read_text(encoding="utf-8"))
    stdlib = sys.stdlib_module_names
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # Relative imports (level > 0) are within the sanad package.
            if node.level and node.level > 0:
                continue
            if node.module:
                roots.add(node.module.split(".")[0])
    for root in roots:
        assert root in stdlib or root == "sanad", root


# ==========================================================================
# Structure: five data-screen containers, one data-bed tile per bed in order.
# ==========================================================================


def test_five_data_screen_containers(board_html: str) -> None:
    ids = re.findall(r'data-screen="([^"]+)"', board_html)
    assert ids == ["start", "ward", "bed", "inbox", "review"]


def test_one_bed_tile_per_bed_in_bed_number_order(board_html: str, board_model: dict) -> None:
    beds = [int(n) for n in re.findall(r'data-bed="(\d+)"', board_html)]
    expected = [b["bed"] for b in board_model["beds"]]
    assert beds == expected
    # 17 physical beds, ascending, no duplicates.
    assert beds == sorted(beds)
    assert len(beds) == len(set(beds)) == 17


# ==========================================================================
# Property-based: any synthetic model renders an offline, no-input HTML.
# ==========================================================================


def _synthetic_model() -> st.SearchStrategy[dict]:
    """A small, JSON-safe board model with text that stresses the escaping.

    The static copy and bed labels deliberately include ``<``, ``>``, ``&`` and
    a double quote so the escaping (and the "no raw markup in board-data")
    invariant is exercised; no real dataset or network is touched
    (``.kiro/steering/tech.md``).
    """

    nasty = st.sampled_from(
        ["plain", "a<b", "x>y", "p&q", 'say "hi"', "</script>", "mix <&> end"]
    )

    def _static(label: str) -> dict:
        return {
            "persistent_label": label,
            "intended_use": "use " + label,
            "verification": "verify " + label,
            "ward_line": "ward " + label,
            "silence_text": "silent " + label,
            "r1_met_text": "r1 " + label,
            "r2_combined_text": "r2 " + label,
            "r3_overdue_text": "r3 " + label,
            "threshold_label": "threshold " + label,
            "fluid_unknown_label": "fluid " + label,
            # The R1 criteria list is part of the static copy that
            # ``render_html`` renders on Screen 5 (task 4 added
            # ``board._render_criteria_sources``). A synthetic model must carry
            # the same shape, with the nasty text in label/source so the
            # escaping invariant is still exercised on it.
            "criteria_sources": [
                {"id": "0", "label": "label " + label, "source": "src " + label},
                {"id": "⏱", "label": "dur " + label, "source": "src2 " + label},
            ],
        }

    @st.composite
    def _build(draw) -> dict:
        label = draw(nasty)
        n_beds = draw(st.integers(min_value=1, max_value=5))
        beds = []
        for i in range(1, n_beds + 1):
            enc = f"E{i:02d}" + draw(nasty)
            beds.append({"bed": i, "encounters": {enc: {"cells": []}}})
        return {
            "static": _static(label),
            "grid_times": [],
            "beds": beds,
            "episodes": [],
            "inbox": [],
        }

    return _build()


@given(model=_synthetic_model())
@settings(max_examples=60)
def test_pbt_render_is_offline_and_no_input(model: dict) -> None:
    html = board.render_html(model)
    assert html.startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in html
    for token in _BANNED_TOKENS:
        assert token not in html, token
    assert "<textarea" not in html
    for tag in _input_tags(html):
        assert 'type="button"' in tag, tag


@given(model=_synthetic_model())
@settings(max_examples=60)
def test_pbt_board_data_never_carries_raw_markup(model: dict) -> None:
    """Even when every string contains ``<``/``>``/``&``/``"`` or a literal
    ``</script>``, the embedded JSON carries no raw ``<``/``>``/``&`` and still
    round-trips to the same model (design.md §3d)."""

    html = board.render_html(model)
    raw = _board_data_text(html)
    assert "<" not in raw and ">" not in raw
    # No *raw* ampersand: every '&' must begin a valid entity (&lt; &gt; &amp;).
    assert re.search(r"&(?!lt;|gt;|amp;)", raw) is None
    parsed = json.loads(html_mod.unescape(raw))
    assert parsed == model


# ==========================================================================
# Task 11 (F1): hidden means hidden. The inline CSS carries a single
# highest-specificity ``[hidden]`` rule so no later class rule
# (``.bed-feed-chip { display: inline-block }`` …) can give a hidden element a
# layout box; the viewer toggles only the ``hidden`` attribute to show/hide the
# feed chip, the feed banner, the review panels and the screens
# (AC-FAIL-1, AC-S2-feedbanner).
# ==========================================================================


def _style_block(html: str) -> str:
    m = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    assert m, "inline <style> block not found"
    return m.group(1)


def test_inline_css_has_hidden_display_none_important(board_html: str) -> None:
    css = _style_block(board_html)
    # The exact rule required by F1 (whitespace-tolerant).
    assert re.search(
        r"\[hidden\]\s*\{\s*display:\s*none\s*!important;?\s*\}", css
    ), "missing [hidden] { display: none !important; } rule"


def test_feed_chip_and_banner_use_the_hidden_attribute(board_html: str) -> None:
    """The feed chip starts hidden in the markup and the viewer toggles the
    ``hidden`` attribute (not a class / inline ``display``), so the single
    ``[hidden]`` rule governs its box (F1)."""

    # Every tile's feed chip ships with the ``hidden`` attribute set.
    tiles = re.findall(r"<li class=\"bed-tile\".*?</li>", board_html, re.DOTALL)
    assert tiles
    for tile in tiles:
        m = re.search(r"<span[^>]*data-feed-chip[^>]*>", tile)
        assert m and "hidden" in m.group(0), tile
    # The feed banner region also starts hidden.
    m = re.search(r"<div[^>]*data-feed-banner[^>]*>", board_html)
    assert m and "hidden" in m.group(0)
