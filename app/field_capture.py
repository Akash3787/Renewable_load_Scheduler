import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent))
from db import get_connection, init_db

st.set_page_config(
    page_title="Field Engineer Event Logger",
    page_icon="📲",
    layout="centered"
)

st.title("📲 Field Engineer Event Logger")
st.caption("Low-friction offline log capture for plant operators and facility engineers.")

init_db()

# Load available load options
conn = get_connection()
cursor = conn.cursor()
cursor.execute("SELECT load_id, name FROM loads ORDER BY load_id;")
loads_rows = cursor.fetchall()
load_options = {f"{r['name']} ({r['load_id']})": r['load_id'] for r in loads_rows}
conn.close()

with st.form("field_event_form", clear_on_submit=True):
    st.subheader("Log Operational Event")
    
    engineer_id = st.text_input("Engineer ID / Name", value="ENG-01")
    load_choice = st.selectbox("Equipment Load", options=list(load_options.keys()))
    event_type = st.selectbox("Event Type", ["override", "complaint", "deviation", "note"])
    note = st.text_area("Note / Reason for Event", placeholder="e.g., Curing oven delayed 30 mins due to raw material staging.")
    
    submitted = st.form_submit_button("💾 Save Field Event")
    
    if submitted:
        load_id = load_options[load_choice]
        ts_now = datetime.now().isoformat()
        
        conn = get_connection()
        c = conn.cursor()
        c.execute("""
            INSERT INTO field_log (timestamp, engineer_id, load_id, event_type, note)
            VALUES (?, ?, ?, ?, ?)
        """, (ts_now, engineer_id, load_id, event_type, note))
        conn.commit()
        conn.close()
        
        st.success(f"✅ Field event logged successfully for {load_id} at {ts_now[:19]}!")

st.write("---")
st.subheader("📋 Recent Field Log Entries")

conn = get_connection()
df_logs = pd.read_sql_query("SELECT timestamp, engineer_id, load_id, event_type, note FROM field_log ORDER BY timestamp DESC LIMIT 20;", conn)
conn.close()

if not df_logs.empty:
    st.dataframe(df_logs, use_container_width=True)
else:
    st.info("No field log entries recorded yet.")
