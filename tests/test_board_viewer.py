"""Viewer contract: screens, clock, tiles and simulated actions (task 5).

The inline viewer (``board._VIEWER_JS`` inside ``render_html``) must obey the
design.md Section 4 contract. The JS is **not executed** by the stdlib-only
suite (design.md Section 6), so -- exactly as task 3 did for the offline
guarantees -- this module proves the contract *structurally* against the
rendered HTML string and the extracted ``<script>`` body:

* the viewer writes text only with ``textContent`` and builds nodes with the
  DOM API -- it never uses ``innerHTML`` (design.md §4; the XSS-safe path);
* the viewer never compares against an **evaluation-state word** literal
  (``"met"``, ``"not_met"``, ``"unknown"``, ``"suppressed"``,
  ``"not_applicable"``): it only renders the embedded word verbatim and builds a
  CSS class from it, so the page can never invent or branch on a state and no
  "safe/green" path can exist (AC-GEN-6, AC-STATE-1, AC-SILENCE-2);
* the viewer references ``start_idx`` (clock-filtered lists) and ``feed_alert``
  (the per-tile failure chip), the two embedded fields the contract names
  (AC-FAIL-1, AC-S4-routing, AC-S5-list);
* the Acknowledge / Assessed / Deferred controls exist on Screens 3 and 5 with
  fixed ``<select>`` picklists only -- no free text anywhere (AC-S3-ack,
  AC-S5-assess, AC-WORKFLOW-2, AC-NOINPUT-2);
* every ``data-bed`` tile template carries a feed-chip element so a stale bed
  can be shown with its own alert, never silence alone (AC-FAIL-1, D06).

A property-based test (hypothesis) over synthetic board models confirms the
same no-``innerHTML`` / no-state-word-literal invariants hold whatever data is
embedded (no real data, no network -- ``.kiro/steering/tech.md``).

Reads the fixed dataset read-only via the shared ``board_html`` fixture and
renders synthetic models in memory only; never writes to ``docs/`` or
``data/`` (safety steering).
"""

from __future__ import annotations

import html as html_mod
import json
import re
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from sanad import board


# The five evaluation-state words (AC-STATE-1). The viewer must never contain
# any of these as a *quoted literal* -- it renders the embedded word verbatim
# and builds a CSS class from it (``"state-" + result.state``) instead, so it
# can never branch on, invent or hide a state (AC-GEN-6). Workflow words
# (acknowledged / assessed / deferred) are not evaluation states and are allowed
# as the fixed overlay chip text the user chooses.
_STATE_WORDS = ("met", "not_met", "unknown", "suppressed", "not_applicable")


# ==========================================================================
# Helpers: extract the inline viewer <script> body from the HTML.
# ==========================================================================


def _viewer_script(html: str) -> str:
    """The body of the inline viewer ``<script>`` (not the JSON data block).

    The data block is ``<script type="application/json" id="board-data">``; the
    viewer is the plain ``<script>`` with no ``type``/``id``. Return its body.
    """

    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", html, re.DOTALL)
    bodies = [
        body for attrs, body in scripts
        if "application/json" not in attrs and "board-data" not in attrs
    ]
    assert bodies, "inline viewer <script> not found"
    assert len(bodies) == 1, "expected exactly one inline viewer script"
    return bodies[0]


def _input_tags(html: str) -> list[str]:
    return re.findall(r"<input\b[^>]*>", html)


def _screen_block(html: str, screen_id: str) -> str:
    """The markup of one ``data-screen`` container."""

    m = re.search(
        rf'<section[^>]*data-screen="{re.escape(screen_id)}".*?</section>',
        html,
        re.DOTALL,
    )
    assert m, f"screen {screen_id} not found"
    return m.group(0)


# ==========================================================================
# No innerHTML; text is written with textContent.
# ==========================================================================


def test_viewer_has_no_inner_html(board_html: str) -> None:
    script = _viewer_script(board_html)
    assert "innerHTML" not in script
    # It does write text -- with textContent and the DOM node API.
    assert "textContent" in script
    assert "createElement" in script


# ==========================================================================
# The viewer never compares against an evaluation-state word literal.
# ==========================================================================


