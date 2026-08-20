"""Dashboard: chart rendering, page assembly, and the approval flow over HTTP."""

import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from http.server import ThreadingHTTPServer

import numpy as np
import pandas as pd
import pytest

from quantdesk.config import Settings
from quantdesk.data import get_provider
from quantdesk.engine import TradingEngine
from quantdesk.news.fetch import NewsFetcher
from quantdesk.web import views
from quantdesk.web.charts import candlestick, equity_curve
from quantdesk.web.server import DeskHandler

UNIVERSE = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "XLK", "GLD"]


def bars(n=200, seed=1):
    rng = np.random.default_rng(seed)
    close = np.maximum(100 + np.cumsum(rng.normal(0, 1.2, n)), 1.0)
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {"open": open_, "high": np.maximum(open_, close) + 1,
         "low": np.minimum(open_, close) - 1, "close": close,
         "volume": np.full(n, 1e6)},
        index=pd.bdate_range(end="2026-01-01", periods=n),
    )


# --- charts -------------------------------------------------------------------
def test_candlestick_draws_one_body_per_session():
    svg = candlestick(bars(), sessions=40)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert svg.count("<rect") == 40


def test_chart_coordinates_are_always_finite():
    """A NaN in an SVG attribute silently drops the shape - it must never happen."""
    from quantdesk.analysis.indicators import compute_all

    frame = bars(60)
    # sma200 over 60 bars is entirely NaN: the worst case for an overlay.
    svg = candlestick(frame, overlays={"SMA200": compute_all(frame)["sma200"]})
    assert not re.search(r'="(-?[\d.]*(?:nan|inf)[^"]*)"', svg, re.I)
    assert "nan" not in svg.lower()


def test_overlays_widen_the_range_so_they_stay_visible():
    frame = bars()
    high_line = pd.Series(frame["high"].max() * 1.5, index=frame.index)
    assert "<polyline" in candlestick(frame, overlays={"HIGH": high_line})


def test_markers_and_levels_render():
    frame = bars()
    svg = candlestick(
        frame,
        markers=[{"date": frame.index[-5], "label": "Hammer", "direction": "bullish"}],
        levels=[{"price": float(frame["close"].iloc[-1]), "label": "stop",
                 "kind": "stop"}],
    )
    assert "<polygon" in svg and "Hammer" in svg and "stop" in svg


def test_empty_inputs_still_produce_valid_svg():
    assert candlestick(None).startswith("<svg")
    assert candlestick(pd.DataFrame()).startswith("<svg")
    assert "Not enough history" in equity_curve([("a", 1.0)])


def test_equity_curve_colours_by_outcome():
    assert "--up" in equity_curve([("a", 100.0), ("b", 120.0)])
    assert "--down" in equity_curve([("a", 120.0), ("b", 100.0)])


def test_chart_markup_is_escaped():
    frame = bars()
    svg = candlestick(frame, markers=[
        {"date": frame.index[-1], "label": "<script>x</script>", "direction": "bullish"}
    ])
    assert "<script>" not in svg


# --- engine fixture -----------------------------------------------------------
@pytest.fixture
def engine(tmp_path):
    settings = Settings(home=tmp_path, risk_profile="moderate",
                        starting_cash=100_000.0)
    settings.execution_mode = "manual"
    eng = TradingEngine(settings, provider=get_provider("synthetic"),
                        news_fetcher=NewsFetcher(offline=True))
    original = eng.recommender.scan
    eng.recommender.scan = (
        lambda equity, symbols=None, limit=10, exclude=None:
        original(equity, UNIVERSE, limit, exclude)
    )
    eng.run_daily(as_of=date.today(), max_new_ideas=3, write_files=False)
    return eng


# --- views --------------------------------------------------------------------
@pytest.mark.parametrize("view", ["dashboard", "ideas", "positions", "history"])
def test_pages_render_complete_documents(engine, view):
    html = getattr(views, view)(engine)
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html
    assert "Not financial advice" in html


def test_pages_have_no_external_resources(engine):
    """The dashboard must work with the machine offline."""
    stripped = views.dashboard(engine).replace("http://www.w3.org", "")
    assert "//cdn" not in stripped.lower()
    assert "<script" not in stripped.lower()


def test_synthetic_data_is_flagged_in_the_ui(engine):
    assert "SIMULATED" in views.dashboard(engine)


def test_ideas_page_offers_a_decision_per_proposal(engine):
    pending = engine.store.proposals("pending")
    html = views.ideas(engine)
    assert html.count('class="approve"') == len(pending)
    assert html.count('class="reject"') == len(pending)


def test_symbol_page_includes_a_chart(engine):
    html = views.symbol_detail(engine, "NVDA")
    assert "<svg" in html and "<rect" in html


def test_unknown_symbol_does_not_crash_the_page(engine):
    assert "<!DOCTYPE html>" in views.symbol_detail(engine, "NOSUCHTICKER")


def test_state_json_is_serialisable(engine):
    payload = views.state_json(engine)
    json.dumps(payload)
    assert payload["mode"] == "manual"
    assert payload["simulated_data"] is True
    assert len(payload["pending_proposals"]) == len(engine.store.proposals("pending"))


# --- live server --------------------------------------------------------------
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


@pytest.fixture
def live(engine):
    DeskHandler.engine = engine
    DeskHandler.settings = engine.settings
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), DeskHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", engine
    httpd.shutdown()
    httpd.server_close()


def get(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.status, response.read().decode()


def post(url, data):
    request = urllib.request.Request(
        url, data=urllib.parse.urlencode(data).encode(), method="POST"
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as r:
            return r.status
    except urllib.error.HTTPError as exc:
        return exc.code


@pytest.mark.parametrize("route", ["/", "/ideas", "/positions", "/history",
                                   "/symbol?s=NVDA", "/api/state"])
def test_routes_return_200(live, route):
    base, _ = live
    assert get(base + route)[0] == 200


def test_unknown_route_is_404(live):
    base, _ = live
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        get(base + "/nowhere")
    assert excinfo.value.code == 404


def test_approving_over_http_creates_exactly_one_order(live):
    base, engine = live
    proposal = engine.store.proposals("pending")[0]

    assert post(f"{base}/approve", {"id": proposal.id}) == 303
    orders = [o for o in engine.store.pending_orders() if o.symbol == proposal.symbol]
    assert len(orders) == 1

    # A second click, or a double-submit, must not place another order.
    assert post(f"{base}/approve", {"id": proposal.id}) == 303
    orders = [o for o in engine.store.pending_orders() if o.symbol == proposal.symbol]
    assert len(orders) == 1, "approval must be idempotent"


def test_rejecting_removes_it_from_the_queue(live):
    base, engine = live
    proposal = engine.store.proposals("pending")[0]
    assert post(f"{base}/reject", {"id": proposal.id}) == 303
    assert proposal.id not in [p.id for p in engine.store.proposals("pending")]
    assert proposal.symbol in [p.symbol for p in engine.store.proposals("rejected")]


def test_malformed_id_is_handled(live):
    base, _ = live
    assert post(f"{base}/approve", {"id": "not-a-number"}) == 303


def test_security_headers_are_set(live):
    base, _ = live
    with urllib.request.urlopen(base + "/", timeout=30) as response:
        assert "default-src 'none'" in response.headers["Content-Security-Policy"]
        assert response.headers["X-Content-Type-Options"] == "nosniff"
