"""Run explorer: one run stop by stop, with a time-distance chart of schedule against actual."""
import plotly.graph_objects as go
import streamlit as st

from dashboard import charts, data

con, filters = st.session_state["con"], data.get_filters()

st.title("Run explorer")
st.caption("Follow a single run stop by stop. " + data.SYNTHETIC_NOTE)

runs = data.query(con, """
    SELECT e.service_id, e.service_date, e.train_id, ANY_VALUE(t.train_name) AS train_name,
        arg_max(e.arrival_delay_min, e.station_sequence) AS final_delay, BOOL_OR(e.simulated_disruption_flag) AS disrupted
    FROM events e JOIN trains t USING (train_id)
    WHERE e.service_date BETWEEN $start AND $end AND list_contains($trains, e.train_id)
    GROUP BY ALL
    ORDER BY e.service_date, e.service_id
""", dict(start=filters.start, end=filters.end, trains=list(filters.trains)))
if runs.empty:
    st.warning("No runs match the sidebar filters.")
    st.stop()

left, right = st.columns([1, 2])
day = left.selectbox("Service day", sorted(runs["service_date"].dt.date.unique()), index=None,
                     format_func=lambda d: f"{d:%a %d %b %Y}", placeholder="All days")
choices = runs if day is None else runs[runs["service_date"].dt.date == day]
labels = {r.service_id: f"{r.service_id}  {r.train_id} {r.train_name}, {r.service_date:%d %b}, "
                        f"{r.final_delay:+.0f} min at terminus{', disrupted' if r.disrupted else ''}"
          for r in choices.itertuples()}
service_id = right.selectbox("Run", list(labels), format_func=labels.get)

stops = data.query(con, """
    SELECT e.*, s.station_name
    FROM events e JOIN stations s USING (station_id)
    WHERE service_id = $id ORDER BY station_sequence
""", dict(id=service_id))
run = runs.set_index("service_id").loc[service_id]

cols = st.columns(4)
cols[0].metric("Delay at terminus", f"{run['final_delay']:+.0f} min")
cols[1].metric("Largest delay", f"{stops[['arrival_delay_min', 'departure_delay_min']].max().max():.0f} min")
cols[2].metric("Stops", len(stops))
cols[3].metric("Disruption", ", ".join(sorted(set(stops.loc[stops["simulated_disruption_flag"], "simulated_disruption_type"])))
               or "None")

# time-distance chart: stations on the vertical axis in route order, time across
fig = go.Figure()
for kind, arrive, depart, colour, dash in [("Scheduled", "scheduled_arrival", "scheduled_departure", charts.MUTED, "dash"),
                                           ("Actual", "actual_arrival", "actual_departure", charts.ARRIVAL, "solid")]:
    xs, ys = [], []
    for _, stop in stops.iterrows():
        for column in (arrive, depart):
            if stop[column] == stop[column]:  # skip NaT at the route ends
                xs.append(stop[column])
                ys.append(stop["station_name"])
    fig.add_trace(go.Scatter(x=xs, y=ys, name=kind, mode="lines+markers", line=dict(color=colour, width=2.5, dash=dash),
                             hovertemplate="%{y}<br>%{x|%H:%M}<extra>" + kind + "</extra>"))
flagged = stops[stops["simulated_disruption_flag"]]
if not flagged.empty:
    fig.add_trace(go.Scatter(x=flagged["actual_arrival"].fillna(flagged["actual_departure"]), y=flagged["station_name"],
                             name="Disrupted stop", mode="markers",
                             marker=dict(color=charts.BAD, size=14, symbol="x"),
                             customdata=flagged[["simulated_disruption_type"]],
                             hovertemplate="%{y}<br>%{customdata[0]}<extra>Disrupted</extra>"))
fig.update_yaxes(categoryorder="array", categoryarray=stops["station_name"].tolist(), autorange="reversed")
fig.update_xaxes(tickformat="%H:%M")
charts.show(fig, f"{run['train_id']} {run['train_name']} on {run['service_date']:%a %d %b %Y}",
            "Time-distance chart: the gap between the lines is the delay.", height=440)

fig = go.Figure()
for measure, colour in [("arrival", charts.ARRIVAL), ("departure", charts.DEPARTURE)]:
    fig.add_trace(go.Bar(x=stops["station_name"], y=stops[f"{measure}_delay_min"], name=measure.capitalize(),
                         marker_color=colour, hovertemplate="%{x}: %{y} min"))
charts.reference_line(fig, filters.threshold, "On-time threshold", axis="y")
fig.update_layout(barmode="group")
fig.update_yaxes(title_text="Delay (minutes)")
charts.show(fig, "Delay at each stop", height=360)

st.dataframe(
    stops[["station_sequence", "station_name", "scheduled_arrival", "actual_arrival", "arrival_delay_min",
           "scheduled_departure", "actual_departure", "departure_delay_min", "scheduled_dwell_min", "actual_dwell_min",
           "simulated_disruption_type"]],
    hide_index=True, width="stretch",
    column_config={
        "station_sequence": "Stop", "station_name": "Station",
        "scheduled_arrival": st.column_config.DatetimeColumn("Sched. arrival", format="HH:mm"),
        "actual_arrival": st.column_config.DatetimeColumn("Actual arrival", format="HH:mm"),
        "arrival_delay_min": "Arrival delay (min)",
        "scheduled_departure": st.column_config.DatetimeColumn("Sched. departure", format="HH:mm"),
        "actual_departure": st.column_config.DatetimeColumn("Actual departure", format="HH:mm"),
        "departure_delay_min": "Departure delay (min)",
        "scheduled_dwell_min": "Sched. dwell (min)", "actual_dwell_min": "Actual dwell (min)",
        "simulated_disruption_type": "Disruption",
    },
)
