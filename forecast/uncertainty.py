import numpy as np
import pandas as pd
from typing import Dict, Any, List

def calculate_forecast_uncertainty_bands(
    p50_series: pd.Series,
    relative_std: float = 0.15,
    min_std: float = 5.0,
    num_samples: int = 500
) -> Dict[str, pd.Series]:
    """
    Generate P10, P50, and P90 uncertainty bands from median (P50) predictions
    using Monte Carlo perturbation with heteroscedastic noise.
    """
    n = len(p50_series)
    samples = np.zeros((num_samples, n))
    
    np.random.seed(42)
    for i, val in enumerate(p50_series):
        std = max(min_std, val * relative_std)
        # Truncated normal distribution at 0 (cannot produce negative generation)
        draws = np.random.normal(val, std, num_samples)
        samples[:, i] = np.maximum(0.0, draws)
        
    p10 = np.percentile(samples, 10, axis=0)
    p50 = np.percentile(samples, 50, axis=0)
    p90 = np.percentile(samples, 90, axis=0)
    
    return {
        'p10': pd.Series(p10, index=p50_series.index),
        'p50': pd.Series(p50, index=p50_series.index),
        'p90': pd.Series(p90, index=p50_series.index),
        'samples': samples
    }
