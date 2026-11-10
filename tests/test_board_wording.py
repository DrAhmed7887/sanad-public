"""Verbatim wording, persistent label and palette (tasks.md task 4).

The rendered board must carry the signed regulatory copy **verbatim**, must use
no banned public phrase and must never describe a silent or non-triggering bed
as safe / stable / clear / green -- and its palette must contain no green at all
(``.kiro/steering/safety.md`` top hazard D06: false reassurance). This module
proves those guarantees against the generated HTML and anchors every hand-typed
string to its signed source so the copy cannot drift:

* **scenario-oracle style tests** over the real fixed dataset (via the shared
  ``board_html`` / ``board_model`` fixtures): the generated HTML contains the
  persistent label, the intended-use statement, the verification-vs-validation
  sentence, the ward line, the four ``states`` texts, the threshold label,
  "fluid balance unknown" and the R1 criteria source lines **verbatim**; a drift
  test reads ``docs/EVIDENCE.md`` / ``docs/UI_FLOW.md`` at test time and asserts
  each hand-typed string appears verbatim in its source document; no banned
  phrase from ``docs/EVIDENCE.md`` appears (case-insensitive); no banned-silence
  word appears as a whole word in the visible text; and every colour in the
  inline ``<style>`` block is in the palette constants and none is green
  (AC-LABEL-1..4, AC-STATE-3, AC-S3-threshold-label, AC-SILENCE-1/2/4, AC-S5-r1);
* **property-based tests** (hypothesis) over the palette and over synthetic
  colours: every palette colour is non-green by the requirement's HSL rule, and
  the green test correctly classifies arbitrary hues (no real data, no network
  -- ``.kiro/steering/tech.md``).

Reads the fixed dataset and the frozen baseline **read-only**; never writes to
``docs/`` or ``data/`` (safety steering sign-off gate).
"""

from __future__ import annotations

import colorsys
import re
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from sanad import board
from sanad.states import BANNED_SILENCE_WORDS

_REPO = Path(__file__).resolve().parent.parent
_EVIDENCE = _REPO / "docs" / "EVIDENCE.md"
_UI_FLOW = _REPO / "docs" / "UI_FLOW.md"


# ==========================================================================
# Helpers.
# ==========================================================================


def _style_block(html: str) -> str:
    m = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    assert m, "no <style> block found"
    return m.group(1)


def _hex_colours(css: str) -> list[str]:
    """Every ``#rrggbb`` / ``#rgb`` colour literal in the CSS, lower-cased."""

    return [c.lower() for c in re.findall(r"#[0-9a-fA-F]{3,6}\b", css)]


def _hex_to_rgb(hex_colour: str) -> tuple[float, float, float]:
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return r, g, b


def _is_green(hex_colour: str) -> bool:
    """A colour is "green" iff its hue is 75°-165° with saturation > 20%.

    This is the requirement's definition (tasks.md task 4): a greenish tint is a
    hue in the green band with meaningful saturation; near-greys (very low
    saturation) are allowed whatever their nominal hue. ``colorsys`` returns HLS
    with hue and saturation in 0..1, so the hue band is 75/360..165/360 and the
    saturation floor is 0.20.
    """

    r, g, b = _hex_to_rgb(hex_colour)
    hue, _light, sat = colorsys.rgb_to_hls(r, g, b)
    hue_deg = hue * 360.0
    return 75.0 <= hue_deg <= 165.0 and sat > 0.20


def _visible_text(html: str) -> str:
    """HTML with ``<script>`` and ``<style>`` blocks and all tags removed.

    The banned-silence-word check runs over what a reader actually sees, so the
    embedded JSON (a ``<script>`` block) and the stylesheet are stripped, then
    the remaining tags are removed and the ``value="..."`` of each control is
    kept (button labels are visible text).
    """

    no_script = re.sub(r"<script\b.*?</script>", " ", html, flags=re.DOTALL)
    no_style = re.sub(r"<style\b.*?</style>", " ", no_script, flags=re.DOTALL)
    # Keep button labels (their visible text lives in the value attribute).
    values = " ".join(re.findall(r'value="([^"]*)"', no_style))
    no_tags = re.sub(r"<[^>]+>", " ", no_style)
    return no_tags + " " + values


