"""Executed-browser regression tests for the offline board's user flows.

These tests drive the generated HTML in headless Chromium through Playwright.
They use the visible controls and rendered DOM only: no viewer globals are
modified and no clinical result is recomputed. Playwright is test-only tooling;
the generated board remains a self-contained, stdlib-generated offline file.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Page, expect, sync_playwright


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    """Fail rather than skip when the explicitly installed browser is absent."""

    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture(scope="session")
def board_url(tmp_path_factory: pytest.TempPathFactory, board_html: str) -> str:
    path = tmp_path_factory.mktemp("executed-browser") / "board.html"
    path.write_text(board_html, encoding="utf-8", newline="\n")
    return path.as_uri()


@pytest.fixture
def page(browser: Browser, board_url: str) -> Iterator[Page]:
    instance = browser.new_page()
    instance.set_default_timeout(5_000)
    try:
        instance.context.set_offline(True)
        instance.goto(board_url)
        yield instance
    finally:
        instance.close()


def set_clock(page: Page, hhmm: str) -> None:
    """Advance through the visible five-minute control to the requested time."""

    page.evaluate(
        """(target) => {
          const display = document.querySelector(
            '[data-screen]:not([hidden]) [data-clock-display]'
          );
          const next = document.querySelector(
            '[data-screen]:not([hidden]) [data-clock-next]'
          );
          if (!display || !next) throw new Error('visible clock not found');
          for (let steps = 0; steps < 145; steps += 1) {
            if (display.textContent.endsWith(target)) return;
            const before = display.textContent;
            next.click();
            if (display.textContent === before) {
              throw new Error('clock stopped before ' + target + ' at ' + before);
            }
          }
          throw new Error('target time not reached: ' + target);
        }""",
        hhmm,
    )
    expect(
        page.locator("[data-screen]:not([hidden]) [data-clock-display]")
    ).to_have_text(re.compile(rf" {hhmm}$"))


@pytest.mark.parametrize("entry", ["inbox", "ward tile"])
def test_acknowledge_updates_bed10_r3_workflow_without_changing_state(
    page: Page, entry: str
) -> None:
    """At 01:10 either route to bed 10 must operate on its open R3 episode."""

    page.locator("[data-role-nurse]").click()
    set_clock(page, "01:10")
    if entry == "inbox":
        page.locator("[data-inbox-counter]").click()
        item = page.locator('[data-inbox-list] [data-episode-id]').filter(
            has_text="Bed 10"
        ).filter(has_text="R3")
        expect(item).to_have_count(1)
        expect(item.locator(".item-workflow")).to_have_text("notified")
        item.click()
    else:
        page.locator('[data-bed="10"]').click()

    r3_row = page.locator("[data-bed-detail] .rule-row").filter(
        has=page.locator('[data-rule="R3"]')
    )
    expect(r3_row.locator('[data-rule="R3"] .state-word')).to_have_text("met")
    expect(r3_row.locator(".workflow-beside")).to_have_text("notified")

    page.locator(
        '[data-screen="bed"]:not([hidden]) [data-action-acknowledge]'
    ).click()

    expect(r3_row.locator('[data-rule="R3"] .state-word')).to_have_text("met")
    expect(r3_row.locator(".workflow-beside")).to_have_text("acknowledged")


def test_deferred_uses_the_visible_owner_and_until_picklists(page: Page) -> None:
    """Screen 5 must not read Screen 3's hidden default selections."""

    page.locator("[data-role-doctor]").click()
    set_clock(page, "01:30")
    item = page.locator('[data-episode-id="E15-1120:R1:78"]')
    expect(item).to_have_count(1)
    item.click()

    screen = page.locator('[data-screen="review"]:not([hidden])')
    screen.locator("[data-action-owner]").select_option("charge nurse")
    screen.locator("[data-action-until]").select_option("01:30")
    screen.locator("[data-action-deferred]").click()

    expect(
        page.locator(
            '[data-episode-id="E15-1120:R1:78"] .item-workflow'
        )
    ).to_have_text("deferred · charge nurse · until 01:30")

    # Existing positive invariant: simulated actions are memory-only.
    page.reload()
    page.locator("[data-role-doctor]").click()
    set_clock(page, "01:30")
    expect(
        page.locator(
            '[data-episode-id="E15-1120:R1:78"] .item-workflow'
        )
    ).to_have_text("")


