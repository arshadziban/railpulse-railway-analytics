"""Tests for the dashboard: numbers agree with the notebooks, the live board logic, and every page renders.

Run with: python -m pytest tests
"""
from datetime import date, datetime

import pytest
from streamlit.testing.v1 import AppTest

from dashboard import data, live, queries

pytestmark = pytest.mark.skipif(not data.DB_PATH.is_file(), reason="railpulse.duckdb not built, run notebooks 01 and 03")

APP = str(data.PROJECT_ROOT / "app.py")
PAGES = ["overview", "trains", "stations", "disruptions", "live_board", "run_explorer", "data_quality"]


@pytest.fixture(scope="module")
def con():
    return data.load_database()


@pytest.fixture(scope="module")
def all_filters(con):
    first, last = con.execute("SELECT MIN(service_date), MAX(service_date) FROM events").fetchone()
    trains = tuple(r[0] for r in con.execute("SELECT train_id FROM trains").fetchall())
    regions = tuple(r[0] for r in con.execute("SELECT DISTINCT region FROM stations").fetchall())
    return data.Filters(start=first, end=last, trains=trains, regions=regions)


def test_headline_matches_notebooks(con, all_filters):
    obs = data.delay_observations(con, all_filters)
    kpi = queries.headline(obs, all_filters.threshold)
    # notebook 04 section 3 and notebook 05
    assert kpi["runs"] == 426
    assert kpi["disrupted_runs"] == 28
    assert kpi["arrival_on_time_pct"] == pytest.approx(79.7, abs=0.05)

    undisrupted = data.delay_observations(con, data.Filters(**{**all_filters.__dict__, "include_disrupted": False}))
    assert queries.headline(undisrupted, all_filters.threshold)["avg_arrival_delay"] == pytest.approx(1.95, abs=0.005)


def test_filters_narrow_the_data(con, all_filters):
    one_train = data.Filters(**{**all_filters.__dict__, "trains": ("TR001",)})
    obs = data.delay_observations(con, one_train)
    assert set(obs["train_id"]) == {"TR001"}
    assert obs["service_id"].nunique() == 39  # TR001 has a weekly day off


def test_previous_period(all_filters):
    week = all_filters.with_dates(date(2026, 8, 15), date(2026, 8, 21))
    earlier = data.previous_period(week, date(2026, 8, 1))
    assert (earlier.start, earlier.end) == (date(2026, 8, 8), date(2026, 8, 14))
    assert data.previous_period(all_filters, date(2026, 8, 1)) is None


def test_integrity_checks_pass(con):
    checks = queries.integrity_checks(con)
    assert (checks["violations"] == 0).all(), checks[checks["violations"] > 0]


def test_live_board_follows_a_run(con, all_filters):
    stops = live.stops_for_day(con, date(2026, 8, 1), all_filters.trains)
    run = stops[stops["service_id"] == "RUN000001"]
    start, end = run["actual_departure"].min(), run["actual_arrival"].max()

    before = live.board_at(run, start - (end - start), 5).iloc[0]
    during = live.board_at(run, start + (end - start) / 2, 5).iloc[0]
    after = live.board_at(run, end, 5).iloc[0]
    assert before["status"] == "Not departed" and before["progress"] == 0
    assert during["status"] in {"On time", "Late", "Disrupted"} and 0 < during["progress"] < 1
    assert after["status"] == "Arrived" and after["progress"] == 1


def test_live_board_includes_overnight_runs(con, all_filters):
    # a run that starts late on the previous day and is still going after midnight belongs on the board
    stops = live.stops_for_day(con, date(2026, 8, 2), all_filters.trains)
    assert (stops.groupby("service_id")["service_date"].first() < datetime(2026, 8, 2)).any()


@pytest.mark.parametrize("page", PAGES)
def test_page_renders(page):
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.switch_page(f"dashboard/views/{page}.py").run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.title, "page did not reach its title"


def test_pages_render_with_narrow_filters():
    at = AppTest.from_file(APP, default_timeout=120).run()
    at.multiselect(key="trains").set_value(["TR003"])
    at.toggle(key="include_disrupted").set_value(False)
    at.slider(key="threshold").set_value(0)
    at.run()
    for page in PAGES:
        at.switch_page(f"dashboard/views/{page}.py").run()
        assert not at.exception, (page, [e.value for e in at.exception])
