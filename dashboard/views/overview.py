"""Network overview: headline measures against the previous period and the target, findings and trends."""
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from dashboard import charts, data, queries

con, filters, obs = data.page_context()

st.title("Network overview")
st.caption(f"{filters.start:%d %b %Y} to {filters.end:%d %b %Y}. On time means at most {filters.threshold} min late. "
           + data.SYNTHETIC_NOTE)

now = queries.headline(obs, filters.threshold)
earlier_filters = data.previous_period(filters, st.session_state["first_date"])
earlier = None
if earlier_filters is not None:
    earlier_obs = data.delay_observations(con, earlier_filters)
    if not earlier_obs.empty:
        earlier = queries.headline(earlier_obs, filters.threshold)


def delta(key, fmt, suffix):
    if earlier is None:
        return None
    return f"{now[key] - earlier[key]:{fmt}}{suffix}"


cols = st.columns(5)
cols[0].metric("Arrivals on time", f"{now['arrival_on_time_pct']:.1f}%", delta("arrival_on_time_pct", "+.1f", " pts"),
               help=f"Share of arrivals at most {filters.threshold} min late")
cols[1].metric("Departures on time", f"{now['departure_on_time_pct']:.1f}%",
               delta("departure_on_time_pct", "+.1f", " pts"))
cols[2].metric("Average arrival delay", f"{now['avg_arrival_delay']:.2f} min",
               delta("avg_arrival_delay", "+.2f", " min"), delta_color="inverse",
               help="Early arrivals count as negative minutes")
cols[3].metric("90th percentile delay", f"{now['p90_arrival_delay']:.0f} min",
               delta("p90_arrival_delay", "+.0f", " min"), delta_color="inverse")
cols[4].metric("Disrupted runs", f"{now['disrupted_runs']} of {now['runs']}",
               f"{100 * now['disrupted_runs'] / now['runs']:.1f}% of runs", delta_color="off")
if earlier is None:
    st.caption("No comparison: the period before the selected dates is outside the data.")
else:
    st.caption(f"Changes are against the previous {(filters.end - filters.start).days + 1} days "
               f"({earlier_filters.start:%d %b} to {earlier_filters.end:%d %b}).")

gap = now["arrival_on_time_pct"] - filters.target_pct
if gap >= 0:
    st.success(f"Arrival on-time performance is {gap:.1f} points above the {filters.target_pct}% target.")
else:
    st.error(f"Arrival on-time performance is {-gap:.1f} points below the {filters.target_pct}% target.")

trains = queries.by_train(con, filters.target_pct)
stations = queries.by_station(con)
with st.container(border=True):
    st.markdown("**Key findings**")
    st.markdown("\n".join(f"- {note}" for note in queries.findings(obs, trains, stations, filters.threshold)))

trend = queries.daily_trend(con)
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.12,
                    subplot_titles=("Average arrival delay (min)", "On-time arrivals (%)"))
for row, (daily, rolling) in enumerate([("avg_delay", "avg_delay_7d"), ("on_time_pct", "on_time_pct_7d")], start=1):
    fig.add_trace(go.Scatter(x=trend["service_date"], y=trend[daily], name="Daily", mode="lines",
                             line=dict(color=charts.MUTED, width=1.5), legendgroup="daily", showlegend=row == 1,
                             hovertemplate="%{y:.2f}"), row=row, col=1)
    fig.add_trace(go.Scatter(x=trend["service_date"], y=trend[rolling], name="7-day average", mode="lines",
                             line=dict(color=charts.ARRIVAL, width=2.5), legendgroup="rolling", showlegend=row == 1,
                             hovertemplate="%{y:.2f}"), row=row, col=1)
fig.add_hline(filters.target_pct, line=dict(color=charts.BAD, width=1, dash="dot"), row=2, col=1,
              annotation_text=f"Target {filters.target_pct}%", annotation_font=dict(color=charts.BAD, size=11))
fig.update_layout(hovermode="x unified")
fig.update_annotations(selector=dict(xref="x domain"), x=0, xanchor="left")
charts.show(fig, "Daily arrival delay and on-time performance",
            "Grey: daily value. Blue: 7-day average weighted by arrivals.", height=560)

left, right = st.columns(2)
with left:
    distribution = queries.delay_distribution(con)
    fig = go.Figure()
    for measure, colour in [("arrival", charts.ARRIVAL), ("departure", charts.DEPARTURE)]:
        part = distribution[distribution["measure"] == measure]
        fig.add_trace(go.Bar(x=part["delay_min"], y=part["observations"], name=measure.capitalize(),
                             marker_color=colour, hovertemplate="%{x} min: %{y} observations"))
    charts.reference_line(fig, filters.threshold + 0.5, f"Late: over {filters.threshold} min")
    fig.update_layout(barmode="group", bargap=0.15)
    fig.update_xaxes(title_text="Delay (minutes)")
    fig.update_yaxes(title_text="Observations")
    charts.show(fig, "Delay distribution", "Most stops run within a few minutes of schedule.")
with right:
    values, counts = queries.weekday_band(con)
    shown = values.where(counts >= 30)
    fig = go.Figure(go.Heatmap(
        z=shown.values, x=list(shown.columns), y=list(shown.index), customdata=counts.values,
        text=shown.map(lambda v: "" if v != v else f"{v:.1f}").values, texttemplate="%{text}",
        colorscale=[[i / (len(charts.BLUE_RAMP) - 1), c] for i, c in enumerate(charts.BLUE_RAMP)],
        xgap=2, ygap=2, hoverongaps=False, colorbar=dict(title=dict(text="min"), thickness=10, outlinewidth=0),
        hovertemplate="%{y}, %{x}<br>Average %{z:.2f} min<br>%{customdata} arrivals<extra></extra>",
    ))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(showgrid=False)
    charts.show(fig, "Delay by weekday and time of day", "Average arrival delay. Cells under 30 arrivals are blank.")

curve = queries.threshold_curve(con)
fig = go.Figure()
for measure, colour in [("arrival", charts.ARRIVAL), ("departure", charts.DEPARTURE)]:
    part = curve[curve["measure"] == measure]
    fig.add_trace(go.Scatter(x=part["threshold_min"], y=part["on_time_pct"], name=measure.capitalize(),
                             mode="lines+markers", line=dict(color=colour, width=3),
                             hovertemplate="Within %{x} min: %{y:.1f}%"))
charts.reference_line(fig, filters.threshold, "Selected threshold")
charts.reference_line(fig, filters.target_pct, f"Target {filters.target_pct}%", axis="y")
fig.update_xaxes(title_text="On-time threshold (minutes late)", dtick=1)
fig.update_yaxes(title_text="On time (%)", range=[0, 100])
charts.show(fig, "How the on-time figure depends on the threshold",
            "Early arrivals are floored at -2 minutes in the source data.")
