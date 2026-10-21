"""Disruption impact: how much of the delay they cause, what the network would look like without them, and how they grow."""
from dataclasses import replace

import plotly.graph_objects as go
import streamlit as st

from dashboard import charts, data, queries

con, filters, _ = data.page_context()

st.title("Disruptions")
st.caption(data.SYNTHETIC_NOTE)

# this page always compares with and without disruptions, so it ignores the sidebar toggle
all_obs = data.register_delay_obs(con, replace(filters, include_disrupted=True))
if not filters.include_disrupted:
    st.info("This page includes disrupted runs even though the sidebar excludes them, since it compares the two.")

arrivals = all_obs[all_obs["measure"] == "arrival"]
disrupted = arrivals[arrivals["run_disrupted"]]
if disrupted.empty:
    st.success("No disrupted runs in the selected period and trains.")
    st.stop()

with_all = queries.headline(all_obs, filters.threshold)
without = queries.headline(all_obs[~all_obs["run_disrupted"]], filters.threshold)
lateness = arrivals["delay_min"].clip(lower=0)
late = arrivals["delay_min"] > filters.threshold
excess = disrupted["delay_min"].sum() - len(disrupted) * without["avg_arrival_delay"]

cols = st.columns(4)
cols[0].metric("Disrupted runs", f"{with_all['disrupted_runs']} of {with_all['runs']}",
               f"{100 * with_all['disrupted_runs'] / with_all['runs']:.1f}% of runs", delta_color="off")
cols[1].metric("Share of late minutes", f"{100 * lateness[arrivals['run_disrupted']].sum() / max(lateness.sum(), 1):.1f}%",
               f"from {100 * len(disrupted) / len(arrivals):.1f}% of arrivals", delta_color="off")
cols[2].metric("Share of late arrivals", f"{100 * (late & arrivals['run_disrupted']).sum() / max(late.sum(), 1):.1f}%")
cols[3].metric("Excess delay", f"{excess:,.0f} min",
               help="Delay on disrupted runs above what the same arrivals would have had at the undisrupted average")

st.subheader("What if no run had been disrupted")
left, right = st.columns(2)
left.metric("Arrivals on time without disruptions", f"{without['arrival_on_time_pct']:.1f}%",
            f"{without['arrival_on_time_pct'] - with_all['arrival_on_time_pct']:+.1f} pts", delta_color="normal")
right.metric("Average arrival delay without disruptions", f"{without['avg_arrival_delay']:.2f} min",
             f"{without['avg_arrival_delay'] - with_all['avg_arrival_delay']:+.2f} min", delta_color="inverse")
st.caption("Every stop of a disrupted run is left out, not only the flagged stops, since delay carries along the run.")

left, right = st.columns(2)
with left:
    by_type = queries.by_disruption_type(con)
    fig = go.Figure(go.Bar(
        y=by_type["disruption_type"].str.capitalize(), x=by_type["avg_delay"], orientation="h",
        marker_color=[charts.MUTED if t == "none" else charts.DEPARTURE for t in by_type["disruption_type"]],
        text=by_type["avg_delay"].map("{:.2f}".format), textposition="outside", cliponaxis=False,
        customdata=by_type[["arrivals", "on_time_pct", "max_delay"]],
        hovertemplate="%{y}<br>Average %{x:.2f} min<br>On time %{customdata[1]:.1f}%<br>Max %{customdata[2]} min"
                      "<br>%{customdata[0]} arrivals<extra></extra>",
    ))
    fig.update_xaxes(title_text="Average arrival delay (minutes)")
    charts.show(fig, "Arrival delay by disruption type", "Stops flagged with each type, against unflagged stops.")
with right:
    onset = queries.onset_profile(con)
    fig = go.Figure()
    for measure, colour in [("arrival", charts.ARRIVAL), ("departure", charts.DEPARTURE)]:
        part = onset[onset["measure"] == measure]
        fig.add_trace(go.Scatter(x=part["stops_since_onset"], y=part["avg_delay"], name=measure.capitalize(),
                                 mode="lines+markers", line=dict(color=colour, width=3),
                                 customdata=part[["observations"]],
                                 hovertemplate="Stop %{x}: %{y:.2f} min (%{customdata[0]} observations)"))
    fig.update_xaxes(title_text="Stops since onset (0 = first disrupted stop)", dtick=1)
    fig.update_yaxes(title_text="Average delay (minutes)", rangemode="tozero")
    charts.show(fig, "Delay compounds once a disruption starts", "No recovery before the end of the route.")

bands = queries.delay_bands(all_obs)
fig = go.Figure()
for col, colour in [("Undisrupted runs", charts.ARRIVAL), ("Disrupted runs", charts.DEPARTURE)]:
    if col in bands:
        fig.add_trace(go.Bar(x=bands.index.astype(str), y=bands[col], name=col, marker_color=colour,
                             hovertemplate="%{x}: %{y} arrivals"))
fig.update_layout(barmode="stack")
fig.update_yaxes(title_text="Arrivals (log scale)", type="log")
charts.show(fig, "Long delays come mostly from disrupted runs", "Arrivals by delay band.")

st.subheader("Most delayed runs")
st.dataframe(
    queries.worst_runs(con), hide_index=True, width="stretch",
    column_config={
        "service_id": "Run", "service_date": st.column_config.DateColumn("Date", format="ddd D MMM YYYY"),
        "train_id": "Train", "final_arrival_delay": "Delay at terminus (min)",
        "max_arrival_delay": "Max arrival delay (min)", "disruption_types": "Disruption types",
    },
)
st.caption("Open a run in the Run explorer to see it stop by stop.")
