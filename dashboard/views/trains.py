"""Train performance: ranking with uncertainty, a scorecard against the target, and a single-train drill-down."""
import plotly.graph_objects as go
import streamlit as st

from dashboard import charts, data, queries

con, filters, obs = data.page_context()

st.title("Trains")
st.caption(data.SYNTHETIC_NOTE)

trains = queries.by_train(con, filters.target_pct)
network = queries.headline(obs, filters.threshold)
below = trains[~trains["meets_target"]]

cols = st.columns(3)
cols[0].metric("Trains in view", len(trains))
cols[1].metric("Below the on-time target", len(below), help=f"Arrival on-time below {filters.target_pct}%")
cols[2].metric("Spread of average delay",
               f"{trains['avg_arrival_delay'].max() - trains['avg_arrival_delay'].min():.2f} min",
               help="Most delayed train minus least delayed train")

intervals = queries.train_intervals(obs)
fig = go.Figure(go.Scatter(
    y=intervals["train_id"], x=intervals["avg_delay"], mode="markers",
    marker=dict(color=charts.ARRIVAL, size=11),
    error_x=dict(type="data", symmetric=False, array=intervals["ci_high"] - intervals["avg_delay"],
                 arrayminus=intervals["avg_delay"] - intervals["ci_low"], color=charts.MUTED, thickness=2),
    customdata=intervals[["ci_low", "ci_high", "runs"]],
    hovertemplate="%{y}<br>Average %{x:.2f} min<br>95% interval %{customdata[0]:.2f} to %{customdata[1]:.2f}"
                  "<br>%{customdata[2]} runs<extra></extra>",
))
charts.reference_line(fig, network["avg_arrival_delay"], f"Network {network['avg_arrival_delay']:.2f}")
fig.update_xaxes(title_text="Average arrival delay (minutes)")
charts.show(fig, "Average arrival delay by train, with 95% intervals",
            "Intervals resample whole runs. Overlapping intervals mean the difference may be chance.",
            height=max(380, 36 * len(intervals) + 140))

st.subheader("Scorecard")
st.dataframe(
    trains[["rank", "train_id", "train_name", "route", "runs", "disrupted_runs", "avg_arrival_delay",
            "avg_delay_undisrupted", "max_arrival_delay", "arrival_on_time_pct", "departure_on_time_pct", "meets_target"]],
    hide_index=True, width="stretch",
    column_config={
        "rank": st.column_config.NumberColumn("Rank", help="1 = most delayed"),
        "train_id": "Train", "train_name": "Name", "route": "Route", "runs": "Runs",
        "disrupted_runs": "Disrupted runs",
        "avg_arrival_delay": st.column_config.NumberColumn("Avg delay (min)", format="%.2f"),
        "avg_delay_undisrupted": st.column_config.NumberColumn("Avg delay, undisrupted (min)", format="%.2f"),
        "max_arrival_delay": st.column_config.NumberColumn("Max delay (min)"),
        "arrival_on_time_pct": st.column_config.ProgressColumn("Arrivals on time", format="%.1f%%",
                                                               min_value=0, max_value=100),
        "departure_on_time_pct": st.column_config.ProgressColumn("Departures on time", format="%.1f%%",
                                                                 min_value=0, max_value=100),
        "meets_target": st.column_config.CheckboxColumn(f"Meets {filters.target_pct}% target"),
    },
)
st.download_button("Download scorecard (CSV)", trains.to_csv(index=False), "railpulse_train_scorecard.csv",
                   "text/csv")

st.divider()
st.subheader("Train detail")
choice = st.selectbox("Train", trains["train_id"], format_func=lambda t: f"{t}  {trains.set_index('train_id').at[t, 'train_name']}")
row = trains.set_index("train_id").loc[choice]
master = data.query(con, "SELECT * FROM trains WHERE train_id = $t", dict(t=choice)).iloc[0]

cols = st.columns(4)
cols[0].metric("Arrivals on time", f"{row['arrival_on_time_pct']:.1f}%",
               f"{row['arrival_on_time_pct'] - network['arrival_on_time_pct']:+.1f} pts vs network")
cols[1].metric("Average arrival delay", f"{row['avg_arrival_delay']:.2f} min",
               f"{row['avg_arrival_delay'] - network['avg_arrival_delay']:+.2f} min vs network", delta_color="inverse")
cols[2].metric("Runs", int(row["runs"]), f"{int(row['disrupted_runs'])} disrupted", delta_color="off")
cols[3].metric("Day off", master["non_operating_weekday"] if isinstance(master["non_operating_weekday"], str) else "None",
               help="Weekday on which the train does not run")
st.caption(f"{master['service_type']} service, {master['origin_station']} to {master['destination_station']}, "
           f"{int(master['stops_per_run'])} stops per run.")

left, right = st.columns(2)
with left:
    runs = queries.train_daily(con, choice)
    fig = go.Figure(go.Scatter(
        x=runs["service_date"], y=runs["final_delay"], mode="lines+markers", name="Final arrival delay",
        line=dict(color=charts.MUTED, width=1.5),
        marker=dict(size=8, color=[charts.BAD if d else charts.ARRIVAL for d in runs["disrupted"]]),
        customdata=runs[["service_id", "avg_delay"]],
        hovertemplate="%{x|%a %d %b} %{customdata[0]}<br>Final delay %{y} min<br>Average %{customdata[1]:.2f} min"
                      "<extra></extra>",
    ))
    charts.reference_line(fig, filters.threshold, "On-time threshold", axis="y")
    fig.update_yaxes(title_text="Delay at the terminus (minutes)")
    charts.show(fig, "Delay at the terminus, run by run", "Red markers are disrupted runs.")
with right:
    profile = queries.train_stop_profile(con, choice)
    fig = go.Figure()
    for measure, colour in [("arrival", charts.ARRIVAL), ("departure", charts.DEPARTURE)]:
        part = profile[profile["measure"] == measure]
        fig.add_trace(go.Bar(x=part["station_sequence"].astype(str) + " " + part["station_name"], y=part["avg_delay"],
                             name=measure.capitalize(), marker_color=colour,
                             customdata=part[["on_time_pct"]],
                             hovertemplate="%{x}<br>Average %{y:.2f} min<br>On time %{customdata[0]:.1f}%"))
    stops = profile.drop_duplicates("station_sequence").sort_values("station_sequence")
    fig.update_layout(barmode="group")
    # route order, otherwise the origin (departure only) would be placed last
    fig.update_xaxes(categoryorder="array",
                     categoryarray=(stops["station_sequence"].astype(str) + " " + stops["station_name"]).tolist())
    fig.update_yaxes(title_text="Average delay (minutes)")
    charts.show(fig, "Average delay at each stop", "Stops in route order.")
