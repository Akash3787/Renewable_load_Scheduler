import pytest
from datetime import datetime
from data_generator import populate_database
from scheduler.baseline import BaselineScheduler
from sim.backtest_engine import BacktestEngine

def test_baseline_scheduler_and_backtest():
    start_date = datetime(2026, 6, 1, 0, 0)
    populate_database(start_date, days=3)
    
    scheduler = BaselineScheduler()
    df_sched = scheduler.schedule_day(start_date, run_id="test_baseline")
    
    assert not df_sched.empty
    assert 'scheduled_start' in df_sched.columns
    assert 'power_kw' in df_sched.columns
    
    engine = BacktestEngine()
    results = engine.run_backtest(run_id="test_baseline")
    
    assert results['run_id'] == "test_baseline"
    assert results['total_load_kwh'] > 0.0
    assert results['max_peak_grid_kw'] > 0.0
    assert results['total_bill'] > 0.0
    assert 0.0 <= results['self_consumption_pct'] <= 100.0
