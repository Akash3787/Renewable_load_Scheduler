import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import yaml
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent))

from db import get_connection, init_db
from data_generator import populate_database
from scheduler.baseline import BaselineScheduler
from scheduler.optimizer import MILPScheduler
from scheduler.mpc_controller import MPCRollingHorizonController
from sim.backtest_engine import BacktestEngine
from sim.metrics import evaluate_schedule_performance, validate_hard_constraints
from forecast.uncertainty import evaluate_empirical_coverage_and_pinball, calculate_calibrated_uncertainty_bands

st.set_page_config(
    page_title="Renewable-Aware Industrial Load Scheduler",
    page_icon="⚡",
    layout="wide"
)

# Modern Glassmorphism Styling
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
st.caption("Co-optimizing industrial demand, flexible load shifting, and BESS storage with closed-loop MPC rolling horizon and empirical forecast calibration.")

# Sidebar Controls
st.sidebar.header("🕹️ Control Panel")
start_date_val = st.sidebar.date_input("Simulation Start Date", datetime(2026, 6, 1))
start_dt = datetime.combine(start_date_val, datetime.min.time())

enable_mpc = st.sidebar.checkbox("Enable Closed-Loop MPC Rolling Horizon", value=True)

regenerate_data = st.sidebar.button("🔄 Reload Dataset & Weather Profile")
if regenerate_data:
    populate_database(start_dt, days=7)
    st.sidebar.success("Database reloaded!")

init_db()

@st.cache_data(ttl=60)
def compute_all_schedules(s_dt):
    populate_database(s_dt, days=3)
    
    # 1. Baseline
    b_sched = BaselineScheduler()
    df_b = b_sched.schedule_day(s_dt, run_id="dash_baseline")
    
    # 2. Day-Ahead MILP Optimizer
    opt = MILPScheduler()
    df_o, bess_o = opt.schedule_day(s_dt, run_id="dash_opt")
    
    # 3. Closed-Loop MPC Rolling Horizon Controller
    mpc_ctrl = MPCRollingHorizonController()
    mpc_res = mpc_ctrl.run_closed_loop_mpc(s_dt, run_id="dash_mpc")
    
    # 4. Oracle
    df_r, bess_r = opt.schedule_day(s_dt, run_id="dash_oracle", use_actuals_oracle=True)
    
    engine = BacktestEngine()
    b_res = engine.run_backtest("dash_baseline")
    o_res = engine.run_backtest("dash_opt", bess_actions=bess_o)
    r_res = engine.run_backtest("dash_oracle", bess_actions=bess_r)
    
    metrics = evaluate_schedule_performance(b_res, o_res, r_res, mpc_res=mpc_res)
    return b_res, o_res, mpc_res, r_res, metrics

b_res, o_res, mpc_res, r_res, metrics = compute_all_schedules(start_dt)

active_res = mpc_res if enable_mpc else o_res
active_name = "MPC Rolling Horizon" if enable_mpc else "Day-Ahead MILP"

# Header Summary KPI Cards
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Total Bill Savings ({active_name})</div>
        <div class="metric-value">₹{metrics['bill_savings_amount']:,.0f}</div>
        <div style="color: #4ade80; font-weight:600;">↓ {metrics['bill_savings_pct']}% vs Baseline</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Peak Demand Cut</div>
        <div class="metric-value">{metrics['peak_reduction_kw']} kW</div>
        <div style="color: #4ade80; font-weight:600;">↓ {metrics['peak_reduction_pct']}% Peak Cut</div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Renewable Self-Consumption</div>
        <div class="metric-value">{active_res['self_consumption_pct']}%</div>
        <div style="color: #38bdf8; font-weight:600;">+{metrics['self_consumption_delta_pct']}% Increase</div>
    </div>
    """, unsafe_allow_html=True)

with col4:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Regret vs Perfect Oracle</div>
        <div class="metric-value">₹{metrics['regret_vs_oracle']:,.0f}</div>
        <div style="color: #f59e0b; font-weight:600;">Near-Optimal Bound</div>
    </div>
    """, unsafe_allow_html=True)

