import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from data_generator import populate_database
from scheduler.mpc_controller import MPCRollingHorizonController
from forecast.uncertainty import calculate_calibrated_uncertainty_bands, evaluate_empirical_coverage_and_pinball, fit_empirical_error_distribution
from sim.metrics import validate_hard_constraints
from db import get_connection

@pytest.fixture(autouse=True)
def setup_db():
    start_date = datetime(2026, 6, 1, 0, 0)
    populate_database(start_date, days=3)

def test_closed_loop_mpc_controller():
    start_date = datetime(2026, 6, 1, 0, 0)
    
    mpc_ctrl = MPCRollingHorizonController()
    mpc_res = mpc_ctrl.run_closed_loop_mpc(start_date, run_id="test_mpc_run")
    
    assert mpc_res['run_id'] == "test_mpc_run"
    assert mpc_res['total_bill'] > 0.0
    assert mpc_res['max_peak_grid_kw'] > 0.0
    assert 0.0 <= mpc_res['self_consumption_pct'] <= 100.0
    assert len(mpc_res['history']) == 24
    
    # Validate hard constraints on MPC schedule
    conn = get_connection()
    df_sched = pd.read_sql_query("SELECT * FROM schedule WHERE run_id = 'test_mpc_run';", conn)
    loads_df = pd.read_sql_query("SELECT * FROM loads;", conn)
    conn.close()
    
    val = validate_hard_constraints(df_sched, loads_df)
    assert val['zero_violations'], f"MPC caused hard constraint violations: {val['violations']}"

def test_empirical_residual_calibration_and_coverage():
    np.random.seed(42)
    y_true = np.array([100, 200, 300, 400, 500, 400, 300, 200, 100, 0], dtype=float)
    y_pred = y_true + np.random.normal(0, 10, size=len(y_true))
    
    params = fit_empirical_error_distribution(y_true, y_pred)
    assert 'mean_bias' in params
    assert 'std_residual' in params
    assert 'q10_offset' in params
    
    p50_series = pd.Series(y_pred)
    bands = calculate_calibrated_uncertainty_bands(p50_series, y_true, y_pred)
    
    cov_eval = evaluate_empirical_coverage_and_pinball(
        y_true, bands['p10'].values, bands['p50'].values, bands['p90'].values
    )
    
    assert 'empirical_coverage_pct' in cov_eval
    assert 'pinball_loss_q50' in cov_eval
    assert cov_eval['empirical_coverage_pct'] >= 50.0 # High empirical coverage
