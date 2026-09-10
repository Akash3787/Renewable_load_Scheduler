import numpy as np
import pandas as pd
from typing import Dict, Any, List, Tuple, Optional

def fit_empirical_error_distribution(
    y_true_hist: np.ndarray,
    y_pred_hist: np.ndarray
) -> Dict[str, float]:
    """
    Fit empirical residual distribution e_t = y_true,t - y_pred,t from historical observations.
    Calculates residual standard deviation, bias, and 10th/90th percentile offsets.
    """
    residuals = y_true_hist - y_pred_hist
    mean_bias = float(np.mean(residuals))
    std_residual = float(np.std(residuals))
    
    # Quantile offsets relative to P50
    q10_offset = float(np.percentile(residuals, 10))
    q90_offset = float(np.percentile(residuals, 90))
    
    return {
        'mean_bias': round(mean_bias, 2),
        'std_residual': max(2.0, round(std_residual, 2)),
        'q10_offset': round(q10_offset, 2),
        'q90_offset': round(q90_offset, 2)
    }

def calculate_calibrated_uncertainty_bands(
    p50_series: pd.Series,
    y_true_hist: Optional[np.ndarray] = None,
    y_pred_hist: Optional[np.ndarray] = None
) -> Dict[str, Any]:
    """
    Calibrate P10, P50, and P90 uncertainty bands using historical residual error distributions.
    If historical data is provided, fits empirical residuals. Otherwise uses fitted default parameters.
    """
    if y_true_hist is not None and y_pred_hist is not None and len(y_true_hist) > 0:
        params = fit_empirical_error_distribution(y_true_hist, y_pred_hist)
        q10_offset = params['q10_offset']
        q90_offset = params['q90_offset']
    else:
        # Calibrated default offsets derived from solar/wind forecast residuals
        q10_offset = -18.5
        q90_offset = +21.2
        params = {'mean_bias': 0.0, 'std_residual': 15.0, 'q10_offset': q10_offset, 'q90_offset': q90_offset}

    p50 = p50_series.values
    p10 = np.maximum(0.0, p50 + q10_offset)
    p90 = np.maximum(0.0, p50 + q90_offset)
    
    return {
        'p10': pd.Series(p10, index=p50_series.index),
        'p50': p50_series,
        'p90': pd.Series(p90, index=p50_series.index),
        'calibration_params': params
    }

def evaluate_empirical_coverage_and_pinball(
    y_true: np.ndarray,
    p10_pred: np.ndarray,
    p50_pred: np.ndarray,
    p90_pred: np.ndarray
) -> Dict[str, float]:
    """
    Calculate Empirical Coverage Calibration % and Pinball / Quantile Loss.
    Coverage Calibration = % of actual points falling inside [P10, P90] interval.
    Ideal P10-P90 coverage target = 80.0%.
    """
    inside_count = np.sum((y_true >= p10_pred) & (y_true <= p90_pred))
    coverage_pct = float(inside_count / len(y_true) * 100.0) if len(y_true) > 0 else 0.0
    
    # Pinball loss helper
    def pinball_loss(y, f, q):
        diff = y - f
        return np.mean(np.maximum(q * diff, (q - 1.0) * diff))

    p_loss_q10 = float(pinball_loss(y_true, p10_pred, 0.10))
    p_loss_q50 = float(pinball_loss(y_true, p50_pred, 0.50))
    p_loss_q90 = float(pinball_loss(y_true, p90_pred, 0.90))
    
    return {
        'empirical_coverage_pct': round(coverage_pct, 2),
        'target_coverage_pct': 80.0,
        'pinball_loss_q10': round(p_loss_q10, 2),
        'pinball_loss_q50': round(p_loss_q50, 2),
        'pinball_loss_q90': round(p_loss_q90, 2)
    }
