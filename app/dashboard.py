import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import yaml
from pathlib import Path

# Add project root to sys.path
import sys
sys.path.append(str(Path(__file__).parent.parent))

from db import get_connection, init_db
from data_generator import populate_database
from scheduler.baseline import BaselineScheduler
from scheduler.optimizer import MILPScheduler
from sim.backtest_engine import BacktestEngine
from sim.metrics import evaluate_schedule_performance, validate_hard_constraints

st.set_page_config(
    page_title="Renewable-Aware Industrial Load Scheduler",
    page_icon="⚡",
    layout="wide"
)

# Custom CSS for modern dark-theme glassmorphism styling
st.markdown("""
<style>
    .main {
        background-color: #0f172a;
        color: #f8fafc;
    }
    .metric-card {
        background: rgba(30, 41, 59, 0.7);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
        padding: 18px;
        text-align: center;
        backdrop-filter: blur(10px);
    }
    .metric-value {
        font-size: 2rem;
        font-weight: 700;
        color: #38bdf8;
    }
    .metric-label {
        font-size: 0.9rem;
        color: #94a3b8;
    }
</style>
""", unsafe_allow_html=True)

st.title("⚡ Renewable-Aware Industrial Load Scheduler")
st.caption("Co-optimizing industrial demand, flexible load shifting, and BESS storage with forecasted solar & wind generation.")

# Sidebar Controls
st.sidebar.header("🕹️ Control Panel")
start_date_val = st.sidebar.date_input("Simulation Start Date", datetime(2026, 6, 1))
start_dt = datetime.combine(start_date_val, datetime.min.time())

regenerate_data = st.sidebar.button("🔄 Regenerate Multi-Week Dataset")
if regenerate_data:
    populate_database(start_dt, days=7)
    st.sidebar.success("Database updated with new weather & generation data!")

# Initialize DB check
init_db()

# Run Schedules & Backtests
@st.cache_data(ttl=60)
def compute_all_schedules(s_dt):
    # Ensure data exists for date
    populate_database(s_dt, days=3)
    
    # 1. Baseline
    b_sched = BaselineScheduler()
    df_b = b_sched.schedule_day(s_dt, run_id="dash_baseline")
    
    # 2. MILP Optimizer
    opt = MILPScheduler()
    df_o, bess_o = opt.schedule_day(s_dt, run_id="dash_opt")
    
    # 3. Oracle
    df_r, bess_r = opt.schedule_day(s_dt, run_id="dash_oracle", use_actuals_oracle=True)
    
    engine = BacktestEngine()
    b_res = engine.run_backtest("dash_baseline")
    o_res = engine.run_backtest("dash_opt", bess_actions=bess_o)
    r_res = engine.run_backtest("dash_oracle", bess_actions=bess_r)
    
    metrics = evaluate_schedule_performance(b_res, o_res, r_res)
    return b_res, o_res, r_res, metrics, df_o

b_res, o_res, r_res, metrics, df_o = compute_all_schedules(start_dt)

# KPI Summary Header Cards
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Total Bill Savings</div>
        <div class="metric-value">₹{metrics['bill_savings_amount']:,.0f}</div>
        <div style="color: #4ade80; font-weight:600;">↓ {metrics['bill_savings_pct']}% vs Baseline</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Peak Demand Reduction</div>
        <div class="metric-value">{metrics['peak_reduction_kw']} kW</div>
        <div style="color: #4ade80; font-weight:600;">↓ {metrics['peak_reduction_pct']}% Peak Cut</div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Renewable Self-Consumption</div>
        <div class="metric-value">{o_res['self_consumption_pct']}%</div>
        <div style="color: #38bdf8; font-weight:600;">+{metrics['self_consumption_delta_pct']}% Increase</div>
    </div>
    """, unsafe_allow_html=True)

with col4:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Regret vs Oracle</div>
        <div class="metric-value">₹{metrics['regret_vs_oracle']:,.0f}</div>
        <div style="color: #f59e0b; font-weight:600;">Near-Optimal Bound</div>
    </div>
    """, unsafe_allow_html=True)

st.write("---")

# Tabbed Navigation
tab1, tab2, tab3, tab4 = st.tabs(["📊 Schedule & Power Comparison", "📈 Generation Forecast & Confidence Bands", "⚖️ Baseline vs Optimizer vs Oracle", "📋 Field Logs & Hard Constraints"])

