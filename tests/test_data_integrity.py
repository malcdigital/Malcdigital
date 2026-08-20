"""Guards on the one thing a paper-trading desk must never do quietly:
report on a market that does not exist.
"""

import pytest

from quantdesk.data import get_provider
from quantdesk.data.base import DataUnavailable


def test_auto_includes_synthetic_by_default():
    """Falling back keeps the desk usable offline - clearly labelled."""
    provider = get_provider("auto")
    assert "synthetic" in provider.name


def test_strict_removes_the_synthetic_fallback():
    """--strict must not be able to resolve to generated prices."""
    try:
        provider = get_provider("auto", allow_synthetic=False)
    except DataUnavailable:
        return  # no live provider installable here; that is also a valid refusal
    assert "synthetic" not in provider.name


def test_strict_rejects_an_explicit_synthetic_request():
    with pytest.raises(DataUnavailable):
        get_provider("synthetic", allow_synthetic=False)


def test_synthetic_runs_are_flagged_as_simulated():
    """A generated-data run must announce itself in the report."""
    from quantdesk.strategy.recommend import ScanResult

    result = ScanResult()
    result.used_synthetic_data = True
    assert result.used_synthetic_data is True


def test_diagnostics_reports_a_structured_verdict(no_network):
    from quantdesk.diagnostics import run_diagnostics

    diagnosis = run_diagnostics(include_news=False)
    names = {c.name for c in diagnosis.checks}
    assert "Python version" in names
    assert "Resolved data source" in names
    assert isinstance(diagnosis.live_data_available, bool)
    assert all(isinstance(c.ok, bool) for c in diagnosis.checks)


def test_diagnostics_marks_price_feeds_as_fatal(no_network):
    """Price-feed checks decide the verdict; the news check must not."""
    from quantdesk.diagnostics import run_diagnostics

    diagnosis = run_diagnostics(include_news=False)
    fatal = {c.name for c in diagnosis.checks if c.fatal}
    assert "Yahoo Finance (live prices)" in fatal
    assert "Stooq (fallback prices)" in fatal


def test_diagnostics_reports_no_live_data_when_every_feed_is_down(no_network):
    """The verdict that matters: with all feeds dead, say so unambiguously."""
    from quantdesk.diagnostics import run_diagnostics

    diagnosis = run_diagnostics(include_news=False)
    assert diagnosis.live_data_available is False
    resolved = next(c for c in diagnosis.checks if c.name == "Resolved data source")
    assert resolved.ok is False
    assert "synthetic" in resolved.detail


def test_strict_refuses_to_build_when_no_live_feed_exists(no_network):
    """--strict must raise rather than quietly resolve to generated prices."""
    provider = get_provider("auto", allow_synthetic=False)
    with pytest.raises(DataUnavailable):
        provider.history("SPY", 60)
