"""Loading the cleaned layer from railpulse.duckdb and applying the dashboard filters."""
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "railpulse.duckdb"

# cleaned tables from notebook 03, copied into memory under these names
TABLES = {
    "events": "train_run_events_clean",
    "trains": "train_master_clean",
    "stations": "station_master_clean",
}

DEFAULT_THRESHOLD_MIN = 5
DEFAULT_TARGET_PCT = 80


@dataclass(frozen=True)
class Filters:
    start: date
    end: date
    trains: tuple
    regions: tuple
    threshold: int = DEFAULT_THRESHOLD_MIN
    include_disrupted: bool = True
    target_pct: int = DEFAULT_TARGET_PCT

    def with_dates(self, start, end):
        return replace(self, start=start, end=end)


def db_version():
    """Modification time of the database, used as the cache key so a rebuilt database triggers a reload."""
    if not DB_PATH.is_file():
        raise FileNotFoundError(f"{DB_PATH.name} not found, run notebooks 01 and 03 first")
    return DB_PATH.stat().st_mtime


def load_database(path=DB_PATH):
    """Copy the cleaned tables into an in-memory database and release the file."""
    con = duckdb.connect(":memory:")
    # detach straight away so the notebooks can still write to the file while the app runs
    con.execute(f"ATTACH '{Path(path).as_posix()}' AS src (READ_ONLY)")
    existing = {row[0] for row in con.execute(
        "SELECT table_name FROM duckdb_tables() WHERE database_name = 'src'").fetchall()}
    missing = [t for t in TABLES.values() if t not in existing]
    if missing:
        raise FileNotFoundError(f"Missing tables {missing} in {Path(path).name}, run notebooks 01 and 03 first")
    for name, source in TABLES.items():
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM src.{source}")
    con.execute("DETACH src")
    return con


@st.cache_resource(show_spinner="Loading data...")
def _cached_database(version):
    return load_database()


def connect():
    """A connection for this script run. Each run gets its own cursor on the shared in-memory database."""
    return _cached_database(db_version()).cursor()


def reload():
    _cached_database.clear()


def query(con, sql, params=None):
    return con.execute(sql, params or {}).df()


# long format, one row per stop per measure, as in notebook 04 section 2, with the filters applied
DELAY_OBS_SQL = """
    WITH events AS (
        SELECT *, BOOL_OR(simulated_disruption_flag) OVER (PARTITION BY service_id) AS run_disrupted
        FROM events
    ),
    long AS (
        SELECT e.service_id, e.service_date, e.train_id, e.station_id, s.region, e.station_sequence,
            'arrival' AS measure, e.scheduled_arrival AS scheduled_time, e.arrival_delay_min AS delay_min,
            e.simulated_disruption_flag AS is_disrupted, e.run_disrupted, e.simulated_disruption_type AS disruption_type
        FROM events e JOIN stations s USING (station_id)
        WHERE e.arrival_delay_min IS NOT NULL
        UNION ALL
        SELECT e.service_id, e.service_date, e.train_id, e.station_id, s.region, e.station_sequence,
            'departure', e.scheduled_departure, e.departure_delay_min,
            e.simulated_disruption_flag, e.run_disrupted, e.simulated_disruption_type
        FROM events e JOIN stations s USING (station_id)
        WHERE e.departure_delay_min IS NOT NULL
    )
    SELECT *, delay_min <= $threshold AS is_on_time
    FROM long
    WHERE service_date BETWEEN $start AND $end
      AND list_contains($trains, train_id)
      AND list_contains($regions, region)
      AND ($include_disrupted OR NOT run_disrupted)
"""


def delay_observations(con, filters):
    return query(con, DELAY_OBS_SQL, dict(
        threshold=filters.threshold, start=filters.start, end=filters.end, trains=list(filters.trains),
        regions=list(filters.regions), include_disrupted=filters.include_disrupted))


def register_delay_obs(con, filters):
    """Filtered observations, registered as the delay_obs table the analysis queries read from."""
    obs = delay_observations(con, filters)
    # views can't take parameters, so the filtered rows are registered as a table instead
    con.register("delay_obs", obs)
    return obs


def previous_period(filters, first_date):
    """Filters for the period of equal length just before the selected one, or None if it falls outside the data."""
    length = filters.end - filters.start
    end = filters.start - timedelta(days=1)
    start = end - length
    if start < first_date:
        return None
    return filters.with_dates(start, end)


def get_filters():
    """The filters set in the sidebar by app.py."""
    return st.session_state["filters"]


def page_context():
    """Connection, filters and filtered observations for an analysis page. Stops the page if nothing matches."""
    con, filters = st.session_state["con"], get_filters()
    obs = register_delay_obs(con, filters)
    if obs.empty:
        st.warning("No stops match the sidebar filters.")
        st.stop()
    return con, filters, obs


SYNTHETIC_NOTE = ("Synthetic data: all records are simulated and the findings are illustrative only. "
                  "They are not actual Bangladesh Railway performance.")