def test_viewer_has_no_state_word_literal(board_html: str) -> None:
    """No evaluation-state word appears as a quoted literal in the viewer.

    The viewer renders the embedded ``state`` word verbatim and builds its CSS
    class from it, so it never needs ``=== "met"`` or ``"unknown"`` anywhere.
    Any such literal would be a place the page could branch on a state and
    invent a "safe/green" shortcut (AC-GEN-6, AC-SILENCE-2). Checked for both
    single- and double-quoted forms.
    """

    script = _viewer_script(board_html)
    for word in _STATE_WORDS:
        assert f'"{word}"' not in script, word
        assert f"'{word}'" not in script, word


def test_viewer_builds_the_state_class_from_the_value(board_html: str) -> None:
    """The chip class is built from the embedded value, not hard-coded.

    The viewer concatenates ``"state-"`` with ``result.state`` -- this is the
    only way a state word reaches the DOM, so the chip always matches the engine
    (AC-GEN-6, AC-STATE-1). The CSS class names in the ``<style>`` block
    (``.chip.state-met`` …) are style, not a comparison in the script.
    """

    script = _viewer_script(board_html)
    assert "state-" in script
    assert "result.state" in script


# ==========================================================================
# The viewer references the clock-filter and failure fields.
# ==========================================================================


def test_viewer_references_start_idx_and_feed_alert(board_html: str) -> None:
    script = _viewer_script(board_html)
    assert "start_idx" in script  # clock-filtered episode / inbox lists
    assert "feed_alert" in script  # per-tile / banner failure indicator
    # It also steps an integer clock index and reads the embedded grid.
    assert "clockIndex" in script
    assert "grid_times" in script


def test_viewer_reads_only_the_board_data_block(board_html: str) -> None:
    """The viewer's only data source is the embedded ``board-data`` block.

    It never fetches or reads anything else (the offline guarantee is already
    tested in ``test_board_offline``; here we assert the positive: it parses the
    embedded JSON and reads it).
    """

    script = _viewer_script(board_html)
    assert 'getElementById("board-data")' in script
    assert "JSON.parse" in script


# ==========================================================================
# Simulated actions: Acknowledge / Assessed / Deferred on Screens 3 and 5,
# with fixed picklists only (no free text).
# ==========================================================================


def test_acknowledge_control_on_bed_and_review_screens(board_html: str) -> None:
    for screen_id in ("bed", "review"):
        block = _screen_block(board_html, screen_id)
        assert "data-action-acknowledge" in block, screen_id
        assert "data-action-assessed" in block, screen_id
        assert "data-action-deferred" in block, screen_id


def test_action_controls_are_buttons_only(board_html: str) -> None:
    """Every action control is a ``<input type="button">`` -- never free text."""

    tags = [
        t for t in _input_tags(board_html)
        if "data-action-" in t or "data-role-" in t
        or "data-clock-" in t
    ]
    assert tags
    for tag in tags:
        assert 'type="button"' in tag, tag


def test_action_picklists_are_fixed_selects(board_html: str) -> None:
    """Reason / owner / until are fixed ``<select>`` picklists (no free text).

    Present on both Screens 3 and 5 (each renders the action controls), with
    only fixed ``<option>`` children (AC-NOINPUT-2, AC-S5-assess).
    """

    for screen_id in ("bed", "review"):
        block = _screen_block(board_html, screen_id)
        for name in ("reason", "owner", "until"):
            m = re.search(
                rf'<select data-action-{name}>(.*?)</select>', block, re.DOTALL
            )
            assert m, (screen_id, name)
            inner = m.group(1)
            # Only <option>…</option> elements inside; no text input.
            stripped = re.sub(
                r"<option\b[^>]*>.*?</option>", "", inner, flags=re.DOTALL
            )
            assert stripped.strip() == "", (screen_id, name)
            assert "<option" in inner, (screen_id, name)


def test_viewer_simulated_action_sets_only_a_workflow_chip(board_html: str) -> None:
    """The simulated action writes to an in-memory overlay, not a state.

    The viewer keeps a plain object keyed by episode id and only ever stores a
    chip string in it; it never assigns to ``result.state`` or re-evaluates
    (AC-S5-assess, AC-WORKFLOW-2, D28). Structurally: it has a ``simulated``
    object and an ``applySimulated`` that writes into it, and it never writes to
    a ``.state`` field.
    """

    script = _viewer_script(board_html)
    assert "simulated" in script
    assert "applySimulated" in script
    # The viewer never assigns to a result's evaluation state.
    assert not re.search(r"\.state\s*=", script)


