"""Analysis queries. Each reads the delay_obs table registered by data.register_delay_obs, or the cleaned tables."""
import numpy as np
import pandas as pd

from dashboard.data import query

BAND_ORDER = ["Night 00-06", "Morning 06-12", "Afternoon 12-18", "Evening 18-24"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# 6h bands instead of hours: each train runs at a fixed time, so hourly would just compare trains
TIME_BAND_SQL = """
    CASE
        WHEN hour(scheduled_time) < 6 THEN 'Night 00-06'
        WHEN hour(scheduled_time) < 12 THEN 'Morning 06-12'
        WHEN hour(scheduled_time) < 18 THEN 'Afternoon 12-18'
        ELSE 'Evening 18-24'
    END
"""


def headline(obs, threshold):
    """Network headline measures for a frame of delay observations."""
    arrivals = obs[obs["measure"] == "arrival"]
    departures = obs[obs["measure"] == "departure"]
    runs = obs.groupby("service_id")["run_disrupted"].first()
    late = arrivals[arrivals["delay_min"] > threshold]
    return dict(
        runs=len(runs),
        disrupted_runs=int(runs.sum()),
        arrivals=len(arrivals),
        arrival_on_time_pct=100 * arrivals["is_on_time"].mean(),
        departure_on_time_pct=100 * departures["is_on_time"].mean(),
        avg_arrival_delay=arrivals["delay_min"].mean(),
        median_arrival_delay=arrivals["delay_min"].median(),
        p90_arrival_delay=arrivals["delay_min"].quantile(0.9),
        late_arrivals=len(late),
        delay_minutes=arrivals["delay_min"].clip(lower=0).sum(),
    )


def daily_trend(con):
    return query(con, """
        WITH daily AS (
            SELECT service_date, COUNT(*) AS arrivals, SUM(delay_min) AS total_delay, SUM(is_on_time::INT) AS on_time
            FROM delay_obs WHERE measure = 'arrival' GROUP BY service_date
        )
        SELECT
            service_date,
            arrivals,
            total_delay / arrivals AS avg_delay,
            100.0 * on_time / arrivals AS on_time_pct,
            -- weighted 7-day average, null until there are 7 days
            CASE WHEN COUNT(*) OVER week = 7 THEN SUM(total_delay) OVER week / SUM(arrivals) OVER week END AS avg_delay_7d,
            CASE WHEN COUNT(*) OVER week = 7 THEN 100.0 * SUM(on_time) OVER week / SUM(arrivals) OVER week END AS on_time_pct_7d
        FROM daily
        WINDOW week AS (ORDER BY service_date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW)
        ORDER BY service_date
    """)


def delay_distribution(con):
    return query(con, "SELECT measure, delay_min, COUNT(*) AS observations FROM delay_obs GROUP BY ALL ORDER BY ALL")


def weekday_band(con):
    grid = query(con, f"""
        SELECT dayname(service_date) AS weekday, {TIME_BAND_SQL} AS time_band,
            COUNT(*) AS arrivals, AVG(delay_min) AS avg_delay
        FROM delay_obs WHERE measure = 'arrival'
        GROUP BY ALL
    """)
    days = [d for d in WEEKDAYS if d in set(grid["weekday"])]
    bands = [b for b in BAND_ORDER if b in set(grid["time_band"])]
    values = grid.pivot(index="weekday", columns="time_band", values="avg_delay").reindex(index=days, columns=bands)
    counts = grid.pivot(index="weekday", columns="time_band", values="arrivals").reindex(index=days, columns=bands)
    return values, counts


def by_train(con, target_pct):
    frame = query(con, """
        SELECT
            o.train_id,
            ANY_VALUE(t.train_name) AS train_name,
            ANY_VALUE(t.origin_station) || ' to ' || ANY_VALUE(t.destination_station) AS route,
            COUNT(DISTINCT o.service_id) AS runs,
            COUNT(DISTINCT o.service_id) FILTER (WHERE o.run_disrupted) AS disrupted_runs,
            COUNT(*) FILTER (WHERE o.measure = 'arrival') AS arrivals,
            AVG(o.delay_min) FILTER (WHERE o.measure = 'arrival') AS avg_arrival_delay,
            AVG(o.delay_min) FILTER (WHERE o.measure = 'arrival' AND NOT o.run_disrupted) AS avg_delay_undisrupted,
            MEDIAN(o.delay_min) FILTER (WHERE o.measure = 'arrival') AS median_arrival_delay,
            MAX(o.delay_min) FILTER (WHERE o.measure = 'arrival') AS max_arrival_delay,
            100.0 * AVG(o.is_on_time::INT) FILTER (WHERE o.measure = 'arrival') AS arrival_on_time_pct,
            100.0 * AVG(o.is_on_time::INT) FILTER (WHERE o.measure = 'departure') AS departure_on_time_pct
        FROM delay_obs o JOIN trains t USING (train_id)
        GROUP BY o.train_id
        ORDER BY avg_arrival_delay DESC
    """)
    frame.insert(0, "rank", frame["avg_arrival_delay"].rank(ascending=False, method="min").astype(int))
    frame["meets_target"] = frame["arrival_on_time_pct"] >= target_pct
    return frame


def train_intervals(obs, n_boot=1000, seed=42):
    """Mean arrival delay per train with a 95% bootstrap interval, resampling whole runs (notebook 05 method)."""
    rng = np.random.default_rng(seed)
    arrivals = obs[obs["measure"] == "arrival"]
    rows = []
    for train_id, part in arrivals.groupby("train_id"):
        runs = part.groupby("service_id")["delay_min"].agg(["sum", "count"])
        sums, counts = runs["sum"].to_numpy(), runs["count"].to_numpy()
        idx = rng.integers(0, len(runs), (n_boot, len(runs)))
        means = sums[idx].sum(1) / counts[idx].sum(1)
        low, high = np.percentile(means, [2.5, 97.5])
        rows.append(dict(train_id=train_id, runs=len(runs), avg_delay=sums.sum() / counts.sum(), ci_low=low, ci_high=high))
    return pd.DataFrame(rows).sort_values("avg_delay")


def train_stop_profile(con, train_id):
    return query(con, """
        SELECT station_sequence, ANY_VALUE(s.station_name) AS station_name, measure, AVG(delay_min) AS avg_delay,
            100.0 * AVG(is_on_time::INT) AS on_time_pct
        FROM delay_obs o JOIN stations s USING (station_id)
        WHERE train_id = $train_id
        GROUP BY station_sequence, measure
        ORDER BY station_sequence, measure DESC
    """, dict(train_id=train_id))


def train_daily(con, train_id):
    return query(con, """
        SELECT service_date, service_id, AVG(delay_min) AS avg_delay,
            arg_max(delay_min, station_sequence) AS final_delay, BOOL_OR(is_disrupted) AS disrupted
        FROM delay_obs
        WHERE train_id = $train_id AND measure = 'arrival'
        GROUP BY ALL
        ORDER BY service_date
    """, dict(train_id=train_id))


def by_region(con):
    return query(con, """
        SELECT region, COUNT(DISTINCT station_id) AS stations, COUNT(*) AS arrivals,
            AVG(delay_min) AS avg_delay, 100.0 * AVG(is_on_time::INT) AS on_time_pct
        FROM delay_obs WHERE measure = 'arrival'
        GROUP BY region ORDER BY avg_delay DESC
    """)


def by_station(con):
    return query(con, """
        SELECT
            o.station_id, ANY_VALUE(s.station_name) AS station_name, ANY_VALUE(o.region) AS region,
            COUNT(DISTINCT o.train_id) AS trains_serving,
            COUNT(*) FILTER (WHERE o.measure = 'arrival') AS arrivals,
            AVG(o.delay_min) FILTER (WHERE o.measure = 'arrival') AS avg_arrival_delay,
            100.0 * AVG(o.is_on_time::INT) FILTER (WHERE o.measure = 'arrival') AS arrival_on_time_pct,
            AVG(o.delay_min) FILTER (WHERE o.measure = 'departure') AS avg_departure_delay
        FROM delay_obs o JOIN stations s USING (station_id)
        GROUP BY o.station_id
        HAVING arrivals > 0
        ORDER BY avg_arrival_delay DESC
    """)


def station_dwell(con):
    """Scheduled against actual dwell at intermediate stops of the filtered runs."""
    return query(con, """
        SELECT
            e.station_id, ANY_VALUE(s.station_name) AS station_name,
            COUNT(e.actual_dwell_min) AS stops,
            AVG(e.scheduled_dwell_min) AS scheduled_dwell,
            AVG(e.actual_dwell_min) AS actual_dwell,
            AVG(e.actual_dwell_min - e.scheduled_dwell_min) AS overrun,
            100.0 * AVG((e.actual_dwell_min > e.scheduled_dwell_min)::INT) AS pct_over_schedule
        FROM events e JOIN stations s USING (station_id)
        WHERE (e.service_id, e.station_sequence) IN (SELECT (service_id, station_sequence) FROM delay_obs)
          AND e.actual_dwell_min IS NOT NULL
        GROUP BY e.station_id
        ORDER BY overrun DESC
    """)


def along_run(con):
    """Average delay at each event over the first five stops: arrive at stop k = event 2k - 1, depart = 2k."""
    return query(con, """
        SELECT
            station_sequence * 2 - (measure = 'arrival')::INT AS event_order,
            CASE WHEN measure = 'arrival' THEN 'Arrive ' ELSE 'Depart ' END || station_sequence AS event,
            measure, COUNT(*) AS observations, AVG(delay_min) AS avg_delay
        FROM delay_obs
        WHERE (measure = 'departure' AND station_sequence <= 4) OR (measure = 'arrival' AND station_sequence BETWEEN 2 AND 5)
        GROUP BY ALL
        ORDER BY event_order
    """)


def running_vs_standing(con):
    return query(con, """
        WITH pairs AS (
            SELECT service_id, station_sequence,
                MAX(delay_min) FILTER (WHERE measure = 'arrival') AS arrival,
                MAX(delay_min) FILTER (WHERE measure = 'departure') AS departure
            FROM delay_obs GROUP BY ALL
        ),
        steps AS (
            SELECT
                arrival - LAG(departure) OVER (PARTITION BY service_id ORDER BY station_sequence) AS running,
                departure - arrival AS standing
            FROM pairs
        )
        SELECT 'Running between stops' AS phase, AVG(running) AS avg_change_min,
            100.0 * AVG((running > 0)::INT) AS pct_delay_grew, COUNT(running) AS observations
        FROM steps WHERE running IS NOT NULL
        UNION ALL
        SELECT 'Standing at a stop', AVG(standing), 100.0 * AVG((standing > 0)::INT), COUNT(standing)
        FROM steps WHERE standing IS NOT NULL
    """)


def by_disruption_type(con):
    return query(con, """
        SELECT disruption_type, COUNT(*) AS arrivals, AVG(delay_min) AS avg_delay,
            100.0 * AVG(is_on_time::INT) AS on_time_pct, MAX(delay_min) AS max_delay
        FROM delay_obs WHERE measure = 'arrival'
        GROUP BY disruption_type ORDER BY avg_delay
    """)


def onset_profile(con):
    return query(con, """
        WITH rel AS (
            SELECT *, station_sequence - MIN(station_sequence) FILTER (WHERE is_disrupted)
                OVER (PARTITION BY service_id) AS stops_since_onset
            FROM delay_obs
        )
        SELECT stops_since_onset, measure, COUNT(*) AS observations, AVG(delay_min) AS avg_delay
        FROM rel WHERE stops_since_onset BETWEEN -1 AND 5
        GROUP BY ALL ORDER BY stops_since_onset
    """)


def delay_bands(obs):
    arrivals = obs[obs["measure"] == "arrival"]
    bands = pd.cut(arrivals["delay_min"], bins=[-100, 5, 10, 15, 1000],
                   labels=["5 min or less", "6-10 min", "11-15 min", "Over 15 min"])
    return (arrivals.groupby([bands, arrivals["run_disrupted"]], observed=False).size()
            .unstack(fill_value=0).rename(columns={False: "Undisrupted runs", True: "Disrupted runs"}))


def worst_runs(con, limit=10):
    return query(con, """
        SELECT
            service_id, service_date, train_id,
            arg_max(delay_min, station_sequence) FILTER (WHERE measure = 'arrival') AS final_arrival_delay,
            MAX(delay_min) FILTER (WHERE measure = 'arrival') AS max_arrival_delay,
            COALESCE(string_agg(DISTINCT disruption_type, ', ') FILTER (WHERE is_disrupted), 'none') AS disruption_types
        FROM delay_obs
        GROUP BY ALL
        ORDER BY final_arrival_delay DESC, max_arrival_delay DESC, service_id
        LIMIT $limit
    """, dict(limit=limit))


def threshold_curve(con):
    return query(con, """
        SELECT t AS threshold_min, measure, 100.0 * AVG((delay_min <= t)::INT) AS on_time_pct
        FROM delay_obs, range(0, 16) AS r(t)
        GROUP BY ALL ORDER BY threshold_min
    """)


def findings(obs, trains, stations, threshold):
    """Plain-language observations for the overview page."""
    notes = []
    if len(trains) > 1:
        worst, best = trains.iloc[0], trains.iloc[-1]
        notes.append(f"{worst['train_id']} {worst['train_name']} has the highest average arrival delay "
                     f"({worst['avg_arrival_delay']:.2f} min); {best['train_id']} {best['train_name']} the lowest "
                     f"({best['avg_arrival_delay']:.2f} min).")
    if len(stations) > 1:
        worst = stations.iloc[0]
        notes.append(f"{worst['station_name']} ({worst['region']}) is the most delayed station at "
                     f"{worst['avg_arrival_delay']:.2f} min, with {worst['arrival_on_time_pct']:.1f}% of arrivals on time.")
    arrivals = obs[obs["measure"] == "arrival"]
    disrupted = arrivals[arrivals["run_disrupted"]]
    if len(disrupted) and len(disrupted) < len(arrivals):
        lateness = arrivals["delay_min"].clip(lower=0)
        share_minutes = 100 * lateness[arrivals["run_disrupted"]].sum() / max(lateness.sum(), 1)
        share_arrivals = 100 * len(disrupted) / len(arrivals)
        notes.append(f"Disrupted runs supply {share_arrivals:.1f}% of arrivals but {share_minutes:.1f}% of all late minutes.")
    daily = arrivals.groupby("service_date")["delay_min"].mean()
    if len(daily) > 1:
        notes.append(f"The worst day was {pd.Timestamp(daily.idxmax()):%a %d %b} at {daily.max():.2f} min average delay; "
                     f"the best was {pd.Timestamp(daily.idxmin()):%a %d %b} at {daily.min():.2f} min.")
    late_share = 100 * (arrivals["delay_min"] > threshold).mean()
    notes.append(f"{late_share:.1f}% of arrivals were more than {threshold} min late.")
    return notes


def integrity_checks(con):
    """Invariants of the cleaned layer from notebook 03, recomputed on the loaded tables. Each count should be 0."""
    return query(con, """
        SELECT 'Duplicate keys (service_id, station_sequence)' AS check_name,
            (SELECT COUNT(*) - COUNT(DISTINCT (service_id, station_sequence)) FROM events) AS violations
        UNION ALL SELECT 'Events without a matching train',
            (SELECT COUNT(*) FROM events ANTI JOIN trains USING (train_id))
        UNION ALL SELECT 'Events without a matching station',
            (SELECT COUNT(*) FROM events ANTI JOIN stations USING (station_id))
        UNION ALL SELECT 'Origin rows carrying an arrival',
            (SELECT COUNT(*) FROM events WHERE is_origin AND arrival_delay_min IS NOT NULL)
        UNION ALL SELECT 'Terminus rows carrying a departure',
            (SELECT COUNT(*) FROM events WHERE is_terminus AND departure_delay_min IS NOT NULL)
        UNION ALL SELECT 'Negative dwell values',
            (SELECT COUNT(*) FROM events WHERE actual_dwell_min < 0)
        UNION ALL SELECT 'Negative lateness values',
            (SELECT COUNT(*) FROM events WHERE arrival_late_min < 0 OR departure_late_min < 0)
        UNION ALL SELECT 'Runs with a gap in the stop sequence',
            (SELECT COUNT(*) FROM (SELECT service_id FROM events GROUP BY service_id
                                   HAVING MAX(station_sequence) <> COUNT(*)))
        UNION ALL SELECT 'Records not marked as synthetic',
            (SELECT COUNT(*) FROM events WHERE data_status <> 'SYNTHETIC_SIMULATED')
    """)


def table_summary(con):
    return query(con, """
        SELECT 'events' AS table_name, 'train_run_events_clean' AS source, COUNT(*) AS row_count,
            'One row per train run per station stop' AS grain FROM events
        UNION ALL SELECT 'trains', 'train_master_clean', COUNT(*), 'One row per train' FROM trains
        UNION ALL SELECT 'stations', 'station_master_clean', COUNT(*), 'One row per station' FROM stations
    """)
