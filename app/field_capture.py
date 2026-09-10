import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent))
from db import get_connection, init_db

st.set_page_config(
    page_title="Plant Operator Field Capture & Feedback Log",
    page_icon="📲",
    layout="centered"
)

st.title("📲 Plant Operator Field Capture & Feedback Portal")
st.caption("Real-world low-friction event logging and operator shift feedback tool.")

init_db()

# Load available load options
conn = get_connection()
cursor = conn.cursor()
cursor.execute("SELECT load_id, name FROM loads ORDER BY load_id;")
loads_rows = cursor.fetchall()
load_options = {f"{r['name']} ({r['load_id']})": r['load_id'] for r in loads_rows}
conn.close()

tab1, tab2 = st.tabs(["📝 Log Equipment Event", "⭐ Plant Operator Shift Survey"])

with tab1:
    with st.form("field_event_form", clear_on_submit=True):
        st.subheader("Log Operational Event / Override")
        
        engineer_id = st.text_input("Operator / Engineer ID", value="OP-SHIFT-1")
        load_choice = st.selectbox("Equipment Load", options=list(load_options.keys()))
        event_type = st.selectbox("Event Category", ["override", "complaint", "deviation", "note"])
        
        reason_cat = st.selectbox("Reason Classification", [
            "Raw Material Staging Delay",
            "Emergency Mechanical Maintenance",
            "Batch Quality Inspection",
            "Shift Changeover Adjustment",
            "Operator Comfort / Temperature Complaint"
        ])
        
        note = st.text_area("Detailed Operator Note", placeholder="e.g., Curing oven delayed 30 mins due to raw material staging in Bay 2.")
        
        submitted = st.form_submit_button("💾 Save Event to Field Log")
        
        if submitted:
            load_id = load_options[load_choice]
            ts_now = datetime.now().isoformat()
            full_note = f"[{reason_cat}] {note}"
            
            conn = get_connection()
            c = conn.cursor()
            c.execute("""
                INSERT INTO field_log (timestamp, engineer_id, load_id, event_type, note)
                VALUES (?, ?, ?, ?, ?)
            """, (ts_now, engineer_id, load_id, event_type, full_note))
            conn.commit()
            conn.close()
            
            st.success(f"✅ Event logged successfully for {load_id} at {ts_now[:19]}!")

with tab2:
    st.subheader("Operator Satisfaction & Feedback Survey")
    with st.form("operator_survey_form", clear_on_submit=True):
        op_name = st.text_input("Operator Name & Plant Section", value="R. Sharma (Curing & Heat Treat)")
        rating = st.slider("Scheduler Satisfaction Rating (1 = Poor, 5 = Excellent)", 1, 5, 5)
        disruption_logged = st.radio("Did automated load shifting disrupt process quality?", ["No disruption", "Minor delay (<15 mins)", "Major process impact"])
        feedback_text = st.text_area("Operator Experience Feedback", value="The automated oven schedule worked smoothly during the afternoon solar peak. Zero deadline impacts observed.")
        
        survey_submitted = st.form_submit_button("📩 Submit Operator Feedback")
        if survey_submitted:
            ts_now = datetime.now().isoformat()
            full_note = f"[OPERATOR SURVEY - Rating: {rating}/5 | Disruption: {disruption_logged}] {feedback_text}"
            
            conn = get_connection()
            c = conn.cursor()
            c.execute("""
                INSERT INTO field_log (timestamp, engineer_id, load_id, event_type, note)
                VALUES (?, ?, ?, ?, ?)
            """, (ts_now, op_name, "SYSTEM_FEEDBACK", "operator_survey", full_note))
            conn.commit()
            conn.close()
            st.success("Thank you! Your feedback has been logged into the plant database.")

st.write("---")
st.subheader("📋 Field Log & Survey Entries (`field_log` Table)")

conn = get_connection()
df_logs = pd.read_sql_query("SELECT timestamp, engineer_id, load_id, event_type, note FROM field_log ORDER BY timestamp DESC LIMIT 20;", conn)
conn.close()

if not df_logs.empty:
    st.dataframe(df_logs, use_container_width=True)
else:
    st.info("No field log entries recorded yet.")
