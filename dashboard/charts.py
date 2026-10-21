"""Shared chart styling. Colours follow the notebooks: blue for arrivals, orange for departures."""
import plotly.graph_objects as go
import streamlit as st

ARRIVAL, DEPARTURE, MUTED = "#2f6db5", "#d9822b", "#9aa5b1"
GOOD, BAD = "#2e8b57", "#c0392b"
BLUE_RAMP = ["#eaf1fa", "#bcd3ee", "#8bb3e0", "#5a92d2", "#2f6db5", "#1d4a82"]
STATUS_COLOURS = {"On time": GOOD, "Late": DEPARTURE, "Disrupted": BAD, "Not departed": MUTED, "Arrived": ARRIVAL}


def show(fig, title, subtitle=None, height=420):
    text = f"<b>{title}</b>" + (f"<br><span style='font-size:12px'>{subtitle}</span>" if subtitle else "")
    fig.update_layout(
        title=dict(text=text, x=0, xanchor="left"), height=height,
        margin=dict(t=80 if subtitle else 60, l=10, r=10, b=10),
        legend=dict(orientation="h", y=1.02, yanchor="bottom", x=1, xanchor="right", title_text=""),
        hoverlabel=dict(namelength=-1),
    )
    st.plotly_chart(fig, width="stretch")


def reference_line(fig, value, label, axis="x", **kwargs):
    """A dotted reference line, such as the network average or the on-time target."""
    add = fig.add_vline if axis == "x" else fig.add_hline
    add(value, line=dict(color=MUTED, width=1, dash="dot"), annotation_text=label,
        annotation_font=dict(color=MUTED, size=11), **kwargs)


def ranked_bars(frame, label_col, value_col, hover, colour=ARRIVAL):
    """Horizontal bars, largest at the top."""
    ordered = frame.sort_values(value_col)
    return go.Figure(go.Bar(
        y=ordered[label_col], x=ordered[value_col], orientation="h", marker_color=colour,
        text=ordered[value_col].map("{:.2f}".format), textposition="outside", cliponaxis=False,
        customdata=ordered[hover["columns"]], hovertemplate=hover["template"] + "<extra></extra>",
    ))
