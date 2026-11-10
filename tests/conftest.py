"""Shared test setup for the Sanad engine tests.

* Put ``src/`` on ``sys.path`` so tests can ``import sanad`` without an install
  step (the repo uses a ``src/`` layout and no packaging config).
* Register and load a deterministic hypothesis profile so property-based tests
  are reproducible in CI (``.kiro/steering/tech.md``: "Hypothesis must be
  deterministic in CI; pin a seed/profile").
"""

from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from hypothesis import HealthCheck, settings  # noqa: E402

settings.register_profile(
    "sanad",
    deadline=None,
    derandomize=True,  # deterministic example generation
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("sanad")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def dataset():
    """The fixed dataset, loaded once per test session (read-only: records are frozen)."""

    from sanad.loader import load_dataset

    return load_dataset()


@pytest.fixture(scope="session")
def ward_eval(dataset) -> dict:
    """One whole-night ward evaluation per test session (~40 s), shared by the
    oracle, board-model and board tests. Determinism tests still re-run the
    engine on purpose and compare against this."""

    from sanad.evaluate import evaluate_ward

    return evaluate_ward(dataset)


@pytest.fixture(scope="session")
def board_model(dataset, ward_eval: dict) -> dict:
    """The ward board model built once per test session from the fixed dataset.

    The night is evaluated once per session (tasks.md): the real dataset is
    loaded read-only and :func:`sanad.board.build_board_model` serialises its
    ward evaluation. Shared so the offline / wording / viewer / state tests do
    not each re-run the whole engine.
    """

    from sanad.board import build_board_model

    return build_board_model(dataset, ward_eval)


@pytest.fixture(scope="session")
def board_html(board_model: dict) -> str:
    """The rendered offline HTML string for the shared board model, built once
    per test session."""

    from sanad.board import render_html

    return render_html(board_model)
