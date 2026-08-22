"""Changing the rules for one run, and saying so.

Two things matter here. A switch flipped for an experiment must not leak into
the settings the live desk trades on. And a run made under altered rules has to
announce it, because the whole point of a backtest number is comparing it with
another one - and two runs under different rules are not comparable.
"""

from datetime import date

import pytest

from quantdesk.backtest import BacktestConfig
from quantdesk.config import Settings


def test_an_override_changes_the_resolved_profile():
    base = Settings(risk_profile="moderate")
    assert base.profile.allow_short is True

    experiment = Settings(risk_profile="moderate",
                          profile_overrides={"allow_short": False})
    assert experiment.profile.allow_short is False
    # Everything else is untouched: this is one changed knob, not a different
    # profile wearing the same name.
    assert experiment.profile.max_positions == base.profile.max_positions
    assert experiment.profile.atr_stop_mult == base.profile.atr_stop_mult


def test_a_misspelled_override_fails_loudly():
    """Silently ignoring it would produce a run that reports a change it did
    not make - the worst of both outcomes."""
    settings = Settings(risk_profile="moderate",
                        profile_overrides={"allow_shorts": False})
    with pytest.raises(ValueError, match="allow_shorts"):
        _ = settings.profile


def test_an_override_is_never_written_to_the_saved_config(tmp_path):
    """A switch flipped for one backtest must not become the live setting."""
    settings = Settings(home=tmp_path, risk_profile="moderate",
                        profile_overrides={"allow_short": False})
    settings.save()

    assert "profile_overrides" not in settings.to_dict()
    reloaded = Settings.load(tmp_path)
    assert reloaded.profile_overrides == {}
    assert reloaded.profile.allow_short is True


def test_no_override_leaves_the_profile_object_alone():
    from quantdesk.config import get_profile

    assert Settings(risk_profile="moderate").profile is get_profile("moderate")


# --- the report has to say so -------------------------------------------------
def _result(overrides):
    from quantdesk.backtest import BacktestMetrics, BacktestResult

    return BacktestResult(
        config=BacktestConfig(symbols=["SPY"], start=date(2024, 1, 1),
                              end=date(2024, 3, 1), profile_overrides=overrides),
        sessions=40,
        metrics=BacktestMetrics(total_return_pct=5.0, cagr_pct=5.0,
                                max_drawdown_pct=-2.0, sharpe=0.4, sortino=0.5,
                                volatility_pct=9.0),
        equity_curve=[(date(2024, 1, 1), 100000.0), (date(2024, 3, 1), 105000.0)],
    )


def test_the_text_report_names_what_was_changed():
    from quantdesk.backtest_report import to_text

    text = to_text(_result({"allow_short": False}))
    assert "RULES CHANGED" in text and "allow_short=False" in text


def test_the_html_report_names_what_was_changed():
    from quantdesk.backtest_report import to_html

    html = to_html(_result({"allow_short": False}))
    assert "Rules changed for this run" in html
    assert "allow_short=False" in html
    assert "Not comparable" in html


def test_an_unmodified_run_says_nothing():
    from quantdesk.backtest_report import to_html, to_text

    assert "RULES CHANGED" not in to_text(_result({}))
    assert "Rules changed for this run" not in to_html(_result({}))


def test_the_backtester_applies_the_override_it_was_given():
    from quantdesk.backtest import Backtester
    from quantdesk.data import get_provider

    config = BacktestConfig(symbols=["SPY"], start=date(2024, 1, 1),
                            end=date(2024, 3, 1),
                            profile_overrides={"allow_short": False})
    engine = Backtester(get_provider("synthetic"), config)
    assert engine.settings.profile.allow_short is False
