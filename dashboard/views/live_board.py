"""Live operations board: replays a recorded day so the network can be watched as if it were running now."""
from datetime import datetime, time, timedelta

import plotly.graph_objects as go
import streamlit as st

from dashboard import charts, data, live

con, filters = st.session_state["con"], data.get_filters()

st.title("Live board")
st.caption("Replays the recorded runs of a day as if they were happening now: where each train is, its current "
           "delay and when it is expected at the next stop. " + data.SYNTHETIC_NOTE)

controls = st.columns([2, 1, 1])
day = controls[0].date_input("Service day", value=filters.end, min_value=filters.start, max_value=filters.end,
                             key="live_day")
playing = controls[1].toggle("Play", key="live_playing", help="Advance the clock automatically")
step = controls[2].selectbox("Speed", [5, 15, 30, 60], index=1, key="live_step",
                             format_func=lambda m: f"{m} min per second")

st.session_state.setdefault("live_time", time(8, 0))
stops = live.stops_for_day(con, day, filters.trains)


@st.fragment(run_every="1s" if playing else None)
def board():
    if playing:
        # advance before the slider is drawn so the slider shows the new time
        moved = datetime.combine(day, st.session_state["live_time"]) + timedelta(minutes=step)
        st.session_state["live_time"] = min(moved.time(), time(23, 55)) if moved.date() == day else time(23, 55)
    clock = st.slider("Time of day", min_value=time(0, 0), max_value=time(23, 55), step=timedelta(minutes=5),
                      key="live_time", format="HH:mm")
    now = datetime.combine(day, clock)

    if stops.empty:
        st.info("No runs on this day for the selected trains.")
        return
    state = live.board_at(stops, now, filters.threshold)
    counts = state["status"].value_counts()
    arrived_today = stops[(stops["actual_arrival"] <= now) & (stops["actual_arrival"] >= datetime.combine(day, time()))]

    cols = st.columns(6)
    cols[0].metric("Clock", f"{now:%H:%M}", f"{now:%a %d %b}", delta_color="off")
    cols[1].metric("Running", int(counts.reindex(["On time", "Late", "Disrupted"]).fillna(0).sum()))
    cols[2].metric("Late", int(counts.get("Late", 0)), help=f"More than {filters.threshold} min behind")
    cols[3].metric("Disrupted", int(counts.get("Disrupted", 0)))
    cols[4].metric("Completed", int(counts.get("Arrived", 0)))
    if len(arrived_today):
        on_time = 100 * (arrived_today["arrival_delay_min"] <= filters.threshold).mean()
        cols[5].metric("Arrivals on time today", f"{on_time:.1f}%", help=f"{len(arrived_today)} arrivals so far")
    else:
        cols[5].metric("Arrivals on time today", "None yet")

    running = state[state["status"].isin(["On time", "Late", "Disrupted"])].sort_values("delay_min")
    if not running.empty:
        fig = go.Figure(go.Bar(
            y=running["train_id"] + "  " + running["train_name"], x=running["delay_min"], orientation="h",
            marker_color=[charts.STATUS_COLOURS[s] for s in running["status"]],
            text=running["delay_min"].map("{:.0f} min".format), textposition="outside", cliponaxis=False,
            customdata=running[["location", "status"]],
            hovertemplate="%{y}<br>%{customdata[1]}, %{x} min<br>%{customdata[0]}<extra></extra>",
        ))
        charts.reference_line(fig, filters.threshold, "On-time threshold")
        fig.update_xaxes(title_text="Current delay (minutes)")
        charts.show(fig, "Trains under way", "Green on time, orange late, red disrupted.",
                    height=max(260, 44 * len(running) + 120))

    styled = state[["train_id", "train_name", "route", "status", "location", "delay_min", "next_stop", "expected",
                    "progress", "scheduled_departure", "scheduled_arrival"]].style.map(
        lambda s: f"color: {charts.STATUS_COLOURS.get(s, 'inherit')}; font-weight: 600", subset=["status"])
    st.dataframe(styled, hide_index=True, width="stretch", column_config={
        "train_id": "Train", "train_name": "Name", "route": "Route", "status": "Status", "location": "Position",
        "delay_min": st.column_config.NumberColumn("Delay (min)", format="%d"),
        "next_stop": "Next stop",
        "expected": st.column_config.DatetimeColumn("Expected", format="HH:mm"),
        "progress": st.column_config.ProgressColumn("Progress", min_value=0, max_value=1, format="percent"),
        "scheduled_departure": st.column_config.DatetimeColumn("Departs", format="ddd HH:mm"),
        "scheduled_arrival": st.column_config.DatetimeColumn("Arrives", format="ddd HH:mm"),
    })


board()