st.write("---")

# Main Tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Power & Storage Dispatch",
    "📈 Empirical Forecast Calibration",
    "🔄 Closed-Loop MPC vs Day-Ahead",
    "⚖️ Performance Benchmark Matrix",
    "📲 Operator Surveys & Field Logs"
])

with tab1:
    st.subheader(f"24-Hour Factory Power Dispatch ({active_name})")
    
    df_act_hist = active_res['history']
    df_base_hist = b_res['history']
    hours = list(range(24))
    
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        subplot_titles=("Grid Power Draw (kW)", "BESS State of Charge & Battery Dispatch (kW)"),
        vertical_spacing=0.12
    )
    
    fig.add_trace(go.Scatter(
        x=hours, y=df_base_hist['grid_import_kw'],
        name="Baseline Grid Draw (kW)", line=dict(color="#ef4444", width=3, dash='dash')
    ), row=1, col=1)
    
    fig.add_trace(go.Scatter(
        x=hours, y=df_act_hist['grid_import_kw'],
        name=f"{active_name} Grid Draw (kW)", line=dict(color="#10b981", width=3)
    ), row=1, col=1)
    
    fig.add_trace(go.Scatter(
        x=hours, y=df_act_hist['ren_gen_kw'],
        name="Actual Renewables (PV+Wind kW)", fill='tozeroy',
        line=dict(color="#f59e0b", width=1.5), opacity=0.3
    ), row=1, col=1)
    
    fig.add_trace(go.Scatter(
        x=hours, y=df_act_hist['bess_soc_kwh'],
        name="BESS SOC (kWh)", line=dict(color="#38bdf8", width=3)
    ), row=2, col=1)
    
    fig.add_trace(go.Bar(
        x=hours, y=df_act_hist['bess_charge_kw'],
        name="BESS Charge (kW)", marker_color="#06b6d4"
    ), row=2, col=1)
    
    fig.add_trace(go.Bar(
        x=hours, y=-df_act_hist['bess_discharge_kw'],
        name="BESS Discharge (kW)", marker_color="#8b5cf6"
    ), row=2, col=1)
    
    fig.update_layout(template="plotly_dark", height=580, barmode="relative")
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("Empirical Forecast Residual Calibration & Coverage Analysis")
    
    conn = get_connection()
    ts_strings = [(start_dt + timedelta(hours=h)).isoformat() for h in range(24)]
    df_f = pd.read_sql_query("SELECT target_timestamp, pv_kw_p50, wind_kw_p50 FROM generation_forecast WHERE target_timestamp IN ({})".format(','.join('?'*24)), conn, params=ts_strings).drop_duplicates(subset=['target_timestamp'])
    df_a = pd.read_sql_query("SELECT timestamp, pv_kw_actual, wind_kw_actual FROM generation_actual WHERE timestamp IN ({})".format(','.join('?'*24)), conn, params=ts_strings)
    conn.close()
    
    # Calibrated bands
    pv_bands = calculate_calibrated_uncertainty_bands(df_f['pv_kw_p50'])
    cov_eval = evaluate_empirical_coverage_and_pinball(
        df_a['pv_kw_actual'].values,
        pv_bands['p10'].values,
        pv_bands['p50'].values,
        pv_bands['p90'].values
    )
    
    c_col1, c_col2, c_col3 = st.columns(3)
    c_col1.metric("Empirical P10–P90 Coverage Calibration", f"{cov_eval['empirical_coverage_pct']}%", delta=f"Target: {cov_eval['target_coverage_pct']}%")
    c_col2.metric("Pinball Loss (q=0.50 Median)", f"{cov_eval['pinball_loss_q50']}")
    c_col3.metric("Pinball Loss (q=0.90 Upper)", f"{cov_eval['pinball_loss_q90']}")
    
    fig_cal = go.Figure()
    fig_cal.add_trace(go.Scatter(x=hours, y=pv_bands['p90'], name="P90 Upper Band", line=dict(width=0), showlegend=False))
    fig_cal.add_trace(go.Scatter(x=hours, y=pv_bands['p10'], name="Calibrated P10-P90 Uncertainty Band", fill='tonexty', fillcolor='rgba(56, 189, 248, 0.25)', line=dict(width=0)))
    fig_cal.add_trace(go.Scatter(x=hours, y=pv_bands['p50'], name="P50 Median Forecast", line=dict(color="#38bdf8", width=2.5)))
    fig_cal.add_trace(go.Scatter(x=hours, y=df_a['pv_kw_actual'], name="Ground Truth PV Actual", line=dict(color="#f59e0b", width=2, dash='dot')))
    
    fig_cal.update_layout(template="plotly_dark", height=420, title="Calibrated Uncertainty Bands vs Ground Truth PV Actual (kW)")
    st.plotly_chart(fig_cal, use_container_width=True)

