"""Data and quality: where the data comes from, integrity checks on the loaded tables, definitions and downloads."""
from datetime import datetime

import streamlit as st

from dashboard import data, queries

con, filters, obs = data.page_context()

st.title("Data and quality")
st.caption(data.SYNTHETIC_NOTE)

st.subheader("Source")
updated = datetime.fromtimestamp(data.db_version())
st.markdown(f"Cleaned layer from `{data.DB_PATH.name}`, built by notebooks 01 (load) and 03 (cleaning). "
            f"Last rebuilt {updated:%d %b %Y %H:%M}.")
st.dataframe(queries.table_summary(con), hide_index=True, width="stretch", column_config={
    "table_name": "Table in the app", "source": "Source table", "row_count": "Rows", "grain": "Grain"})

st.subheader("Integrity checks")
checks = queries.integrity_checks(con)
checks["result"] = checks["violations"].map(lambda n: "Pass" if n == 0 else "Fail")
failed = int((checks["violations"] > 0).sum())
if failed:
    st.error(f"{failed} of {len(checks)} checks failed. Rerun notebook 03 and review notebook 02.")
else:
    st.success(f"All {len(checks)} checks pass on the loaded tables.")
st.dataframe(checks.style.map(lambda r: "color: #2e8b57" if r == "Pass" else "color: #c0392b; font-weight: 600",
                              subset=["result"]),
             hide_index=True, width="stretch",
             column_config={"check_name": "Check", "violations": "Violations", "result": "Result"})

st.subheader("Definitions")
st.markdown(f"""
- **Delay**: actual minus scheduled time in minutes. Early running is negative and is floored at -2 minutes in the source.
- **On time**: a delay of at most {filters.threshold} minutes (set in the sidebar). The notebooks use 5 minutes.
- **Disrupted run**: a run where any stop carries a simulated disruption flag. All of its stops count as disrupted,
  since delay carries along the run.
- **Origin and terminus**: the origin has no arrival and the terminus no departure; these placeholders are removed
  in notebook 03, so averages only use real observations.
- **Confidence intervals** on the Trains page resample whole runs, because stops of one run are not independent.
""")

st.subheader("Download")
st.caption("Delay observations in long format (one row per stop per measure), with the sidebar filters applied.")
st.download_button("Download filtered observations (CSV)", obs.to_csv(index=False),
                   f"railpulse_delay_observations_{filters.start}_{filters.end}.csv", "text/csv")
