![RailPulse case study](case_study/railpulse_case_study.png)

## Dashboard

An interactive Streamlit dashboard on top of the cleaned layer in `railpulse.duckdb`.

| Page | What it shows |
| --- | --- |
| Overview | Headline measures with change against the previous period, status against an on-time target, findings written from the data, daily trend, delay distribution, weekday by time-of-day heatmap, threshold sensitivity |
| Trains | Ranking with 95% bootstrap intervals (resampled by run), scorecard against the target, single-train drill-down |
| Stations | Regional summary, station ranking, where delay is added along a run, dwell overruns |
| Disruptions | Share of late minutes caused by disruptions, the network without disrupted runs, delay growth after onset, most delayed runs |
| Live board | Replays a recorded day as a live operations board: position, status, current delay and expected arrival of every train |
| Run explorer | One run stop by stop, with a time-distance chart of schedule against actual |
| Data and quality | Source tables, integrity checks on the loaded data, definitions, CSV download |

The sidebar filters (dates, trains, regions, on-time threshold, on-time target, disrupted runs) apply to every page.

### Run locally

```
pip install -r requirements.txt
streamlit run app.py
```

The app reads `railpulse.duckdb`. Rebuild it with notebooks 01 and 03; the dashboard picks up the new file on the next refresh.

### Tests

```
pytest
```

The tests check that the dashboard reproduces the notebook figures, that the live board places trains correctly, and that every page renders.

### Layout

```
app.py                  entry point: sidebar filters and page navigation
dashboard/data.py       loading the database and applying the filters
dashboard/queries.py    analysis queries
dashboard/live.py       live board logic
dashboard/charts.py     shared chart styling
dashboard/views/        one file per page
tests/                  pytest suite
```

All records are synthetic. The findings are illustrative and are not actual Bangladesh Railway performance.
