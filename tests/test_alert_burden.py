"""The committed alert-burden count is a fresh run, and the README and JUDGES.md state it.

``eval/results/alert-burden.json`` is the evidence behind the README headline. These
tests re-run the script's count on the session's ward evaluation and assert the
committed file is exactly what ``scripts/alert_burden.py`` writes now, with the
numbers the README and JUDGES.md state. If the engine or the data change, rerun
``python3 -I scripts/alert_burden.py`` and update the wording in the same PR.
Software behaviour on fictional data only; no clinical or alert-fatigue claim.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
COMMITTED = ROOT / "eval" / "results" / "alert-burden.json"

_spec = importlib.util.spec_from_file_location("alert_burden", ROOT / "scripts" / "alert_burden.py")
ab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ab)


@pytest.fixture(scope="module")
def report(dataset, ward_eval) -> dict:
    return ab.build_report(dataset, ward_eval)


def test_committed_file_is_a_fresh_run(report: dict) -> None:
    assert COMMITTED.read_text(encoding="utf-8") == ab.render(report), (
        "eval/results/alert-burden.json is stale: rerun python3 -I scripts/alert_burden.py"
    )


def test_headline_numbers(report: dict) -> None:
    assert report["rule_checks"] == 9848
    assert report["met_checks_total"] == 657
    assert report["messages_total"] == 11
    assert report["doctor_episodes"] == 9
    assert report["nurse_inbox_items"] == 2


def test_every_on_board_cell_checks_every_rule(report: dict) -> None:
    # 9,848 = 2,462 on-board encounter grid points x 4 rules.
    assert report["rule_checks"] == report["active_encounter_cells"] * len(report["rules"])


def test_one_message_per_board_item(report: dict, board_model: dict) -> None:
    """Every message is one item of the board model the HTML embeds, and vice versa."""

    def keys(items: list[dict], group: str) -> list[tuple]:
        return [(i["encounter"], i[group], i["time_raised"]) for i in items]

    assert keys(report["doctor_episode_list"], "group") == keys(board_model["episodes"], "rule")
    assert keys(report["nurse_inbox_list"], "group") == keys(board_model["inbox"], "rule")


@pytest.mark.parametrize("doc", ["README.md", "JUDGES.md"])
def test_docs_state_the_committed_numbers(report: dict, doc: str) -> None:
    text = (ROOT / doc).read_text(encoding="utf-8")
    for phrase in (
        f"met {report['met_checks_total']} times",
        f"{report['messages_total']} messages",
        f"{report['rule_checks']:,} rule checks",
    ):
        assert phrase in text, (doc, phrase)
