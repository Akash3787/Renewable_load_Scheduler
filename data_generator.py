import math
import yaml
import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

from db import get_connection, init_db
from forecast.generation_model import calculate_pv_power, calculate_wind_power

CONFIG_PATH = Path(__file__).parent / "config" / "scenario.yaml"

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)

def generate_synthetic_weather_data(start_date: datetime, days: int = 28):
    """
    Generate realistic multi-week hourly weather data (GHI, Wind Speed, Temp, Cloud Cover)
    with daily cycles, weather fronts, and forecast perturbations.
    """
    hours = days * 24
    timestamps = [start_date + timedelta(hours=i) for i in range(hours)]
    
    np.random.seed(42) # Reproducible synthetic data
    
    ghi_list = []
    temp_list = []
    cloud_list = []
    wind_10m_list = []
    wind_100m_list = []
    
    for i, ts in enumerate(timestamps):
        hour = ts.hour
        day_of_year = ts.timetuple().tm_yday
        
        # Diurnal Solar Profile (GHI in W/m2)
        # Solar noon roughly at 12:00
        if 6 <= hour <= 18:
            solar_rad = math.sin((hour - 6) / 12.0 * math.pi)
            base_ghi = 950.0 * solar_rad
        else:
            base_ghi = 0.0
            
        # Cloud cover dynamics (passing weather fronts)
        # Low frequency weather system + high frequency turbulence
        front_cycle = math.sin(i / 36.0) * 40.0 + 30.0 # 0 to 70%
        random_cloud = np.clip(front_cycle + np.random.normal(0, 15), 0, 100)
        
        # Actual GHI reduced by cloud cover
        ghi_actual = base_ghi * (1.0 - 0.75 * (random_cloud / 100.0) ** 2)
        ghi_actual = max(0.0, ghi_actual)
        
        # Ambient temperature (°C)
        base_temp = 28.0 + 5.0 * math.sin((hour - 9) / 24.0 * 2 * math.pi)
        temp_c = base_temp + np.random.normal(0, 1.0)
        
        # Wind speed (m/s) with nocturnal boundary layer variations
        base_wind_10m = 5.5 + 2.5 * math.sin((i / 48.0) * 2 * math.pi)
        wind_10m = max(0.0, base_wind_10m + np.random.normal(0, 1.2))
        wind_100m = wind_10m * (100.0 / 10.0) ** 0.2 # Power law wind shear
        
        ghi_list.append(ghi_actual)
        temp_list.append(temp_c)
        cloud_list.append(random_cloud)
        wind_10m_list.append(wind_10m)
        wind_100m_list.append(wind_100m)
        
    df = pd.DataFrame({
        'timestamp': [ts.isoformat() for ts in timestamps],
        'ghi': ghi_list,
        'cloud_cover_pct': cloud_list,
        'temp_c': temp_list,
        'wind_speed_10m': wind_10m_list,
        'wind_speed_100m': wind_100m_list
    })
    return df

