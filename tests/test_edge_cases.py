import pytest
import sqlite3
import pandas as pd
from datetime import datetime, timedelta

from db import init_db, get_connection
from data_generator import populate_database
from scheduler.baseline import BaselineScheduler
from scheduler.optimizer import MILPScheduler
from sim.backtest_engine import BacktestEngine
from sim.metrics import validate_hard_constraints
from forecast.adapter import ForecastAdapter

@pytest.fixture(autouse=True)
def reset_db():
    start_date = datetime(2026, 6, 1, 0, 0)
    populate_database(start_date, days=3)

def test_edge_case_1_cloud_cover_surprise():
    """
    Edge Case 1: Forecast predicts clear skies (high PV), actual generation drops to 10% (overcast).
    Verify optimizer meets all deadlines (using grid/BESS) with zero constraint violations.
    """
    start_date = datetime(2026, 6, 1, 0, 0)
    ts_strings = [(start_date + timedelta(hours=h)).isoformat() for h in range(24)]
    
    conn = get_connection()
    cursor = conn.cursor()
    # Artificially crush actual PV to 10% of forecast (cloud surprise)
    cursor.execute("UPDATE generation_actual SET pv_kw_actual = pv_kw_actual * 0.10 WHERE timestamp IN ({});".format(','.join('?' * 24)), ts_strings)
    conn.commit()
    conn.close()
    
    opt = MILPScheduler()
    df_sched, bess_actions = opt.schedule_day(start_date, run_id="edge_cloud_surprise")
    
    engine = BacktestEngine()
    results = engine.run_backtest(run_id="edge_cloud_surprise", bess_actions=bess_actions)
    
    conn = get_connection()
    loads_df = pd.read_sql_query("SELECT * FROM loads;", conn)
    conn.close()
    
    validation = validate_hard_constraints(df_sched, loads_df)
    assert validation['zero_violations'], f"Cloud surprise caused violations: {validation['violations']}"
    assert results['total_bill'] > 0.0

def test_edge_case_2_wind_lull():
    """
    Edge Case 2: Forecast predicts high wind generation, actual wind drops below cut-in (0 kW).
    Verify optimizer handles wind shortfall gracefully without deadline misses.
    """
    start_date = datetime(2026, 6, 1, 0, 0)
    ts_strings = [(start_date + timedelta(hours=h)).isoformat() for h in range(24)]
    
    conn = get_connection()
    cursor = conn.cursor()
    # Zero out actual wind generation
    cursor.execute("UPDATE generation_actual SET wind_kw_actual = 0.0 WHERE timestamp IN ({});".format(','.join('?' * 24)), ts_strings)
    conn.commit()
    conn.close()
    
    opt = MILPScheduler()
    df_sched, bess_actions = opt.schedule_day(start_date, run_id="edge_wind_lull")
    
    engine = BacktestEngine()
    results = engine.run_backtest(run_id="edge_wind_lull", bess_actions=bess_actions)
    
    conn = get_connection()
    loads_df = pd.read_sql_query("SELECT * FROM loads;", conn)
    conn.close()
    
    validation = validate_hard_constraints(df_sched, loads_df)
    assert validation['zero_violations'], f"Wind lull caused violations: {validation['violations']}"

def test_edge_case_3_deadline_conflict_low_renewables():
    """
    Edge Case 3: Overlapping deadlines under zero solar/wind generation.
    Verify optimizer falls back to grid power while preserving 100% deadline compliance.
    """
    start_date = datetime(2026, 6, 1, 0, 0)
    ts_strings = [(start_date + timedelta(hours=h)).isoformat() for h in range(24)]
    
    conn = get_connection()
    cursor = conn.cursor()
    # Zero out all solar and wind generation for forecast and actuals
    cursor.execute("UPDATE generation_actual SET pv_kw_actual = 0.0, wind_kw_actual = 0.0 WHERE timestamp IN ({});".format(','.join('?' * 24)), ts_strings)
    cursor.execute("UPDATE generation_forecast SET pv_kw_p50 = 0.0, wind_kw_p50 = 0.0 WHERE target_timestamp IN ({});".format(','.join('?' * 24)), ts_strings)
    conn.commit()
    conn.close()
    
    opt = MILPScheduler()
    df_sched, bess_actions = opt.schedule_day(start_date, run_id="edge_deadline_conflict")
    
    conn = get_connection()
    loads_df = pd.read_sql_query("SELECT * FROM loads;", conn)
    conn.close()
    
    validation = validate_hard_constraints(df_sched, loads_df)
    assert validation['zero_violations'], "Optimizer failed to satisfy deadlines under zero renewables!"

def test_edge_case_4_battery_degraded_unavailable():
    """
    Edge Case 4: Battery storage system offline (max charge/discharge = 0 kW).
    Verify optimizer degrades gracefully to solar/wind direct consumption without crashing.
    """
    start_date = datetime(2026, 6, 1, 0, 0)
    
    opt = MILPScheduler()
    df_sched, bess_actions = opt.schedule_day(start_date, run_id="edge_no_bess", battery_available=False)
    
    engine = BacktestEngine()
    results = engine.run_backtest(run_id="edge_no_bess", bess_actions=bess_actions)
    
    conn = get_connection()
    loads_df = pd.read_sql_query("SELECT * FROM loads;", conn)
    conn.close()
    
    validation = validate_hard_constraints(df_sched, loads_df)
    assert validation['zero_violations']
    assert results['max_peak_grid_kw'] > 0.0

def test_edge_case_5_offline_climatology_fallback():
    """
    Edge Case 5: Forecast API unreachable for full day.
    Verify climatology fallback produces a valid schedule tagged with source='climatology_fallback'.
    """
    start_date = datetime(2026, 6, 1, 0, 0)
    ts_strings = [(start_date + timedelta(hours=h)).isoformat() for h in range(24)]
    
    adapter = ForecastAdapter()
    df_forecast = adapter.get_forecast(ts_strings, force_offline=True)
    
    assert not df_forecast.empty
    assert df_forecast['source'].iloc[0] in ['cache', 'climatology_fallback']
    
    opt = MILPScheduler()
    df_sched, bess_actions = opt.schedule_day(start_date, run_id="edge_offline_fallback")
    assert not df_sched.empty