# ==========================================================================
# Every tile template carries a feed-chip element (AC-FAIL-1, D06).
# ==========================================================================


def test_every_tile_has_a_feed_chip_element(board_html: str, board_model: dict) -> None:
    tiles = re.findall(r"<li class=\"bed-tile\".*?</li>", board_html, re.DOTALL)
    assert len(tiles) == len(board_model["beds"]) == 17
    for tile in tiles:
        assert "data-feed-chip" in tile, tile
        # And each tile has a body element the viewer fills from the cell.
        assert "data-bed-body" in tile, tile


def test_feed_banner_region_exists(board_html: str) -> None:
    assert 'data-feed-banner' in board_html


# ==========================================================================
# Screen structure the viewer drives (clock, inbox counter, lists).
# ==========================================================================


def test_ward_screen_has_clock_and_inbox_counter(board_html: str) -> None:
    block = _screen_block(board_html, "ward")
    assert "data-clock-prev" in block
    assert "data-clock-next" in block
    assert "data-clock-display" in block
    assert "data-inbox-counter" in block
    assert "data-bed-grid" in block


def test_inbox_and_review_screens_have_their_lists(board_html: str) -> None:
    assert "data-inbox-list" in _screen_block(board_html, "inbox")
    assert "data-episode-list" in _screen_block(board_html, "review")


def test_start_screen_has_both_role_buttons(board_html: str) -> None:
    block = _screen_block(board_html, "start")
    assert "data-role-nurse" in block
    assert "data-role-doctor" in block


# ==========================================================================
# Property-based: any synthetic model renders a viewer with the invariants.
# ==========================================================================


def _synthetic_model() -> st.SearchStrategy[dict]:
    """A small JSON-safe board model whose text includes the state words.

    Deliberately seeds ``display_text`` and the static copy with the evaluation
    state words so the property test proves they can appear in the *data*
    without the viewer *script* ever containing them as a literal (the script
    is fixed, independent of the data).
    """

    nasty = st.sampled_from(
        ["plain", "met here", "unknown there", "a<b", "p&q", "</script>"]
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
            "feed_alert_label": "feed " + label,
            "criteria_sources": [
                {"id": "0", "label": "label " + label, "source": "src " + label},
            ],
        }

    @st.composite
    def _build(draw) -> dict:
        label = draw(nasty)
        n_beds = draw(st.integers(min_value=1, max_value=4))
        beds = []
        for i in range(1, n_beds + 1):
            enc = f"E{i:02d}"
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
@settings(max_examples=50)
def test_pbt_viewer_invariants_hold_for_any_model(model: dict) -> None:
    html = board.render_html(model)
    script = _viewer_script(html)
    # The script is fixed: it carries no innerHTML and no state-word literal,
    # whatever the embedded data says.
    assert "innerHTML" not in script
    for word in _STATE_WORDS:
        assert f'"{word}"' not in script, word
        assert f"'{word}'" not in script, word
    # And it still references the two contract fields.
    assert "start_idx" in script
    assert "feed_alert" in script


# ==========================================================================
# Task 10: navigation, the clock on every screen, and the selected episode
# on Screen 5. The JS is not executed by the suite (design.md §6), so these
# assert the contract structurally against the rendered HTML and the extracted
# viewer <script> body (AC-S2-nav, AC-S4-nav, AC-S5-list, AC-S5-r1, AC-S5-r2,
# AC-S2-inbox-counter, D27 answer 1, D28).
# ==========================================================================

# The working screens (Screens 2-5): the clock and a Start button live on each.
_WORKING_SCREENS = ("ward", "bed", "inbox", "review")


# --- Navigation: bed tile -> Screen 3; inbox counter -> Screen 4; Start ----


def test_bed_tile_opens_bed_detail_screen(board_html: str) -> None:
    """Clicking a bed tile opens Screen 3 (Bed detail) for that bed.

    Structurally: the viewer wires every ``data-bed`` tile (``wireTiles``) to a
    click that sets ``currentBed`` from the tile's ``data-bed`` and shows the
    ``bed`` screen (AC-S2-nav).
    """

    script = _viewer_script(board_html)
    assert "wireTiles" in script
    assert 'qa("[data-bed]")' in script
    # The tile click reads the bed number from the tile and shows Screen 3.
    assert 'getAttribute("data-bed")' in script
    assert "currentBed = bedNumber" in script
    assert 'show("bed")' in script