def _banned_phrases() -> list[str]:
    """The banned public phrases, parsed from ``docs/EVIDENCE.md`` at test time.

    Never hard-coded (so the test tracks the signed baseline): the "Banned
    wording:" line lists the phrases in double quotes.
    """

    text = _EVIDENCE.read_text(encoding="utf-8")
    m = re.search(r"\*\*Banned wording:\*\*\s*(.+)", text)
    assert m, "banned-wording line not found in docs/EVIDENCE.md"
    phrases = re.findall(r'"([^"]+)"', m.group(1))
    assert phrases, "no banned phrases parsed"
    return phrases


# ==========================================================================
# Verbatim wording in the generated HTML (AC-LABEL-*, AC-STATE-3, labels).
# ==========================================================================


def _in_html(text: str, html: str) -> bool:
    """True if ``text`` appears in ``html``, allowing for HTML escaping.

    Every string the renderer writes is passed through ``board._escape_text``
    (``&`` → ``&amp;``, ``<`` → ``&lt;``, ``>`` → ``&gt;``), and the embedded
    ``board-data`` JSON is escaped the same way. So a criterion label like
    "SBP > 90 mmHg" is stored as "SBP &gt; 90 mmHg". The string is verbatim iff
    its escaped form is present; strings with no special character escape to
    themselves, so this also covers the plain regulatory copy.
    """

    return board._escape_text(text) in html


def test_html_contains_the_verbatim_regulatory_copy(board_html: str) -> None:
    for text in (
        board.PERSISTENT_LABEL,
        board.INTENDED_USE,
        board.VERIFICATION,
        board.WARD_LINE,
    ):
        assert _in_html(text, board_html), text


def test_html_contains_the_four_states_texts_verbatim(
    board_html: str, board_model: dict
) -> None:
    static = board_model["static"]
    for key in ("silence_text", "r1_met_text", "r2_combined_text", "r3_overdue_text"):
        assert _in_html(static[key], board_html), key


def test_html_contains_the_threshold_and_fluid_unknown_labels(
    board_html: str,
) -> None:
    assert _in_html(board.THRESHOLD_LABEL, board_html)
    assert _in_html(board.FLUID_UNKNOWN_LABEL, board_html)


def test_html_contains_each_r1_criterion_label_and_source(board_html: str) -> None:
    """Screen 5 shows the R1 criteria list (0, a-f, the 120-min duration) with
    each criterion's source line verbatim (AC-S5-r1, D28)."""

    assert board.CRITERIA_SOURCES  # 0, a-f, duration
    ids = [c["id"] for c in board.CRITERIA_SOURCES]
    assert ids == ["0", "a", "b", "c", "d", "e", "f", "⏱"]
    for c in board.CRITERIA_SOURCES:
        assert _in_html(c["label"], board_html), c["id"]
        assert _in_html(c["source"], board_html), c["id"]


# ==========================================================================
# Drift guard: each hand-typed string is verbatim in its source document.
# ==========================================================================


def test_regulatory_copy_is_verbatim_in_evidence() -> None:
    text = _EVIDENCE.read_text(encoding="utf-8")
    assert board.PERSISTENT_LABEL in text
    assert board.INTENDED_USE in text
    assert board.VERIFICATION in text


def test_ward_line_is_verbatim_in_ui_flow() -> None:
    assert board.WARD_LINE in _UI_FLOW.read_text(encoding="utf-8")


def test_threshold_and_fluid_labels_are_verbatim_in_sources() -> None:
    evidence = _EVIDENCE.read_text(encoding="utf-8")
    ui_flow = _UI_FLOW.read_text(encoding="utf-8")
    # The threshold label appears verbatim in UI_FLOW's "Approved strings";
    # "fluid balance unknown" appears verbatim in both the baseline and UI_FLOW.
    assert board.THRESHOLD_LABEL in ui_flow
    assert board.FLUID_UNKNOWN_LABEL in evidence
    assert board.FLUID_UNKNOWN_LABEL in ui_flow