with tab1:
    st.subheader("24-Hour Factory Power Dispatch & Storage Dynamics")
    
    df_opt_hist = o_res['history']
    df_base_hist = b_res['history']
    
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=("Grid Power Import & Demand Profile (kW)", "BESS State of Charge (SOC kWh) & Battery Dispatch"),
        vertical_spacing=0.12
    )
    
    hours = [i for i in range(24)]
    
    # Baseline Grid Draw
    fig.add_trace(go.Scatter(
        x=hours, y=df_base_hist['grid_import_kw'],
        name="Baseline Grid Draw (kW)", line=dict(color="#ef4444", width=3, dash='dash')
    ), row=1, col=1)
    
    # Optimizer Grid Draw
    fig.add_trace(go.Scatter(
        x=hours, y=df_opt_hist['grid_import_kw'],
        name="Optimized Grid Draw (kW)", line=dict(color="#10b981", width=3)
    ), row=1, col=1)
    
    # Total Renewables
    fig.add_trace(go.Scatter(
        x=hours, y=df_opt_hist['ren_gen_kw'],
        name="Actual Renewables (PV+Wind kW)", fill='tozeroy',
        line=dict(color="#f59e0b", width=1.5), opacity=0.3
    ), row=1, col=1)
    
    # BESS SOC
    fig.add_trace(go.Scatter(
        x=hours, y=df_opt_hist['bess_soc_kwh'],
        name="BESS SOC (kWh)", line=dict(color="#38bdf8", width=3)
    ), row=2, col=1)
    
    # Battery Charge/Discharge Bars
    fig.add_trace(go.Bar(
        x=hours, y=df_opt_hist['bess_charge_kw'],
        name="BESS Charge (kW)", marker_color="#06b6d4"
    ), row=2, col=1)
    
    fig.add_trace(go.Bar(
        x=hours, y=-df_opt_hist['bess_discharge_kw'],
        name="BESS Discharge (kW)", marker_color="#8b5cf6"
    ), row=2, col=1)
    
    fig.update_layout(template="plotly_dark", height=600, barmode="relative")
    fig.update_xaxes(title_text="Hour of Day", row=2, col=1)
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("Day-Ahead Renewable Forecast with P10–P90 Uncertainty Bands")
    
    conn = get_connection()
    ts_strings = [(start_dt + timedelta(hours=h)).isoformat() for h in range(24)]
    query = "SELECT target_timestamp, pv_kw_p50, pv_kw_p10, pv_kw_p90, wind_kw_p50, wind_kw_p10, wind_kw_p90 FROM generation_forecast WHERE target_timestamp IN ({}) ORDER BY forecast_run_time DESC".format(','.join('?'*24))
    df_f = pd.read_sql_query(query, conn, params=ts_strings).drop_duplicates(subset=['target_timestamp'])
    query_a = "SELECT timestamp, pv_kw_actual, wind_kw_actual FROM generation_actual WHERE timestamp IN ({})".format(','.join('?'*24))
    df_a = pd.read_sql_query(query_a, conn, params=ts_strings)
    conn.close()
    
    fig_f = go.Figure()
    
    # PV P10-P90 Confidence Band
    fig_f.add_trace(go.Scatter(
        x=hours, y=df_f['pv_kw_p90'], name="PV P90", line=dict(width=0), showlegend=False
    ))
    fig_f.add_trace(go.Scatter(
        x=hours, y=df_f['pv_kw_p10'], name="PV P10-P90 Band", fill='tonexty',
        fillcolor='rgba(245, 158, 11, 0.2)', line=dict(width=0)
    ))
    fig_f.add_trace(go.Scatter(
        x=hours, y=df_f['pv_kw_p50'], name="PV Forecast (P50)", line=dict(color="#f59e0b", width=2.5)
    ))
    fig_f.add_trace(go.Scatter(
        x=hours, y=df_a['pv_kw_actual'], name="PV Ground Truth Actual", line=dict(color="#eab308", width=2, dash='dot')
    ))
    
    # Wind Forecast
    fig_f.add_trace(go.Scatter(
        x=hours, y=df_f['wind_kw_p50'], name="Wind Forecast (P50)", line=dict(color="#3b82f6", width=2.5)
    ))
    fig_f.add_trace(go.Scatter(
        x=hours, y=df_a['wind_kw_actual'], name="Wind Ground Truth Actual", line=dict(color="#60a5fa", width=2, dash='dot')
    ))
    
    fig_f.update_layout(template="plotly_dark", height=450, title="Solar PV & Wind Power Forecast vs Actuals (kW)")
    st.plotly_chart(fig_f, use_container_width=True)

with tab3:
    st.subheader("Performance Comparison Matrix")
    
    comp_df = pd.DataFrame({
        "Metric": ["Total Electricity Bill (₹)", "Peak Grid Demand (kW)", "Renewable Self-Consumption (%)", "Energy Charge Cost (₹)", "Demand Charge Cost (₹)"],
        "Baseline (BAU)": [f"₹{b_res['total_bill']:,.2f}", f"{b_res['max_peak_grid_kw']} kW", f"{b_res['self_consumption_pct']}%", f"₹{b_res['energy_charge_cost']:,.2f}", f"₹{b_res['demand_charge_cost']:,.2f}"],
        "MILP Optimizer": [f"₹{o_res['total_bill']:,.2f}", f"{o_res['max_peak_grid_kw']} kW", f"{o_res['self_consumption_pct']}%", f"₹{o_res['energy_charge_cost']:,.2f}", f"₹{o_res['demand_charge_cost']:,.2f}"],
        "Oracle (Upper Bound)": [f"₹{r_res['total_bill']:,.2f}", f"{r_res['max_peak_grid_kw']} kW", f"{r_res['self_consumption_pct']}%", f"₹{r_res['energy_charge_cost']:,.2f}", f"₹{r_res['demand_charge_cost']:,.2f}"]
    })
    
    st.table(comp_df)

with tab4:
    st.subheader("Field Logged Events & Hard Constraint Verification")
    
    conn = get_connection()
    df_logs = pd.read_sql_query("SELECT * FROM field_log ORDER BY timestamp DESC LIMIT 50;", conn)
    loads_df = pd.read_sql_query("SELECT * FROM loads;", conn)
    conn.close()
    
    validation = validate_hard_constraints(df_o, loads_df)
    
    if validation['zero_violations']:
        st.success("✅ **Zero Hard Constraint Violations Enforced!** All flexible deadlines and curtailable comfort bands satisfied.")
    else:
        st.error(f"⚠️ {validation['violation_count']} Constraint Violations Detected!")
        for v in validation['violations']:
            st.write(f"- {v}")
            
    st.write("#### Recent Field Engineer Logs (`field_log` table)")
    if not df_logs.empty:
        st.dataframe(df_logs, use_container_width=True)
    else:
        st.info("No field log events recorded yet. Use the Field Capture App (`app/field_capture.py`) to log overrides or complaints.")