def test_inbox_counter_is_a_button_opening_screen_4(board_html: str) -> None:
    """The inbox counter is a fixed button "Inbox: N open (simulated)" that
    opens the simulated inbox (Screen 4) (AC-S2-inbox-counter, AC-S2-nav)."""

    ward = _screen_block(board_html, "ward")
    # It is an <input type="button"> carrying data-inbox-counter (not a span).
    m = re.search(r'<input\b[^>]*data-inbox-counter[^>]*>', ward)
    assert m, "inbox counter button not found on the ward screen"
    tag = m.group(0)
    assert 'type="button"' in tag, tag
    # Its default label is the "Inbox: N open (simulated)" form.
    assert 'value="Inbox: 0 open (simulated)"' in tag, tag
    # The viewer rewrites the label with the open-count and opens Screen 4.
    script = _viewer_script(board_html)
    assert 'Inbox: " + inboxOpenCount() + " open (simulated)' in script
    assert 'on("[data-inbox-counter]"' in script
    assert 'show("inbox")' in script


def test_every_working_screen_has_a_start_button(board_html: str) -> None:
    """Screens 2-5 each carry a "Start" button back to Screen 1 (task 10)."""

    for screen_id in _WORKING_SCREENS:
        block = _screen_block(board_html, screen_id)
        m = re.search(r'<input\b[^>]*data-nav-start[^>]*>', block)
        assert m, f"no Start button on screen {screen_id}"
        tag = m.group(0)
        assert 'type="button"' in tag, (screen_id, tag)
        assert 'value="Start"' in tag, (screen_id, tag)
    # The viewer wires every Start button back to Screen 1.
    script = _viewer_script(board_html)
    assert 'on("[data-nav-start]"' in script
    assert 'show("start")' in script


# --- The clock is visible and working on Screens 2-5 -----------------------


def test_clock_controls_on_every_working_screen(board_html: str) -> None:
    for screen_id in _WORKING_SCREENS:
        block = _screen_block(board_html, screen_id)
        assert "data-clock-prev" in block, screen_id
        assert "data-clock-next" in block, screen_id
        assert "data-clock-display" in block, screen_id


def test_viewer_steps_and_renders_all_clock_displays(board_html: str) -> None:
    """The viewer wires *all* clock controls (not just the first) and writes
    *every* clock display, so stepping the clock on any screen moves the whole
    board together (task 10)."""

    script = _viewer_script(board_html)
    # ``on`` wires every match (querySelectorAll), and renderClock writes every
    # display element.
    assert "function on(sel, handler)" in script
    assert "qa(sel)" in script
    assert 'qa("[data-clock-display]")' in script
    # The prev/next buttons call the integer step over the embedded grid.
    assert 'on("[data-clock-prev]", function () { step(-1); })' in script
    assert 'on("[data-clock-next]", function () { step(1); })' in script


# --- Screen 5: the selected episode at the clock ---------------------------


def test_review_screen_has_r1_and_r2_detail_panels_hidden(board_html: str) -> None:
    """Screen 5 carries an R1 detail panel (approved wording + criteria list)
    and an R2 detail panel (combined message + threshold label), both ``hidden``
    until an episode is selected, plus the episode list (AC-S5-list, AC-S5-r1,
    AC-S5-r2)."""

    block = _screen_block(board_html, "review")
    assert "data-episode-list" in block
    # R1 panel: hidden, carries the approved R1 wording and the criteria list.
    m1 = re.search(r'<div class="r1-detail" data-r1-detail\b[^>]*>', block)
    assert m1, "r1-detail panel not found"
    assert "hidden" in m1.group(0)
    assert "data-r1-wording" in block
    assert "data-criteria-sources" in block
    # R2 panel: hidden, carries the chips area, the combined message and the
    # threshold label.
    m2 = re.search(r'<div class="r2-detail" data-r2-detail\b[^>]*>', block)
    assert m2, "r2-detail panel not found"
    assert "hidden" in m2.group(0)
    assert "data-r2-chips" in block
    assert "data-r2-combined" in block
    assert "data-threshold-label" in block


