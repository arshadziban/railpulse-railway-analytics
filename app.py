"""RailPulse dashboard entry point.

Reads the cleaned layer from railpulse.duckdb (built by notebooks 01 and 03) and serves the pages in dashboard/views.
The sidebar filters here apply to every analysis page. The data is reloaded whenever the database file changes.

Run locally with: streamlit run app.py
"""
import duckdb
import streamlit as st

from dashboard import data
from dashboard.data import Filters, query

st.set_page_config(page_title="RailPulse", layout="wide")

try:
    con = data.connect()
except (FileNotFoundError, duckdb.Error) as error:
    st.error(f"Could not load the data: {error}")
    st.stop()

bounds = query(con, "SELECT MIN(service_date) AS first, MAX(service_date) AS last FROM events").iloc[0]
first_date, last_date = bounds["first"].date(), bounds["last"].date()
all_trains = query(con, "SELECT train_id, train_name FROM trains ORDER BY train_id")
train_names = dict(zip(all_trains["train_id"], all_trains["train_name"]))
all_regions = query(con, "SELECT DISTINCT region FROM stations WHERE is_served ORDER BY region")["region"].tolist()

pages = {
    "Performance": [
        st.Page("dashboard/views/overview.py", title="Overview", default=True),
        st.Page("dashboard/views/trains.py", title="Trains"),
        st.Page("dashboard/views/stations.py", title="Stations"),
        st.Page("dashboard/views/disruptions.py", title="Disruptions"),
    ],
    "Operations": [
        st.Page("dashboard/views/live_board.py", title="Live board"),
        st.Page("dashboard/views/run_explorer.py", title="Run explorer"),
    ],
    "Data": [
        st.Page("dashboard/views/data_quality.py", title="Data and quality"),
    ],
}
page = st.navigation(pages)

with st.sidebar:
    st.markdown("### RailPulse")
    st.caption("Train delay analytics on synthetic data")
    st.subheader("Filters")
    date_range = st.date_input("Service dates", value=(first_date, last_date),
                               min_value=first_date, max_value=last_date, key="dates")
    trains = st.multiselect("Trains", list(train_names), default=list(train_names), key="trains",
                            format_func=lambda t: f"{t}  {train_names[t]}")
    regions = st.multiselect("Station regions", all_regions, default=all_regions, key="regions")
    threshold = st.slider("On-time threshold (minutes late)", 0, 15, data.DEFAULT_THRESHOLD_MIN, key="threshold",
                          help="A stop counts as on time if its delay is at most this many minutes.")
    target = st.slider("On-time target (%)", 50, 100, data.DEFAULT_TARGET_PCT, key="target",
                       help="Trains and stations below this share of on-time arrivals are flagged.")
    include_disrupted = st.toggle("Include disrupted runs", value=True, key="include_disrupted",
                                  help="A run is disrupted if any of its stops has a simulated disruption.")
    st.divider()
    if st.button("Reload data", width="stretch"):
        data.reload()
        st.rerun()
    st.caption("Data reloads automatically when railpulse.duckdb changes. "
               "All records are simulated and are not actual Bangladesh Railway performance.")

# the date input returns a single date while the second one is being picked
if not isinstance(date_range, tuple) or len(date_range) != 2:
    st.info("Pick an end date to apply the date filter.")
    st.stop()
if not trains or not regions:
    st.warning("Select at least one train and one region.")
    st.stop()

st.session_state["filters"] = Filters(
    start=date_range[0], end=date_range[1], trains=tuple(trains), regions=tuple(regions),
    threshold=threshold, include_disrupted=include_disrupted, target_pct=target)
st.session_state["first_date"] = first_date
st.session_state["con"] = con

page.run()
