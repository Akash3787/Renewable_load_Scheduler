import pytest
from datetime import datetime
import pandas as pd

from data_generator import populate_database
from scheduler.baseline import BaselineScheduler
from scheduler.optimizer import MILPScheduler
from sim.backtest_engine import BacktestEngine
from sim.metrics import evaluate_schedule_performance, validate_hard_constraints

def test_milp_optimizer_vs_baseline_vs_oracle():
    start_date = datetime(2026, 6, 1, 0, 0)
    populate_database(start_date, days=3)
    
    # 1. Baseline
    b_sched = BaselineScheduler()
    df_b = b_sched.schedule_day(start_date, run_id="baseline_run")
    
    # 2. MILP Optimizer
    opt = MILPScheduler()
    df_o, bess_o = opt.schedule_day(start_date, run_id="opt_run")
    
    # 3. Oracle (Perfect Foresight)
    df_r, bess_r = opt.schedule_day(start_date, run_id="oracle_run", use_actuals_oracle=True)
    
    engine = BacktestEngine()
    b_res = engine.run_backtest("baseline_run")
    o_res = engine.run_backtest("opt_run", bess_actions=bess_o)
    r_res = engine.run_backtest("oracle_run", bess_actions=bess_r)
    
    metrics = evaluate_schedule_performance(b_res, o_res, r_res)
    
    # Validate MILP beats baseline in cost and/or peak demand
    assert metrics['optimizer_bill'] <= metrics['baseline_bill']
    assert metrics['optimizer_peak_kw'] <= metrics['baseline_peak_kw']
    assert metrics['bill_savings_amount'] >= 0.0
    assert metrics['regret_vs_oracle'] >= 0.0