@pytest.mark.parametrize(
    ("hhmm", "label"),
    [("01:05", "next check due"), ("01:10", "overdue since")],
)
def test_r3_detail_uses_readable_hhmm_times(
    page: Page, hhmm: str, label: str
) -> None:
    """Both R3 due and overdue details must hide the embedded ISO timestamp."""

    page.locator("[data-role-nurse]").click()
    set_clock(page, hhmm)
    page.locator('[data-bed="10"]').click()

    detail = page.locator(
        '[data-bed-detail] [data-rule="R3"] .detail'
    )
    expect(detail).to_have_text(re.compile(rf"^{label} \d{{2}}:\d{{2}}$"))
    expect(detail).not_to_contain_text("2026-11-")


def test_selected_r1_episode_shows_current_state_and_approved_detail(
    page: Page,
) -> None:
    """An R1 selection needs its current result, not only the static panel."""

    page.locator("[data-role-doctor]").click()
    set_clock(page, "01:30")
    page.locator('[data-episode-id="E15-1120:R1:78"]').click()

    panel = page.locator('[data-screen="review"] [data-r1-detail]')
    expect(panel).to_be_visible()
    expect(panel.locator('[data-rule="R1"]')).to_have_count(1)
    expect(panel.locator('[data-rule="R1"] .state-word')).to_have_text("met")
    expect(panel.locator('[data-rule="R1"] .approved-message')).to_have_count(0)
    expect(panel.locator("[data-r1-wording]")).to_be_visible()
    expect(panel.locator("[data-criterion]")).to_have_count(8)


def test_doctor_list_contains_only_open_episodes_at_0200(page: Page) -> None:
    """Ended R1/R2 runs disappear while still-open Bed 6 R2 remains."""

    page.locator("[data-role-doctor]").click()
    set_clock(page, "02:00")

    expected = page.evaluate(
        """() => {
          const data = JSON.parse(document.getElementById('board-data').textContent);
          const index = data.grid_times.findIndex((t) => t.slice(11, 16) === '02:00');
          if (index < 0) throw new Error('02:00 not in grid');
          return data.episodes
            .filter((item) => item.start_idx <= index && index <= item.end_idx)
            .map((item) => item.encounter + ':' + item.rule + ':' + item.start_idx);
        }"""
    )
    assert "E15-1120:R1:19" not in expected
    assert "E06-1120:R2:73" in expected

    expect(page.locator('[data-episode-id="E15-1120:R1:19"]')).to_have_count(0)
    actual = page.locator("[data-episode-list] [data-episode-id]").evaluate_all(
        "elements => elements.map((element) => element.dataset.episodeId)"
    )
    assert actual == expected


def test_feed_alert_positive_flow_at_0115(page: Page) -> None:
    """The existing Bed 9 stale-feed alert remains visible on the ward."""

    page.locator("[data-role-nurse]").click()
    set_clock(page, "01:15")

    expect(page.locator("[data-feed-banner]")).to_be_visible()
    expect(page.locator("[data-feed-banner]")).to_have_text("feed alert · beds 9")
    bed9 = page.locator('[data-bed="9"]')
    expect(bed9.locator("[data-feed-chip]")).to_be_visible()
    expect(bed9.locator('[data-rule="R1"] .state-word')).to_have_text("unknown")
    expect(bed9.locator('[data-rule="R1"] .reason-code')).to_have_text(
        "stale_data"
    )
    expect(page.locator('[data-bed="7"] [data-feed-chip]')).to_be_hidden()


def test_bed6_combined_r2_positive_flow_at_0200(page: Page) -> None:
    """The open Bed 6 item still renders both R2 states and combined text."""

    page.locator("[data-role-doctor]").click()
    set_clock(page, "02:00")
    page.locator('[data-episode-id="E06-1120:R2:73"]').click()

    panel = page.locator('[data-screen="review"] [data-r2-detail]')
    expect(panel).to_be_visible()
    expect(panel.locator('[data-rule="R2a"] .state-word')).to_have_text("met")
    expect(panel.locator('[data-rule="R2b"] .state-word')).to_have_text("met")
    expect(panel.locator("[data-r2-combined]")).to_be_visible()
    expect(page.locator('[data-screen="review"] [data-r1-detail]')).to_be_hidden()
