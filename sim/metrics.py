import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional

from forecast.uncertainty import evaluate_empirical_coverage_and_pinball

def calculate_forecast_errors(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """Calculate Mean Absolute Error (MAE) and Root Mean Squared Error (RMSE)."""
    mae = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    return {'mae': round(mae, 2), 'rmse': round(rmse, 2)}

def evaluate_schedule_performance(
    baseline_res: Dict[str, Any],
    optimizer_res: Dict[str, Any],
    oracle_res: Dict[str, Any],
    mpc_res: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Compare Baseline vs Day-Ahead Optimizer vs MPC Rolling Horizon vs Oracle metrics side by side.
    Computes savings delta, self-consumption delta, peak demand reduction %, and regret vs oracle.
    """
    b_bill = baseline_res['total_bill']
    o_bill = optimizer_res['total_bill']
    r_bill = oracle_res['total_bill']
    m_bill = mpc_res['total_bill'] if mpc_res else o_bill
    
    b_peak = baseline_res['max_peak_grid_kw']
    o_peak = optimizer_res['max_peak_grid_kw']
    r_peak = oracle_res['max_peak_grid_kw']
    m_peak = mpc_res['max_peak_grid_kw'] if mpc_res else o_peak
    
    b_self = baseline_res['self_consumption_pct']
    o_self = optimizer_res['self_consumption_pct']
    r_self = oracle_res['self_consumption_pct']
    m_self = mpc_res['self_consumption_pct'] if mpc_res else o_self
    
    savings_dollars = b_bill - m_bill
    savings_pct = (savings_dollars / b_bill * 100.0) if b_bill > 0 else 0.0
    
    peak_reduction_kw = b_peak - m_peak
    peak_reduction_pct = (peak_reduction_kw / b_peak * 100.0) if b_peak > 0 else 0.0
    
    regret = m_bill - r_bill
    
    return {
        'baseline_bill': b_bill,
        'optimizer_bill': o_bill,
        'mpc_bill': m_bill,
        'oracle_bill': r_bill,
        'bill_savings_amount': round(savings_dollars, 2),
        'bill_savings_pct': round(savings_pct, 2),
        
        'baseline_peak_kw': b_peak,
        'optimizer_peak_kw': o_peak,
        'mpc_peak_kw': m_peak,
        'oracle_peak_kw': r_peak,
        'peak_reduction_kw': round(peak_reduction_kw, 2),
        'peak_reduction_pct': round(peak_reduction_pct, 2),
        
        'baseline_self_consumption_pct': b_self,
        'optimizer_self_consumption_pct': o_self,
        'mpc_self_consumption_pct': m_self,
        'oracle_self_consumption_pct': r_self,
        'self_consumption_delta_pct': round(m_self - b_self, 2),
        
        'regret_vs_oracle': round(regret, 2)
    }

def validate_hard_constraints(
    df_sched: pd.DataFrame,
    loads_df: pd.DataFrame
) -> Dict[str, Any]:
    """
    Check if any flexible load missed deadline or if curtailable load violated comfort band.
    Returns zero_violations boolean gate.
    """
    violations = []
    
    for _, load in loads_df.iterrows():
        load_id = load['load_id']
        ltype = load['load_type']
        
        load_entries = df_sched[df_sched['load_id'] == load_id]
        
        if ltype == 'flexible':
            req_duration_h = int(load['duration_min'] / 60)
            act_duration_h = len(load_entries)
            
            if act_duration_h < req_duration_h:
                violations.append(f"Flexible load {load_id} ran for {act_duration_h}h instead of required {req_duration_h}h")
                
            deadline_str = load['deadline']
            deadline_h = int(deadline_str.split(':')[0])
            
            for _, entry in load_entries.iterrows():
                scheduled_h = int(entry['scheduled_start'].split('T')[1].split(':')[0])
                if scheduled_h > deadline_h:
                    violations.append(f"Flexible load {load_id} violated deadline ({scheduled_h}:00 > {deadline_h}:00)")
                    
        elif ltype == 'curtailable':
            pk = float(load['power_kw'])
            c_max = float(load['comfort_band_kw'])
            min_allowed_kw = pk - c_max
            
            for _, entry in load_entries.iterrows():
                power_kw = float(entry['power_kw'])
                if power_kw < (min_allowed_kw - 0.001):
                    violations.append(f"Curtailable load {load_id} power ({power_kw}kW) below comfort band min ({min_allowed_kw}kW)")
                    
    return {
        'zero_violations': len(violations) == 0,
        'violation_count': len(violations),
        'violations': violations
    }
