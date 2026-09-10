import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path

from db import get_connection

class BacktestEngine:
    """
    Simulation / Backtest Engine.
    Replays a generated schedule (baseline or optimized) against held-out ground truth
    actual generation data and tariffs.
    """
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def run_backtest(
        self,
        run_id: str,
        bess_actions: Optional[Dict[str, Dict[str, float]]] = None
    ) -> Dict[str, Any]:
        """
        Execute backtest for a given schedule run_id.
        bess_actions format optional: { timestamp_str: {'charge_kw': float, 'discharge_kw': float} }
        """
        conn = get_connection(self.db_path) if self.db_path else get_connection()
        
        try:
            # Load schedule
            df_sched = pd.read_sql_query("SELECT * FROM schedule WHERE run_id = ?", conn, params=[run_id])
            if df_sched.empty:
                raise ValueError(f"No schedule found for run_id: {run_id}")
                
            timestamps = sorted(df_sched['scheduled_start'].unique())
            
            # Load actual generation and tariff data
            query_actual = """
                SELECT a.timestamp, a.pv_kw_actual, a.wind_kw_actual, t.energy_rate, t.demand_charge_rate, t.is_peak_window
                FROM generation_actual a
                JOIN tariff t ON a.timestamp = t.timestamp
                WHERE a.timestamp IN ({})
                ORDER BY a.timestamp ASC
            """.format(','.join('?' * len(timestamps)))
            
            df_actual = pd.read_sql_query(query_actual, conn, params=timestamps)
            
            # Initial storage specs
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM storage_state ORDER BY timestamp ASC LIMIT 1;")
            bess_spec = cursor.fetchone()
        finally:
            conn.close()
        
        soc_kwh = bess_spec['soc_kwh'] if bess_spec else 200.0
        cap_kwh = bess_spec['capacity_kwh'] if bess_spec else 400.0
        max_chg = bess_spec['max_charge_kw'] if bess_spec else 100.0
        max_dis = bess_spec['max_discharge_kw'] if bess_spec else 100.0
        rte = bess_spec['round_trip_eff'] if bess_spec else 0.90
        one_way_eff = np.sqrt(rte)
        
        min_soc = cap_kwh * 0.10
        max_soc = cap_kwh * 0.95
        
        history = []
        total_energy_cost = 0.0
        max_grid_peak_kw = 0.0
        
        total_ren_gen_kwh = 0.0
        total_ren_consumed_kwh = 0.0
        total_grid_import_kwh = 0.0
        
        demand_rate = 500.0
        
        for ts_str in timestamps:
            active_loads = df_sched[df_sched['scheduled_start'] == ts_str]
            total_load_kw = active_loads['power_kw'].sum()
            
            actual_row = df_actual[df_actual['timestamp'] == ts_str]
            if not actual_row.empty:
                pv_act = float(actual_row['pv_kw_actual'].values[0])
                wind_act = float(actual_row['wind_kw_actual'].values[0])
                energy_rate = float(actual_row['energy_rate'].values[0])
                demand_rate = float(actual_row['demand_charge_rate'].values[0])
            else:
                pv_act, wind_act, energy_rate = 0.0, 0.0, 5.0
                
            ren_gen_kw = pv_act + wind_act
            total_ren_gen_kwh += ren_gen_kw
            
            chg_kw = 0.0
            dis_kw = 0.0
            
            if bess_actions and ts_str in bess_actions:
                chg_kw = bess_actions[ts_str].get('charge_kw', 0.0)
                dis_kw = bess_actions[ts_str].get('discharge_kw', 0.0)
                
                chg_kw = min(chg_kw, max_chg, (max_soc - soc_kwh) / one_way_eff)
                dis_kw = min(dis_kw, max_dis, (soc_kwh - min_soc) * one_way_eff)
                
                soc_kwh = soc_kwh + (chg_kw * one_way_eff) - (dis_kw / one_way_eff)
                soc_kwh = np.clip(soc_kwh, min_soc, max_soc)
                
            ren_to_load = min(total_load_kw, ren_gen_kw)
            net_load_kw = total_load_kw - ren_to_load
            
            surplus_ren = max(0.0, ren_gen_kw - ren_to_load)
            ren_to_bess = min(surplus_ren, chg_kw)
            
            total_ren_consumed = ren_to_load + ren_to_bess
            total_ren_consumed_kwh += total_ren_consumed
            
            grid_import_kw = max(0.0, net_load_kw + (chg_kw - ren_to_bess) - dis_kw)
            total_grid_import_kwh += grid_import_kw
            
            if grid_import_kw > max_grid_peak_kw:
                max_grid_peak_kw = grid_import_kw
                
            timestep_energy_cost = grid_import_kw * energy_rate
            total_energy_cost += timestep_energy_cost
            
            history.append({
                'timestamp': ts_str,
                'total_load_kw': total_load_kw,
                'pv_kw': pv_act,
                'wind_kw': wind_act,
                'ren_gen_kw': ren_gen_kw,
                'ren_consumed_kw': total_ren_consumed,
                'grid_import_kw': grid_import_kw,
                'bess_charge_kw': chg_kw,
                'bess_discharge_kw': dis_kw,
                'bess_soc_kwh': soc_kwh,
                'energy_rate': energy_rate,
                'energy_cost': timestep_energy_cost
            })
            
        demand_charge_cost = max_grid_peak_kw * demand_rate
        total_bill = total_energy_cost + demand_charge_cost
        
        self_consumption_pct = (total_ren_consumed_kwh / total_ren_gen_kwh * 100.0) if total_ren_gen_kwh > 0 else 0.0
        
        return {
            'run_id': run_id,
            'total_load_kwh': sum(h['total_load_kw'] for h in history),
            'total_ren_gen_kwh': total_ren_gen_kwh,
            'total_ren_consumed_kwh': total_ren_consumed_kwh,
            'self_consumption_pct': round(self_consumption_pct, 2),
            'total_grid_import_kwh': total_grid_import_kwh,
            'max_peak_grid_kw': round(max_grid_peak_kw, 2),
            'energy_charge_cost': round(total_energy_cost, 2),
            'demand_charge_cost': round(demand_charge_cost, 2),
            'total_bill': round(total_bill, 2),
            'history': pd.DataFrame(history)
        }