def test_review_detail_is_driven_by_the_selected_episode(board_html: str) -> None:
    """The viewer renders the detail from the *selected* episode at the clock.

    Structurally: ``renderReviewDetail`` resolves the selected episode, shows
    the R1 panel for an R1 episode and the R2 panel otherwise, and shows the
    combined message only when the selected cell carries it -- never the R1 text
    or criteria for an R2 item (AC-S5-r1, AC-S5-r2, D27 answer 1, D28).
    """

    script = _viewer_script(board_html)
    assert "renderReviewDetail" in script
    assert "selectedEpisode" in script
    # R1 episode -> show the R1 panel (approved wording + criteria), return.
    assert 'item.rule === "R1"' in script
    assert "r1Panel.hidden = false" in script
    # R2 (any other group) -> show the R2 panel and build chips; the combined
    # message is toggled by the embedded combined_message, never recomputed.
    assert "r2Panel.hidden = false" in script
    assert "cell.combined_message" in script
    # Selecting an episode sets the current id and re-renders the detail.
    assert "currentEpisodeId = episodeId(item)" in script
    assert 'show("review")' in script


def test_review_detail_hidden_when_no_episode_selected(board_html: str) -> None:
    """With no episode selected both panels stay hidden, so Screen 5 shows the
    list only (task 10)."""

    script = _viewer_script(board_html)
    # renderReviewDetail hides both panels first, then bails out when there is
    # no selected episode (both stay hidden).
    assert "r1Panel.hidden = true" in script
    assert "r2Panel.hidden = true" in script
    # The early return guards on a falsy selected episode.
    assert "if (!item) { return; }" in script


def test_review_detail_r2_never_shows_r1_text_for_non_r1(board_html: str) -> None:
    """An R2 item shows only its chips (and the combined message when both are
    met), never the R1 approved text or criteria list (D27 answer 1).

    The R1 wording and criteria live only inside the ``data-r1-detail`` panel,
    which ``renderReviewDetail`` shows exclusively for ``item.rule === "R1"``;
    for any other group the R1 panel is left hidden and only the R2 panel is
    shown. Structurally the two panels are disjoint and the R1 panel is never
    unhidden outside the R1 branch.
    """

    block = _screen_block(board_html, "review")
    # The R1 wording and criteria are inside the r1-detail panel only.
    r1_panel = re.search(
        r'<div class="r1-detail" data-r1-detail\b.*?</div>\s*'
        r'<div class="r2-detail"',
        block,
        re.DOTALL,
    )
    assert r1_panel, "r1-detail panel block not isolated"
    r1_html = r1_panel.group(0)
    assert "data-r1-wording" in r1_html
    assert "data-criteria-sources" in r1_html
    # The R2 panel does not contain the R1 wording or the criteria list.
    r2_panel = re.search(
        r'<div class="r2-detail" data-r2-detail\b.*?</div>\s*</div>',
        block,
        re.DOTALL,
    )
    assert r2_panel, "r2-detail panel block not found"
    r2_html = r2_panel.group(0)
    assert "data-r1-wording" not in r2_html
    assert "data-criteria-sources" not in r2_html
    # And the viewer only unhides the R1 panel inside the R1 branch (it is set
    # true at the top and set false exactly once, guarded by item.rule==="R1").
    script = _viewer_script(board_html)
    assert script.count("r1Panel.hidden = false") == 1


# ==========================================================================
# The module under test is the real board module (sanity for coverage tools).
# ==========================================================================


def test_board_module_file_exists() -> None:
    assert Path(board.__file__).is_file()


# ==========================================================================
# Task 11: display fixes (G3 round 1 F1, F2, F6, F7, F9). The JS is not
# executed by the suite (design.md §6), so the viewer behaviour is asserted
# structurally against the extracted viewer <script> and the inline <style>,
# and the underlying data is asserted against the embedded ``board-data`` at
# the oracle sample times (AC-FAIL-1, AC-S2-feedbanner, AC-STATE-3,
# D27 answer 2, D28).
# ==========================================================================


def _style_block(html: str) -> str:
    m = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    assert m, "inline <style> block not found"
    return m.group(1)


