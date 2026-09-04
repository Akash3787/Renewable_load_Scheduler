#!/usr/bin/env python3
import sys
from datetime import datetime
import pandas as pd

from db import init_db
from data_generator import populate_database
from scheduler.baseline import BaselineScheduler
from scheduler.optimizer import MILPScheduler
from sim.backtest_engine import BacktestEngine
from sim.metrics import evaluate_schedule_performance, validate_hard_constraints

def main():
    print("=" * 70)
    print(" ⚡ RENEWABLE-AWARE INDUSTRIAL LOAD SCHEDULER — FULL BENCHMARK RUN")
    print("=" * 70)
    
    start_date = datetime(2026, 6, 1, 0, 0)
    
    print("\n1. Initializing database and generating multi-week weather & load dataset...")
    populate_database(start_date, days=7)
    
    print("\n2. Executing Business-as-Usual (BAU) Baseline Scheduler...")
    b_scheduler = BaselineScheduler()
    df_b = b_scheduler.schedule_day(start_date, run_id="run_baseline")
    
    print("\n3. Executing Renewable-Aware MILP Optimizer (PuLP / CBC)...")
    opt_scheduler = MILPScheduler()
    df_o, bess_o = opt_scheduler.schedule_day(start_date, run_id="run_optimizer")
    
    print("\n4. Executing Perfect-Foresight Oracle Scheduler (Upper Bound)...")
    df_r, bess_r = opt_scheduler.schedule_day(start_date, run_id="run_oracle", use_actuals_oracle=True)
    
    print("\n5. Running Backtest Engine against Ground Truth Generation Actuals...")
    engine = BacktestEngine()
    b_res = engine.run_backtest("run_baseline")
    o_res = engine.run_backtest("run_optimizer", bess_actions=bess_o)
    r_res = engine.run_backtest("run_oracle", bess_actions=bess_r)
    
    metrics = evaluate_schedule_performance(b_res, o_res, r_res)
    
    print("\n" + "=" * 70)
    print(" RESULTS COMPARISON SUMMARY")
    print("=" * 70)
    print(f" Baseline Total Bill:             ₹{metrics['baseline_bill']:,.2f}")
    print(f" MILP Optimizer Total Bill:        ₹{metrics['optimizer_bill']:,.2f}")
    print(f" Oracle (Perfect Foresight) Bill:  ₹{metrics['oracle_bill']:,.2f}")
    print(f" Net Bill Savings:                 ₹{metrics['bill_savings_amount']:,.2f} ({metrics['bill_savings_pct']}% reduction)")
    print("-" * 70)
    print(f" Baseline Peak Grid Demand:        {metrics['baseline_peak_kw']:.2f} kW")
    print(f" MILP Optimizer Peak Grid Demand:   {metrics['optimizer_peak_kw']:.2f} kW")
    print(f" Peak Demand Cut:                  {metrics['peak_reduction_kw']:.2f} kW ({metrics['peak_reduction_pct']}% reduction)")
    print("-" * 70)
    print(f" Baseline Renewable Self-Cons:     {metrics['baseline_self_consumption_pct']:.2f}%")
    print(f" Optimizer Renewable Self-Cons:    {metrics['optimizer_self_consumption_pct']:.2f}% (+{metrics['self_consumption_delta_pct']}%)")
    print(f" Regret vs Perfect Oracle:         ₹{metrics['regret_vs_oracle']:,.2f}")
    print("=" * 70)
    
    # Hard constraint verification
    from db import get_connection
    conn = get_connection()
    loads_df = pd.read_sql_query("SELECT * FROM loads;", conn)
    conn.close()
    
    val = validate_hard_constraints(df_o, loads_df)
    if val['zero_violations']:
        print(" SUCCESS: ZERO HARD CONSTRAINT VIOLATIONS ENFORCED!")
    else:
        print(f" WARNING: {val['violation_count']} VIOLATIONS DETECTED!")
        
    print("=" * 70)
    print(" Benchmark execution complete. Launch Dashboard with:")
    print(" streamlit run app/dashboard.py")

if __name__ == "__main__":
    main()