def test_each_r1_criterion_source_is_verbatim_in_evidence() -> None:
    text = _EVIDENCE.read_text(encoding="utf-8")
    for c in board.CRITERIA_SOURCES:
        assert c["source"] in text, c["id"]
        assert c["label"] in text, c["id"]


# ==========================================================================
# No banned public phrase; no banned-silence word in visible text.
# ==========================================================================


def test_no_banned_public_phrase_appears(board_html: str) -> None:
    lowered = board_html.lower()
    for phrase in _banned_phrases():
        assert phrase.lower() not in lowered, phrase


def test_no_banned_silence_word_in_visible_text(
    board_html: str, board_model: dict
) -> None:
    """No safe/stable/clear/green as a whole word in anything a reader sees.

    Checked over the visible text (``<script>``/``<style>`` stripped) plus every
    embedded ``display_text`` (the silence/other per-cell strings the viewer
    writes), so a banned word can hide in neither the markup nor the data
    (AC-SILENCE-2). The fixed ``VERIFICATION`` sentence is allowed even though it
    contains no banned word; this test does not need to exempt it.
    """

    visible = _visible_text(board_html)
    # Add every embedded display_text so a per-cell string is checked too.
    display_texts = []
    for bed in board_model["beds"]:
        for enc in bed["encounters"].values():
            for cell in enc["cells"]:
                display_texts.append(cell.get("display_text", ""))
    haystack = (visible + " " + " ".join(display_texts)).lower()

    for word in BANNED_SILENCE_WORDS:
        assert re.search(rf"\b{re.escape(word)}\b", haystack) is None, word


# ==========================================================================
# Palette: every colour is a declared palette colour, and none is green.
# ==========================================================================


def test_every_style_colour_is_a_declared_palette_colour(board_html: str) -> None:
    css = _style_block(board_html)
    used = set(_hex_colours(css))
    palette = {c.lower() for c in board.PALETTE}
    assert used, "no colours found in the stylesheet"
    assert used <= palette, used - palette


def test_no_palette_colour_is_green() -> None:
    for colour in board.PALETTE:
        assert not _is_green(colour), colour


def test_no_style_colour_is_green(board_html: str) -> None:
    css = _style_block(board_html)
    for colour in _hex_colours(css):
        assert not _is_green(colour), colour


# ==========================================================================
# Property-based: the green classifier and the palette.
# ==========================================================================


@given(
    hue_deg=st.integers(min_value=80, max_value=160),
    sat=st.floats(min_value=0.40, max_value=1.0),
    light=st.floats(min_value=0.30, max_value=0.70),
)
@settings(max_examples=60)
def test_pbt_green_band_is_flagged(hue_deg: int, sat: float, light: float) -> None:
    """A clearly-green colour (well inside the 75-165 deg band, well-saturated)
    is always classified green, so a greenish colour could never slip past
    ``_is_green``."""

    r, g, b = colorsys.hls_to_rgb(hue_deg / 360.0, light, sat)
    hex_colour = "#{:02x}{:02x}{:02x}".format(
        round(r * 255), round(g * 255), round(b * 255)
    )
    assert _is_green(hex_colour)


@given(
    hue_deg=st.integers(min_value=0, max_value=360),
    light=st.floats(min_value=0.0, max_value=1.0),
)
@settings(max_examples=60)
def test_pbt_near_grey_is_never_green(hue_deg: int, light: float) -> None:
    """A near-grey (saturation ≤ 20%) is never flagged green, whatever its
    nominal hue -- the neutral greys in the palette are allowed."""

    r, g, b = colorsys.hls_to_rgb(hue_deg / 360.0, light, 0.10)
    hex_colour = "#{:02x}{:02x}{:02x}".format(
        round(r * 255), round(g * 255), round(b * 255)
    )
    assert not _is_green(hex_colour)