with tab3:
    st.subheader("Closed-Loop MPC vs Day-Ahead Schedule Resilience")
    st.caption("Demonstrating how 1-hour receding horizon MPC re-optimizes BESS dispatch dynamically under real weather perturbations.")
    
    fig_cmp = go.Figure()
    fig_cmp.add_trace(go.Scatter(x=hours, y=o_res['history']['grid_import_kw'], name="Day-Ahead Schedule Grid Draw (kW)", line=dict(color="#f59e0b", width=2.5, dash='dash')))
    fig_cmp.add_trace(go.Scatter(x=hours, y=mpc_res['history']['grid_import_kw'], name="Closed-Loop MPC Grid Draw (kW)", line=dict(color="#10b981", width=3)))
    
    fig_cmp.update_layout(template="plotly_dark", height=420, title="Grid Import Power Profile: Static Day-Ahead vs Closed-Loop MPC (kW)")
    st.plotly_chart(fig_cmp, use_container_width=True)

with tab4:
    st.subheader("Performance Comparison Matrix")
    
    comp_df = pd.DataFrame({
        "Metric": ["Total Electricity Bill (₹)", "Peak Grid Demand (kW)", "Renewable Self-Consumption (%)", "Energy Charge Cost (₹)", "Demand Charge Cost (₹)"],
        "Baseline (BAU)": [f"₹{b_res['total_bill']:,.2f}", f"{b_res['max_peak_grid_kw']} kW", f"{b_res['self_consumption_pct']}%", f"₹{b_res['energy_charge_cost']:,.2f}", f"₹{b_res['demand_charge_cost']:,.2f}"],
        "Day-Ahead MILP": [f"₹{o_res['total_bill']:,.2f}", f"{o_res['max_peak_grid_kw']} kW", f"{o_res['self_consumption_pct']}%", f"₹{o_res['energy_charge_cost']:,.2f}", f"₹{o_res['demand_charge_cost']:,.2f}"],
        "Closed-Loop MPC": [f"₹{mpc_res['total_bill']:,.2f}", f"{mpc_res['max_peak_grid_kw']} kW", f"{mpc_res['self_consumption_pct']}%", f"₹{mpc_res['energy_charge_cost']:,.2f}", f"₹{mpc_res['demand_charge_cost']:,.2f}"],
        "Oracle (Upper Bound)": [f"₹{r_res['total_bill']:,.2f}", f"{r_res['max_peak_grid_kw']} kW", f"{r_res['self_consumption_pct']}%", f"₹{r_res['energy_charge_cost']:,.2f}", f"₹{r_res['demand_charge_cost']:,.2f}"]
    })
    
    st.table(comp_df)

with tab5:
    st.subheader("Plant Operator Surveys & Field Event Log Analytics")
    
    conn = get_connection()
    df_logs = pd.read_sql_query("SELECT timestamp, engineer_id, load_id, event_type, note FROM field_log ORDER BY timestamp DESC LIMIT 50;", conn)
    conn.close()
    
    st.write("#### Operator Event Log Feed (`field_log` Table)")
    if not df_logs.empty:
        st.dataframe(df_logs, use_container_width=True)
    else:
        st.info("No field log entries recorded yet.")
