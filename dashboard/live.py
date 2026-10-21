"""Replaying recorded runs as a live operations board: where every train is at a given moment."""
from datetime import datetime, timedelta

import pandas as pd

from dashboard.data import query

STATUS_ORDER = ["Disrupted", "Late", "On time", "Not departed", "Arrived"]


def stops_for_day(con, day, trains):
    """Stop rows of every run that is under way at some point on the given day, including overnight runs."""
    day_start = datetime.combine(day, datetime.min.time())
    return query(con, """
        WITH runs AS (
            SELECT service_id
            FROM events
            WHERE list_contains($trains, train_id)
            GROUP BY service_id
            HAVING MIN(scheduled_departure) < $day_end
               AND MAX(COALESCE(actual_arrival, actual_departure)) >= $day_start
        )
        SELECT e.service_id, e.service_date, e.train_id, t.train_name, e.station_sequence, e.station_id, s.station_name,
            e.is_origin, e.is_terminus, e.scheduled_arrival, e.actual_arrival, e.arrival_delay_min,
            e.scheduled_departure, e.actual_departure, e.departure_delay_min,
            e.simulated_disruption_flag, e.simulated_disruption_type
        FROM events e
        JOIN runs USING (service_id)
        JOIN trains t USING (train_id)
        JOIN stations s USING (station_id)
        ORDER BY e.service_id, e.station_sequence
    """, dict(trains=list(trains), day_start=day_start, day_end=day_start + timedelta(days=1)))


def _run_state(stops, now, threshold):
    """State of one run at time `now`, from what had been observed by then."""
    stops = stops.sort_values("station_sequence")
    origin, terminus = stops.iloc[0], stops.iloc[-1]
    total = len(stops)
    row = dict(service_id=origin["service_id"], train_id=origin["train_id"], train_name=origin["train_name"],
               route=f"{origin['station_name']} to {terminus['station_name']}",
               scheduled_departure=origin["scheduled_departure"], scheduled_arrival=terminus["scheduled_arrival"])

    if now < origin["actual_departure"]:
        return row | dict(status="Not departed", location=f"At {origin['station_name']}", delay_min=None,
                          next_stop=origin["station_name"], expected=origin["scheduled_departure"], progress=0.0)

    # observed events up to now, in order: arrive then depart at each stop
    events = []
    for _, stop in stops.iterrows():
        if pd.notna(stop["actual_arrival"]):
            events.append((stop["actual_arrival"], "arrive", stop))
        if pd.notna(stop["actual_departure"]):
            events.append((stop["actual_departure"], "depart", stop))
    seen = [e for e in events if e[0] <= now]
    disrupted = any(stop["simulated_disruption_flag"] for _, _, stop in seen)
    _, kind, stop = seen[-1]
    delay = stop["arrival_delay_min"] if kind == "arrive" else stop["departure_delay_min"]

    if now >= terminus["actual_arrival"]:
        return row | dict(status="Arrived", location=f"At {terminus['station_name']}", delay_min=delay,
                          next_stop=None, expected=None, progress=1.0, disrupted=disrupted)

    position = stop["station_sequence"]
    following = stops[stops["station_sequence"] == position + 1].iloc[0]
    if kind == "arrive":
        location = f"At {stop['station_name']}"
        passed = position - 1
    else:
        location = f"Between {stop['station_name']} and {following['station_name']}"
        passed = position - 0.5
    # expected arrival at the next stop assumes the current delay holds
    expected = following["scheduled_arrival"] + timedelta(minutes=float(delay))
    if disrupted:
        status = "Disrupted"
    elif delay > threshold:
        status = "Late"
    else:
        status = "On time"
    return row | dict(status=status, location=location, delay_min=delay, next_stop=following["station_name"],
                      expected=expected, progress=passed / (total - 1), disrupted=disrupted)


def board_at(stops, now, threshold):
    """One row per run with its status at `now`, running trains first."""
    if stops.empty:
        return pd.DataFrame()
    board = pd.DataFrame([_run_state(part, now, threshold) for _, part in stops.groupby("service_id")])
    board["status_order"] = board["status"].map(STATUS_ORDER.index)
    return board.sort_values(["status_order", "scheduled_departure"]).drop(columns="status_order").reset_index(drop=True)
