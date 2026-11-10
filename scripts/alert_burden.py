#!/usr/bin/env python3
"""Count rule checks, met checks and raised messages on Sanad's fixed fictional night.

Loads the fixed dataset, evaluates the ward exactly as the board does, and counts
from ``sanad.board.build_board_model``. Writes ``eval/results/alert-burden.json``,
the committed evidence behind the README headline. Standard library only; no
network. Python 3.12, from the repository root:

    python3 -I scripts/alert_burden.py --check   # compare with the committed file; write nothing
    python3 -I scripts/alert_burden.py           # rewrite eval/results/alert-burden.json

The numbers describe software behaviour on fictional data. They are not a clinical
result, an alert-fatigue measurement or a comparison with any real product.
Exit: 0 written or matching · 1 the committed file differs from a fresh run · 2 the
dataset could not be loaded.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "eval" / "results" / "alert-burden.json"

if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from sanad import board, evaluate, loader, r3  # noqa: E402
from sanad.model import Dataset, GridCell  # noqa: E402
from sanad.units import UnsupportedUnitError  # noqa: E402

SCOPE = (
    "Software behaviour on the fixed fictional seed-42 ward (data/ward_seed42): "
    "the 19:00-07:00 night on the 5-minute grid. Not a clinical result, not an "
    "alert-fatigue measurement and not a comparison with any real product."
)
DEFINITIONS = {
    "rule_check": (
        "one rule (R1, R2a, R2b or R3) evaluated at one grid point for an "
        "encounter that is on the board then (sanad.r3.is_active)"
    ),
    "met_check": "a rule check whose evaluation state is met",
    "message": (
        "one item in the on-call doctor's episode list or the night nurse's inbox "
        "(sanad.board.build_board_model): one per contiguous run of met grid points "
        "per encounter and group (R1; R2 = R2a or R2b; R3), plus one per "
        "contiguous feed-alert run. grid_points counts the whole run; "
        "on_board_points counts only its points where the encounter is on the board"
    ),
    "met_results_outside_stay": (
        "met results on grid points where the encounter is not on the board; they "
        "are not rule checks, and any listed here is a discrepancy explained in "
        "JUDGES.md"
    ),
}


def _summary(item: dict, on_board: list[bool]) -> dict:
    """One raised message: where, which group, when, and how many grid points it spans."""

    start, end = item["start_idx"], item["end_idx"]
    return {
        "bed": item["bed"],
        "encounter": item["encounter"],
        "group": item["rule"],
        "time_raised": item["time_raised"],
        "time_ended": item["time_ended"],
        "grid_points": end - start + 1,
        "on_board_points": sum(on_board[start:end + 1]),
    }


def build_report(ds: Dataset, results: dict[str, list[GridCell]]) -> dict:
    """Count checks, met checks and messages for an already evaluated ward."""

    model = board.build_board_model(ds, results)
    active_cells = 0
    checks = 0
    met_by_rule: Counter[str] = Counter()
    outside: dict[str, Counter[str]] = {}
    on_board: dict[str, list[bool]] = {}
    for enc in ds.encounters:
        ctx = r3.context_for(ds, enc.encounter)
        on_board[enc.encounter] = []
        for cell in results[enc.encounter]:
            active = r3.is_active(ctx, cell.t)
            on_board[enc.encounter].append(active)
            active_cells += int(active)
            for rule_id in board.RULE_IDS:
                res = cell.results.get(rule_id)
                if res is None:
                    continue
                met = res.state.value == "met"
                if active:
                    checks += 1
                    met_by_rule[rule_id] += int(met)
                elif met:
                    outside.setdefault(enc.encounter, Counter())[rule_id] += 1

    doctor = model["episodes"]
    nurse = model["inbox"]
    grid = model["grid_times"]
    return {
        "_scope": SCOPE,
        "generated_by": "scripts/alert_burden.py",
        "definitions": DEFINITIONS,
        "night_grid": {"first": grid[0], "last": grid[-1], "points": len(grid)},
        "beds": len({enc.bed for enc in ds.encounters}),
        "encounters": len(ds.encounters),
        "rules": list(board.RULE_IDS),
        "active_encounter_cells": active_cells,
        "rule_checks": checks,
        "met_checks_total": sum(met_by_rule.values()),
        "met_checks_by_rule": {r: met_by_rule[r] for r in board.RULE_IDS},
        "messages_total": len(doctor) + len(nurse),
        "doctor_episodes": len(doctor),
        "nurse_inbox_items": len(nurse),
        "messages_by_group": dict(sorted(Counter(i["rule"] for i in doctor + nurse).items())),
        "met_results_outside_stay": sum(sum(c.values()) for c in outside.values()),
        "met_results_outside_stay_by_encounter": {
            e: dict(sorted(c.items())) for e, c in sorted(outside.items())
        },
        "doctor_episode_list": [_summary(i, on_board[i["encounter"]]) for i in doctor],
        "nurse_inbox_list": [_summary(i, on_board[i["encounter"]]) for i in nurse],
    }


def render(report: dict) -> str:
    """The exact text of the committed JSON file."""

    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"


def headline(report: dict) -> str:
    """The one-line summary printed after a run."""

    return (
        f"rules met {report['met_checks_total']:,} times in {report['rule_checks']:,} rule checks; "
        f"{report['messages_total']} messages ({report['doctor_episodes']} doctor, "
        f"{report['nurse_inbox_items']} nurse)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="compare a fresh run with the committed file; write nothing")
    args = parser.parse_args(argv)

    try:
        ds = loader.load_dataset()
    except (loader.LoaderError, UnsupportedUnitError, OSError, json.JSONDecodeError) as exc:
        print(f"cannot load the fixed dataset: {exc}", file=sys.stderr)
        return 2
    report = build_report(ds, evaluate.evaluate_ward(ds))
    text = render(report)
    rel = OUT.relative_to(REPO)
    if args.check:
        committed = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if committed != text:
            print(f"MISMATCH: {rel} differs from a fresh run; rerun without --check "
                  "and commit the new file", file=sys.stderr)
            print(headline(report), file=sys.stderr)
            return 1
        print(f"OK: {rel} matches a fresh run")
    else:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(text, encoding="utf-8")
        print(f"wrote {rel}")
    print(headline(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
