import sqlite3
import requests
import yaml
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from db import get_connection
from forecast.generation_model import calculate_pv_power, calculate_wind_power

CONFIG_PATH = Path(__file__).parent.parent / "config" / "scenario.yaml"

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)

class ForecastAdapter:
    def __init__(self, db_path: Optional[Path] = None):
        self.config = load_config()
        self.db_path = db_path
        self.lat = self.config['facility']['location']['latitude']
        self.lon = self.config['facility']['location']['longitude']

    def fetch_live_open_meteo(self) -> Optional[pd.DataFrame]:
        """
        Attempt to fetch 7-day hourly solar and wind forecasts from Open-Meteo API.
        No API key required.
        """
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": self.lat,
            "longitude": self.lon,
            "hourly": "shortwave_radiation,temperature_2m,cloud_cover,wind_speed_10m,wind_speed_100m",
            "forecast_days": 7,
            "timezone": "auto"
        }
        try:
            response = requests.get(url, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                hourly = data.get("hourly", {})
                times = hourly.get("time", [])
                
                df = pd.DataFrame({
                    'timestamp': [datetime.fromisoformat(t).isoformat() for t in times],
                    'ghi': hourly.get("shortwave_radiation", []),
                    'temp_c': hourly.get("temperature_2m", []),
                    'cloud_cover_pct': hourly.get("cloud_cover", []),
                    'wind_speed_10m': hourly.get("wind_speed_10m", []),
                    'wind_speed_100m': hourly.get("wind_speed_100m", [])
                })
                return df
        except Exception as e:
            print(f"[ForecastAdapter] Open-Meteo live pull failed: {e}. Falling back...")
        return None

    def get_cached_forecast(self, target_timestamps: List[str]) -> Optional[pd.DataFrame]:
        """Retrieve recent cached forecast from SQLite database."""
        conn = get_connection(self.db_path) if self.db_path else get_connection()
        query = """
            SELECT * FROM generation_forecast
            WHERE target_timestamp IN ({})
            ORDER BY forecast_run_time DESC
        """.format(','.join('?' * len(target_timestamps)))
        
        try:
            df = pd.read_sql_query(query, conn, params=target_timestamps)
            if not df.empty:
                # Deduplicate by target_timestamp taking latest run
                df = df.drop_duplicates(subset=['target_timestamp'], keep='first')
                if len(df) == len(target_timestamps):
                    df['source'] = 'cache'
                    return df
        except Exception as e:
            print(f"[ForecastAdapter] SQLite cache query error: {e}")
        finally:
            conn.close()
        return None

    def get_climatology_fallback(self, target_timestamps: List[str]) -> pd.DataFrame:
        """
        Fallback forecast based on historical average (climatology/persistence)
        if live API is unreachable and cache is unavailable.
        """
        conn = get_connection(self.db_path) if self.db_path else get_connection()
        
        records = []
        for ts_str in target_timestamps:
            ts_dt = datetime.fromisoformat(ts_str)
            hour = ts_dt.hour
            
            # Query historical actuals for the same hour
            query = """
                SELECT AVG(ghi) as avg_ghi, AVG(temp_c) as avg_temp,
                       AVG(cloud_cover_pct) as avg_cloud,
                       AVG(wind_speed_10m) as avg_w10, AVG(wind_speed_100m) as avg_w100,
                       AVG(pv_kw_actual) as avg_pv, AVG(wind_kw_actual) as avg_wind
                FROM generation_actual
                WHERE strftime('%H', timestamp) = ?
            """
            cursor = conn.cursor()
            cursor.execute(query, (f"{hour:02d}",))
            row = cursor.fetchone()
            
            avg_ghi = row['avg_ghi'] if row and row['avg_ghi'] is not None else (400.0 if 6 <= hour <= 18 else 0.0)
            avg_temp = row['avg_temp'] if row and row['avg_temp'] is not None else 28.0
            avg_cloud = row['avg_cloud'] if row and row['avg_cloud'] is not None else 20.0
            avg_w10 = row['avg_w10'] if row and row['avg_w10'] is not None else 5.0
            avg_w100 = row['avg_w100'] if row and row['avg_w100'] is not None else 7.0
            
            pv_p50 = calculate_pv_power(
                ghi=avg_ghi, temp_c=avg_temp,
                capacity_kwp=self.config['renewable_assets']['pv_capacity_kwp'],
                derate_factor=self.config['renewable_assets']['pv_derate_factor']
            )
            wind_p50 = calculate_wind_power(
                wind_speed=avg_w100,
                rated_power_kw=self.config['renewable_assets']['wind_rated_kw'],
                cut_in_speed=self.config['renewable_assets']['wind_cut_in_m_s'],
                rated_speed=self.config['renewable_assets']['wind_rated_m_s']
            )
            
            records.append({
                'target_timestamp': ts_str,
                'ghi': avg_ghi,
                'cloud_cover_pct': avg_cloud,
                'temp_c': avg_temp,
                'wind_speed_10m': avg_w10,
                'wind_speed_100m': avg_w100,
                'pv_kw_p50': pv_p50,
                'pv_kw_p10': max(0.0, pv_p50 * 0.7),
                'pv_kw_p90': pv_p50 * 1.3,
                'wind_kw_p50': wind_p50,
                'wind_kw_p10': max(0.0, wind_p50 * 0.7),
                'wind_kw_p90': wind_p50 * 1.3,
                'source': 'climatology_fallback'
            })
        conn.close()
        return pd.DataFrame(records)

    def get_forecast(self, target_timestamps: List[str], force_offline: bool = False) -> pd.DataFrame:
        """
        Hierarchical forecast retrieval: Live API -> Cache -> Climatology Fallback.
        Guarantees returned DataFrame has 'source' tag.
        """
        if not force_offline:
            df_live = self.fetch_live_open_meteo()
            if df_live is not None:
                # Calculate PV & Wind for live data
                df_live['pv_kw_p50'] = df_live.apply(
                    lambda r: calculate_pv_power(
                        r['ghi'], r['temp_c'],
                        self.config['renewable_assets']['pv_capacity_kwp'],
                        self.config['renewable_assets']['pv_derate_factor']
                    ), axis=1
                )
                df_live['pv_kw_p10'] = df_live['pv_kw_p50'] * 0.8
                df_live['pv_kw_p90'] = df_live['pv_kw_p50'] * 1.2
                
                df_live['wind_kw_p50'] = df_live.apply(
                    lambda r: calculate_wind_power(
                        r['wind_speed_100m'],
                        self.config['renewable_assets']['wind_rated_kw'],
                        self.config['renewable_assets']['wind_cut_in_m_s'],
                        self.config['renewable_assets']['wind_rated_m_s']
                    ), axis=1
                )
                df_live['wind_kw_p10'] = df_live['wind_kw_p50'] * 0.8
                df_live['wind_kw_p90'] = df_live['wind_kw_p50'] * 1.2
                df_live['source'] = 'live_api'
                
                # Filter for target timestamps if matched
                matched = df_live[df_live['timestamp'].isin(target_timestamps)]
                if len(matched) == len(target_timestamps):
                    return matched.rename(columns={'timestamp': 'target_timestamp'})
        
        # Try Cache
        cached = self.get_cached_forecast(target_timestamps)
        if cached is not None and not cached.empty:
            return cached
            
        # Fallback to Climatology
        return self.get_climatology_fallback(target_timestamps)