def populate_database(start_date: datetime = datetime(2026, 6, 1, 0, 0), days: int = 28):
    init_db()
    config = load_config()
    conn = get_connection()
    
    # 1. Populate Loads Table
    cursor = conn.cursor()
    cursor.execute("DELETE FROM loads;")
    for load in config['loads']:
        cursor.execute("""
            INSERT INTO loads (load_id, name, load_type, power_kw, duration_min, earliest_start, deadline, comfort_band_kw, priority)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            load['load_id'], load['name'], load['load_type'], load['power_kw'],
            load['duration_min'], load['earliest_start'], load['deadline'],
            load['comfort_band_kw'], load['priority']
        ))
        
    # 2. Populate Weather & Generation Actuals
    df_weather = generate_synthetic_weather_data(start_date, days)
    
    pv_cap = config['renewable_assets']['pv_capacity_kwp']
    pv_derate = config['renewable_assets']['pv_derate_factor']
    pv_temp_coeff = config['renewable_assets']['pv_temp_coeff']
    
    wind_rated_kw = config['renewable_assets']['wind_rated_kw']
    cut_in = config['renewable_assets']['wind_cut_in_m_s']
    rated_v = config['renewable_assets']['wind_rated_m_s']
    cut_out = config['renewable_assets']['wind_cut_out_m_s']
    
    cursor.execute("DELETE FROM generation_actual;")
    cursor.execute("DELETE FROM generation_forecast;")
    cursor.execute("DELETE FROM tariff;")
    cursor.execute("DELETE FROM storage_state;")
    
    forecast_run_time = start_date.isoformat()
    
    for _, row in df_weather.iterrows():
        ts_str = row['timestamp']
        ts_dt = datetime.fromisoformat(ts_str)
        
        # Calculate ground truth PV & Wind
        pv_actual = calculate_pv_power(
            ghi=row['ghi'],
            temp_c=row['temp_c'],
            capacity_kwp=pv_cap,
            derate_factor=pv_derate,
            temp_coeff=pv_temp_coeff
        )
        
        wind_actual = calculate_wind_power(
            wind_speed=row['wind_speed_100m'],
            rated_power_kw=wind_rated_kw,
            cut_in_speed=cut_in,
            rated_speed=rated_v,
            cut_out_speed=cut_out
        )
        
        cursor.execute("""
            INSERT INTO generation_actual (timestamp, ghi, cloud_cover_pct, temp_c, wind_speed_10m, wind_speed_100m, pv_kw_actual, wind_kw_actual)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (ts_str, row['ghi'], row['cloud_cover_pct'], row['temp_c'], row['wind_speed_10m'], row['wind_speed_100m'], pv_actual, wind_actual))
        
        # Add day-ahead forecast with realistic forecast error noise
        # PV error correlated with cloudiness, Wind error correlated with speed
        pv_err_std = 0.15 * pv_actual + 10.0 * (row['cloud_cover_pct'] / 100.0)
        wind_err_std = 0.12 * wind_actual + 5.0
        
        pv_p50 = max(0.0, pv_actual + np.random.normal(0, pv_err_std))
        wind_p50 = max(0.0, wind_actual + np.random.normal(0, wind_err_std))
        
        # P10 / P90 Uncertainty Bands
        pv_p10 = max(0.0, pv_p50 - 1.28 * pv_err_std)
        pv_p90 = pv_p50 + 1.28 * pv_err_std
        
        wind_p10 = max(0.0, wind_p50 - 1.28 * wind_err_std)
        wind_p90 = wind_p50 + 1.28 * wind_err_std
        
        horizon = (ts_dt - start_date).total_seconds() / 3600.0
        
        cursor.execute("""
            INSERT INTO generation_forecast (
                forecast_run_time, target_timestamp, horizon_hours, ghi, cloud_cover_pct, temp_c,
                wind_speed_10m, wind_speed_100m, pv_kw_p50, pv_kw_p10, pv_kw_p90,
                wind_kw_p50, wind_kw_p10, wind_kw_p90, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            forecast_run_time, ts_str, horizon, row['ghi'], row['cloud_cover_pct'], row['temp_c'],
            row['wind_speed_10m'], row['wind_speed_100m'], pv_p50, pv_p10, pv_p90,
            wind_p50, wind_p10, wind_p90, "climatology_fallback"
        ))
        
        # Tariff structure
        hour = ts_dt.hour
        is_peak = 1 if (config['tariff']['peak_hours_start'] <= hour < config['tariff']['peak_hours_end']) else 0
        energy_rate = config['tariff']['energy_rate_peak'] if is_peak else config['tariff']['energy_rate_off_peak']
        demand_rate = config['tariff']['demand_charge_rate_per_kw']
        
        cursor.execute("""
            INSERT INTO tariff (timestamp, energy_rate, demand_charge_rate, is_peak_window)
            VALUES (?, ?, ?, ?)
        """, (ts_str, energy_rate, demand_rate, is_peak))
        
        # Initial BESS storage state
        cursor.execute("""
            INSERT INTO storage_state (timestamp, soc_kwh, capacity_kwh, max_charge_kw, max_discharge_kw, round_trip_eff)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            ts_str, config['bess']['initial_soc_kwh'], config['bess']['capacity_kwh'],
            config['bess']['max_charge_kw'], config['bess']['max_discharge_kw'], config['bess']['round_trip_efficiency']
        ))
        
    conn.commit()
    conn.close()
    print(f"Database successfully populated with {days} days of synthetic multi-week data.")

if __name__ == "__main__":
    populate_database()
