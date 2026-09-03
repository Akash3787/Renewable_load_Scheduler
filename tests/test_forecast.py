import pytest
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

from db import init_db, DB_PATH
from data_generator import populate_database
from forecast.generation_model import calculate_pv_power, calculate_wind_power
from forecast.adapter import ForecastAdapter

@pytest.fixture(scope="module")
def setup_test_db(tmp_path_factory):
    db_dir = tmp_path_factory.mktemp("db")
    db_file = db_dir / "test_scheduler.db"
    start_date = datetime(2026, 6, 1, 0, 0)
    populate_database(start_date, days=3)
    return db_file

def test_pv_generation_model():
    # Test zero GHI
    assert calculate_pv_power(0.0, 25.0) == 0.0
    
    # Test STC condition (1000 W/m2, 25°C ambient with cell heating) -> 371.875 kW
    pv_stc = calculate_pv_power(1000.0, 25.0, capacity_kwp=500.0, derate_factor=0.85)
    assert pytest.approx(pv_stc, abs=5.0) == 371.875
    
    # Test hot day temperature derating
    pv_hot = calculate_pv_power(1000.0, 40.0, capacity_kwp=500.0, derate_factor=0.85)
    assert pv_hot < pv_stc

def test_wind_generation_model():
    # Below cut-in (3.0 m/s) -> 0 kW
    assert calculate_wind_power(2.0) == 0.0
    
    # At rated speed (12.0 m/s) -> 300 kW
    assert calculate_wind_power(12.0) == 300.0
    
    # Above cut-out (25.0 m/s) -> 0 kW
    assert calculate_wind_power(26.0) == 0.0
    
    # Intermediate speed cubic curve
    p_mid = calculate_wind_power(8.0)
    assert 0.0 < p_mid < 300.0

def test_forecast_adapter_climatology_fallback():
    # Populate default DB
    populate_database(datetime(2026, 6, 1, 0, 0), days=3)
    
    adapter = ForecastAdapter()
    target_ts = [(datetime(2026, 6, 1, 0, 0) + timedelta(hours=i)).isoformat() for i in range(24)]
    
    # Force offline mode to test fallback
    df_forecast = adapter.get_forecast(target_ts, force_offline=True)
    
    assert not df_forecast.empty
    assert 'source' in df_forecast.columns
    assert df_forecast['source'].iloc[0] in ['cache', 'climatology_fallback']
    assert len(df_forecast) == 24
