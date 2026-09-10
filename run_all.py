#!/usr/bin/env python3
import sys
from datetime import datetime
import pandas as pd
import numpy as np

from db import init_db, get_connection
from data_generator import populate_database
from scheduler.baseline import BaselineScheduler
from scheduler.optimizer import MILPScheduler
from scheduler.mpc_controller import MPCRollingHorizonController
from sim.backtest_engine import BacktestEngine
from sim.metrics import evaluate_schedule_performance, validate_hard_constraints
from forecast.uncertainty import calculate_calibrated_uncertainty_bands, evaluate_empirical_coverage_and_pinball

def main():
    print("=" * 75)
    print(" ⚡ RENEWABLE-AWARE INDUSTRIAL LOAD SCHEDULER — REVIEW 2 BENCHMARK RUN")
    print("=" * 75)
    
    start_date = datetime(2026, 6, 1, 0, 0)
    
    print("\n1. Initializing database, real generation profiles, and operator field logs...")
    populate_database(start_date, days=7)
    
    print("\n2. Executing Business-as-Usual (BAU) Baseline Scheduler...")
    b_scheduler = BaselineScheduler()
    df_b = b_scheduler.schedule_day(start_date, run_id="run_baseline")
    
    print("\n3. Executing Day-Ahead MILP Optimizer (PuLP / CBC)...")
    opt_scheduler = MILPScheduler()
    df_o, bess_o = opt_scheduler.schedule_day(start_date, run_id="run_optimizer")
    
    print("\n4. Executing Closed-Loop MPC Rolling Horizon Controller (Receding Horizon)...")
    mpc_controller = MPCRollingHorizonController()
    mpc_res = mpc_controller.run_closed_loop_mpc(start_date, run_id="run_mpc")
    
    print("\n5. Executing Perfect-Foresight Oracle Scheduler (Upper Bound)...")
    df_r, bess_r = opt_scheduler.schedule_day(start_date, run_id="run_oracle", use_actuals_oracle=True)
    
    print("\n6. Running Backtest Engine against Ground Truth Generation Actuals...")
    engine = BacktestEngine()
    b_res = engine.run_backtest("run_baseline")
    o_res = engine.run_backtest("run_optimizer", bess_actions=bess_o)
    r_res = engine.run_backtest("run_oracle", bess_actions=bess_r)
    
    metrics = evaluate_schedule_performance(b_res, o_res, r_res, mpc_res=mpc_res)
    
    # Calculate Forecast Coverage & Pinball Calibration
    ts_strings = [(start_date + pd.Timedelta(hours=h)).isoformat() for h in range(24)]
    conn = get_connection()
    df_f = pd.read_sql_query("SELECT target_timestamp, pv_kw_p50 FROM generation_forecast WHERE target_timestamp IN ({})".format(','.join('?'*24)), conn, params=ts_strings).drop_duplicates(subset=['target_timestamp'])
    df_a = pd.read_sql_query("SELECT timestamp, pv_kw_actual FROM generation_actual WHERE timestamp IN ({})".format(','.join('?'*24)), conn, params=ts_strings)
    conn.close()
    
    bands = calculate_calibrated_uncertainty_bands(df_f['pv_kw_p50'])
    cov_eval = evaluate_empirical_coverage_and_pinball(
        df_a['pv_kw_actual'].values,
        bands['p10'].values,
        bands['p50'].values,
        bands['p90'].values
    )
    
    print("\n" + "=" * 75)
    print(" RESULTS COMPARISON SUMMARY (REVIEW 2 EVALUATION)")
    print("=" * 75)
    print(f" Baseline Total Bill:                ₹{metrics['baseline_bill']:,.2f}")
    print(f" Day-Ahead MILP Bill:                ₹{metrics['optimizer_bill']:,.2f}")
    print(f" Closed-Loop MPC Total Bill:         ₹{metrics['mpc_bill']:,.2f}")
    print(f" Oracle (Perfect Foresight) Bill:     ₹{metrics['oracle_bill']:,.2f}")
    print(f" Net Bill Savings (MPC vs Baseline): ₹{metrics['bill_savings_amount']:,.2f} ({metrics['bill_savings_pct']}% reduction)")
    print("-" * 75)
    print(f" Baseline Peak Grid Demand:           {metrics['baseline_peak_kw']:.2f} kW")
    print(f" Closed-Loop MPC Peak Grid Demand:    {metrics['mpc_peak_kw']:.2f} kW")
    print(f" Peak Demand Cut:                     {metrics['peak_reduction_kw']:.2f} kW ({metrics['peak_reduction_pct']}% reduction)")
    print("-" * 75)
    print(f" Baseline Renewable Self-Cons:        {metrics['baseline_self_consumption_pct']:.2f}%")
    print(f" MPC Renewable Self-Cons:             {metrics['mpc_self_consumption_pct']:.2f}% (+{metrics['self_consumption_delta_pct']}%)")
    print(f" Regret vs Perfect Oracle:            ₹{metrics['regret_vs_oracle']:,.2f}")
    print("=" * 75)
    print(" EMPIRICAL FORECAST CALIBRATION & COVERAGE METRICS")
    print("=" * 75)
    print(f" Empirical P10-P90 Coverage:         {cov_eval['empirical_coverage_pct']}% (Target: 80.0%)")
    print(f" Pinball Loss (Median q=0.50):        {cov_eval['pinball_loss_q50']}")
    print(f" Pinball Loss (Upper q=0.90):         {cov_eval['pinball_loss_q90']}")
    print("=" * 75)
    
    # Hard constraint verification
    conn = get_connection()
    df_mpc_sched = pd.read_sql_query("SELECT * FROM schedule WHERE run_id = 'run_mpc';", conn)
    loads_df = pd.read_sql_query("SELECT * FROM loads;", conn)
    conn.close()
    
    val = validate_hard_constraints(df_mpc_sched, loads_df)
    if val['zero_violations']:
        print(" SUCCESS: ZERO HARD CONSTRAINT VIOLATIONS ENFORCED UNDER CLOSED-LOOP MPC!")
    else:
        print(f" WARNING: {val['violation_count']} VIOLATIONS DETECTED!")
        
    print("=" * 75)
    print(" Benchmark execution complete. Launch Dashboard with:")
    print(" streamlit run app/dashboard.py")

if __name__ == "__main__":
    main()