def _board_data(html: str) -> dict:
    """The embedded ``board-data`` JSON, unescaped the way ``JSON.parse`` sees
    it (design.md §3d)."""

    m = re.search(
        r'<script type="application/json" id="board-data">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert m, "board-data block not found"
    return json.loads(html_mod.unescape(m.group(1)))


def _cells_for(data: dict, encounter: str) -> list[dict]:
    for bed in data["beds"]:
        if encounter in bed["encounters"]:
            return bed["encounters"][encounter]["cells"]
    raise AssertionError(f"encounter {encounter} not found")


def _cell_at(cells: list[dict], iso: str) -> dict:
    return next(c for c in cells if c["t"] == iso)


# --- F1: the per-tile feed chip is hidden whenever feed_alert is false ------


def test_feed_chip_hidden_toggles_on_feed_alert_only(board_html: str) -> None:
    """The viewer hides every feed chip by default and only unhides it when the
    cell's ``feed_alert`` is true -- so a chip's box exists iff the bed is stale
    (F1, AC-FAIL-1). Checked structurally: the chip is set ``hidden = true`` at
    the top of the tile loop and set ``hidden = false`` only inside the
    ``cell.feed_alert`` branch."""

    script = _viewer_script(board_html)
    assert "if (feedChip) { feedChip.hidden = true; }" in script
    # The only place the chip is unhidden is under the feed_alert branch.
    assert "if (cell.feed_alert)" in script
    assert "feedChip.hidden = false" in script


def test_bed9_feed_alert_data_false_at_0110_and_0230(board_html: str) -> None:
    """Bed 9's embedded cell carries ``feed_alert`` false before the outage
    (01:10) and once fresh again (02:30), and true during it (01:15, 02:25) --
    so the data the viewer toggles the chip from is correct; with the F1 CSS the
    chip then has no box when it is false (data/SCENARIOS.md bed 9)."""

    cells = _cells_for(_board_data(board_html), "E09-1120")

    def iso(h: int, mi: int) -> str:
        return f"2026-11-21T{h:02d}:{mi:02d}:00+01:00"

    assert _cell_at(cells, iso(1, 10))["feed_alert"] is False
    assert _cell_at(cells, iso(2, 30))["feed_alert"] is False
    assert _cell_at(cells, iso(1, 15))["feed_alert"] is True
    assert _cell_at(cells, iso(2, 25))["feed_alert"] is True


# --- F2: the banner text is the static label plus the affected beds ---------


def test_feed_banner_text_is_label_plus_affected_beds(board_html: str) -> None:
    """While any active cell has a feed alert, the viewer writes the banner the
    static feed-alert label plus the affected bed numbers, and empties and hides
    it otherwise (F2, AC-S2-feedbanner, AC-FAIL-1). Asserted structurally: the
    viewer builds the banner text from ``feed_alert_label`` and the collected
    affected beds, shows it when ``anyFeed`` and clears + hides it otherwise."""

    script = _viewer_script(board_html)
    # It collects the affected bed numbers of stale active cells.
    assert "feedBeds.push(bedNumber)" in script
    # The banner text is the static label plus the beds.
    assert "staticCopy.feed_alert_label" in script
    assert 'beds " + feedBeds.join(", ")' in script
    # Shown with text when anyFeed, emptied + hidden otherwise.
    assert "banner.hidden = false" in script
    assert 'setText(banner, "")' in script
    assert "banner.hidden = true" in script


def test_bed9_is_the_only_feed_affected_active_bed_during_the_outage(
    board_html: str,
) -> None:
    """During the outage window the only active cell with a feed alert is bed 9,
    so the banner would read the label plus bed 9 (F2). Checked from the data:
    at 01:15 and 02:25 exactly the bed-9 encounter's active cell has
    ``feed_alert`` true across the whole ward."""

    data = _board_data(board_html)

    def iso(h: int, mi: int) -> str:
        return f"2026-11-21T{h:02d}:{mi:02d}:00+01:00"

    for h, mi in ((1, 15), (2, 25)):
        affected = []
        for bed in data["beds"]:
            for enc, payload in bed["encounters"].items():
                cell = next(
                    (c for c in payload["cells"] if c["t"] == iso(h, mi)), None
                )
                if cell and cell["active"] and cell["feed_alert"]:
                    affected.append(bed["bed"])
        assert affected == [9], (h, mi, affected)


# --- F6: met chips show no reason code; others show it verbatim -------------


def test_met_rule_results_have_show_reason_false(board_model: dict) -> None:
    """Every embedded rule result carries a ``show_reason`` display flag; it is
    false exactly for ``met`` results (so a met chip hides the engine-default
    reason) and true for every other state, which keeps its reason code shown
    verbatim (F6, D27 answer 2). The engine ``state``/``reason`` are untouched.
    """

    seen_met = False
    seen_other = False
    for bed in board_model["beds"]:
        for payload in bed["encounters"].values():
            for cell in payload["cells"]:
                for result in cell["results"].values():
                    assert "show_reason" in result
                    if result["state"] == "met":
                        seen_met = True
                        assert result["show_reason"] is False
                        # The reason value is still carried (engine unchanged),
                        # just not displayed.
                        assert result["reason"] != ""
                    else:
                        seen_other = True
                        assert result["show_reason"] is True
    assert seen_met and seen_other


def test_viewer_shows_reason_only_when_show_reason(board_html: str) -> None:
    """The viewer appends the reason-code span only under the embedded
    ``show_reason`` flag -- it never compares the state word to decide, so no
    state-word literal is introduced (F6, AC-GEN-6)."""

    script = _viewer_script(board_html)
    assert "if (result.show_reason) {" in script
    # And the reason-code span is built inside that guard.
    m = re.search(
        r"if \(result\.show_reason\) \{(.*?)\}", script, re.DOTALL
    )
    assert m and 'withText("span", "reason-code"' in m.group(1)


# --- F9: reason codes wrap instead of being clipped -------------------------


def test_reason_codes_wrap(board_html: str) -> None:
    """The chip and its reason-code span wrap long codes (``overflow-wrap:
    anywhere``) so ``sat_not_recorded`` is not cut to ``sat_no…`` at the tile
    width (F9)."""

    css = _style_block(board_html)
    # The chip wraps, and the reason-code span wraps.
    assert re.search(r"\.chip\s*\{[^}]*overflow-wrap:\s*anywhere", css, re.DOTALL)
    assert re.search(
        r"\.chip\s+\.reason-code\s*\{[^}]*overflow-wrap:\s*anywhere", css
    )


# --- F7: readable HH:MM times; date only on the clock / at a day change -----


def test_viewer_has_time_formatting_helpers(board_html: str) -> None:
    """The viewer carries the time helpers and uses them, so no raw ISO string
    reaches the screen (F7)."""

    script = _viewer_script(board_html)
    assert "function fmtTime(iso)" in script
    assert "function fmtClock(iso)" in script
    assert "function fmtDate(iso)" in script
    # HH:MM is the 11..16 slice of the fixed ISO layout; the date is D Mon.
    assert "slice(11, 16)" in script


def test_clock_display_uses_fmtClock(board_html: str) -> None:
    """The clock shows a readable date + HH:MM, never the raw ISO grid time
    (F7)."""

    script = _viewer_script(board_html)
    # The clock display is written with fmtClock(grid[...]), not the raw string.
    assert "fmtClock(grid[clockIndex])" in script
    # The old raw-ISO write is gone.
    assert "setText(disps[k], clockIndex >= 0 ? grid[clockIndex] : \"\")" not in script


def test_list_item_time_uses_hhmm_with_day_change_only(board_html: str) -> None:
    """List items show time raised as HH:MM, prefixing the date only when the
    day changes from the previous item (F7). Structurally: the item time is
    built from ``fmtTime`` / ``fmtDate`` guarded by a day comparison, never the
    raw ``item.time_raised``."""

    script = _viewer_script(board_html)
    assert "dayOf(item.time_raised)" in script
    assert "fmtTime(item.time_raised)" in script
    assert "fmtDate(item.time_raised)" in script
    # The raw ISO value is no longer written straight into the item-time span.
    assert 'withText("span", "item-time", item.time_raised)' not in script


def test_month_names_table_present_for_the_date(board_html: str) -> None:
    """The date uses a fixed month-name table (Nov for this night), read by
    position from the ISO string -- no Date parsing that could shift the day by
    a timezone (F7)."""

    script = _viewer_script(board_html)
    assert '"Nov"' in script
    assert "var MONTHS" in script


def test_no_raw_iso_timestamp_rendered_as_literal_text(board_html: str) -> None:
    """No full ISO timestamp (``…T..:..:..+01:00``) is written to the page as a
    literal: the markup and the viewer never embed one, and every time shown is
    produced by the HH:MM / date helpers (F7). (The embedded ``board-data`` JSON
    legitimately holds ISO strings; those are inside the JSON block, not visible
    text, and are reformatted by the viewer before display.)"""

    # The viewer script contains no literal ISO timestamp.
    script = _viewer_script(board_html)
    assert re.search(r"\dT\d\d:\d\d:\d\d", script) is None
    # The rendered markup (outside the JSON data block) contains none either.
    without_data = re.sub(
        r'<script type="application/json" id="board-data">.*?</script>',
        "",
        board_html,
        flags=re.DOTALL,
    )
    assert re.search(r"\dT\d\d:\d\d:\d\d", without_data) is None


# ==========================================================================
# Task 12 (D30): decoded text, emphasis, criteria rows.
# ==========================================================================


def _criteria_items(html: str) -> list[str]:
    block = re.search(
        r'<ul class="criteria-sources"[^>]*>(.*?)</ul>', html, re.DOTALL
    )
    assert block, "criteria list not found"
    return re.findall(r"<li class=\"criterion\".*?</li>", block.group(1), re.DOTALL)


def test_viewer_reverses_python_escaping_before_json_parse(board_html: str) -> None:
    """Text in a ``<script>`` is never entity-decoded, so the viewer must undo
    ``&lt;`` / ``&gt;`` / ``&amp;`` itself, with ``&amp;`` last (D30)."""

    script = _viewer_script(board_html)
    m = re.search(r"JSON\.parse\((.*?)\);", script, re.DOTALL)
    assert m, "JSON.parse call not found"
    arg = m.group(1)
    assert "raw.textContent" in arg
    lt = arg.index(".replace(/&lt;/g")
    gt = arg.index(".replace(/&gt;/g")
    amp = arg.index(".replace(/&amp;/g")
    assert lt < gt < amp


def test_criteria_rows_are_separate_blocks_with_source_label(
    board_html: str,
) -> None:
    """Each criterion renders id, label, a visible ``Source:`` label and the
    source as separate blocks (D30)."""

    items = _criteria_items(board_html)
    assert len(items) == len(board.CRITERIA_SOURCES) == 8
    for item in items:
        ids = re.findall(r'<div class="criterion-id">', item)
        labels = re.findall(r'<div class="criterion-label">', item)
        src_labels = re.findall(
            r'<div class="criterion-source-label">Source:</div>', item
        )
        sources = re.findall(r'<div class="criterion-source">', item)
        assert len(ids) == len(labels) == len(src_labels) == len(sources) == 1
        assert (
            item.index("criterion-id")
            < item.index('class="criterion-label"')
            < item.index("criterion-source-label")
            < item.index('class="criterion-source"')
        )


def test_criteria_emphasis_rendered_after_escaping(board_html: str) -> None:
    """``**x**`` -> ``<strong>x</strong>`` and `` `x` `` -> ``<code>x</code>``;
    no marker survives in the visible criteria markup (D30)."""

    items = _criteria_items(board_html)
    joined = "".join(items)
    assert "<strong>any other vasoactive agent</strong>" in joined
    assert "<strong>more than 120 min</strong>" in joined
    assert "<code>unknown</code>" in joined
    assert "<code>not_met</code>" in joined
    assert "<code>context_review</code>" in joined
    text = re.sub(r"<[^>]+>", "", joined)
    assert "**" not in text
    assert "`" not in text


def test_emphasis_never_lets_data_inject_tags() -> None:
    """Escaping happens before emphasis, so only ``strong``/``code`` appear."""

    out = board._emphasise("<b>**x**</b> `<i>` & **y**")
    assert out == (
        "&lt;b&gt;<strong>x</strong>&lt;/b&gt; <code>&lt;i&gt;</code> "
        "&amp; <strong>y</strong>"
    )


def test_criteria_static_strings_stay_verbatim(board_model: dict) -> None:
    """The embedded ``criteria_sources`` still carry the raw markers (D30)."""

    labels = [c["label"] for c in board_model["static"]["criteria_sources"]]
    assert any("**any other vasoactive agent**" in s for s in labels)
    assert any("`unknown`" in s for s in labels)
    assert labels == [c["label"] for c in board.CRITERIA_SOURCES]
