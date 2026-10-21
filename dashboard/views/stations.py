"""Station performance: regions, station ranking, where delay is added along a run, and dwell overruns."""
import plotly.graph_objects as go
import streamlit as st

from dashboard import charts, data, queries

con, filters, obs = data.page_context()

st.title("Stations")
st.caption(data.SYNTHETIC_NOTE)

network = queries.headline(obs, filters.threshold)
regions = queries.by_region(con)
cols = st.columns(len(regions))
for col, (_, region) in zip(cols, regions.iterrows()):
    col.metric(region["region"], f"{region['on_time_pct']:.1f}% on time",
               f"{region['avg_delay'] - network['avg_arrival_delay']:+.2f} min vs network", delta_color="inverse",
               help=f"{int(region['stations'])} stations, {int(region['arrivals'])} arrivals")

stations = queries.by_station(con)
stations["label"] = stations["station_id"] + "  " + stations["station_name"]
stations["below_target"] = stations["arrival_on_time_pct"] < filters.target_pct
ordered = stations.sort_values("avg_arrival_delay")
fig = go.Figure(go.Bar(
    y=ordered["label"], x=ordered["avg_arrival_delay"], orientation="h",
    marker_color=[charts.BAD if b else charts.ARRIVAL for b in ordered["below_target"]],
    text=ordered["avg_arrival_delay"].map("{:.2f}".format), textposition="outside", cliponaxis=False,
    customdata=ordered[["region", "arrivals", "arrival_on_time_pct", "trains_serving"]],
    hovertemplate="%{y} (%{customdata[0]})<br>Average %{x:.2f} min<br>On time %{customdata[2]:.1f}%"
                  "<br>%{customdata[1]} arrivals from %{customdata[3]} trains<extra></extra>",
))
charts.reference_line(fig, network["avg_arrival_delay"], f"Network {network['avg_arrival_delay']:.2f}")
fig.update_xaxes(title_text="Average arrival delay (minutes)")
charts.show(fig, "Stations ranked by average arrival delay",
            f"Red bars are below the {filters.target_pct}% on-time target. Some stations see only one train.",
            height=max(420, 28 * len(ordered) + 140))

left, right = st.columns(2)
with left:
    profile = queries.along_run(con)
    fig = go.Figure(go.Scatter(x=profile["event"], y=profile["avg_delay"], mode="lines",
                               line=dict(color=charts.MUTED, width=2), showlegend=False, hoverinfo="skip"))
    for measure, colour in [("arrival", charts.ARRIVAL), ("departure", charts.DEPARTURE)]:
        part = profile[profile["measure"] == measure]
        fig.add_trace(go.Scatter(x=part["event"], y=part["avg_delay"], name=measure.capitalize(), mode="markers",
                                 marker=dict(color=colour, size=12), hovertemplate="%{x}: %{y:.2f} min"))
    fig.update_xaxes(categoryorder="array", categoryarray=profile["event"].tolist())
    fig.update_yaxes(title_text="Average delay (minutes)", rangemode="tozero")
    charts.show(fig, "Delay is added at stops and recovered between them", "First five stops of every run.")
with right:
    phases = queries.running_vs_standing(con)
    fig = go.Figure(go.Bar(
        x=phases["phase"], y=phases["avg_change_min"],
        marker_color=[charts.GOOD if v < 0 else charts.BAD for v in phases["avg_change_min"]],
        text=phases["avg_change_min"].map("{:+.2f} min".format), textposition="outside", cliponaxis=False,
        customdata=phases[["pct_delay_grew", "observations"]],
        hovertemplate="%{x}<br>Average change %{y:+.2f} min<br>Delay grew in %{customdata[0]:.1f}%"
                      "<br>%{customdata[1]} observations<extra></extra>", width=0.4,
    ))
    fig.add_hline(0, line=dict(color=charts.MUTED, width=1))
    fig.update_yaxes(title_text="Average change in delay (minutes)")
    charts.show(fig, "Change in delay by phase", "Positive: the train lost time. Negative: it recovered time.")

st.subheader("Dwell time at intermediate stops")
dwell = queries.station_dwell(con)
st.dataframe(
    dwell, hide_index=True, width="stretch",
    column_config={
        "station_id": "Station", "station_name": "Name", "stops": "Stops",
        "scheduled_dwell": st.column_config.NumberColumn("Scheduled dwell (min)", format="%.2f"),
        "actual_dwell": st.column_config.NumberColumn("Actual dwell (min)", format="%.2f"),
        "overrun": st.column_config.NumberColumn("Average overrun (min)", format="%+.2f"),
        "pct_over_schedule": st.column_config.ProgressColumn("Stops over schedule", format="%.1f%%",
                                                             min_value=0, max_value=100),
    },
)
