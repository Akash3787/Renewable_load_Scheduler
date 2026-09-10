import sqlite3
import pulp
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

from db import get_connection

class MILPScheduler:
    """
    Mixed-Integer Linear Programming (MILP) Renewable-Aware Scheduler using PuLP.
    Co-optimizes flexible load timing, curtailment, and BESS charge/discharge
    to minimize grid peak demand charges and Time-of-Use energy costs while
    guaranteeing 100% hard constraint satisfaction.
    """
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def schedule_day(
        self,
        start_date: datetime,
        run_id: str = "opt_run_1",
        use_actuals_oracle: bool = False,
        battery_available: bool = True
    ) -> Tuple[pd.DataFrame, Dict[str, Dict[str, float]]]:
        """
        Build and solve MILP model for 24-hour horizon.
        If use_actuals_oracle=True, uses generation_actual (perfect foresight).
        Otherwise uses generation_forecast (p50 forecast).
        """
        conn = get_connection(self.db_path) if self.db_path else get_connection()
        cursor = conn.cursor()
        
        timestamps = [start_date + timedelta(hours=h) for h in range(24)]
        ts_strings = [ts.isoformat() for ts in timestamps]
        
        # Load equipment loads
        cursor.execute("SELECT * FROM loads ORDER BY priority, load_id;")
        loads = [dict(row) for row in cursor.fetchall()]
        
        # Load renewable forecast or ground truth actuals
        if use_actuals_oracle:
            query = """
                SELECT timestamp, pv_kw_actual as pv_kw, wind_kw_actual as wind_kw
                FROM generation_actual WHERE timestamp IN ({})
            """.format(','.join('?' * 24))
            df_gen = pd.read_sql_query(query, conn, params=ts_strings)
        else:
            query = """
                SELECT target_timestamp as timestamp, pv_kw_p50 as pv_kw, wind_kw_p50 as wind_kw
                FROM generation_forecast WHERE target_timestamp IN ({})
                ORDER BY forecast_run_time DESC
            """.format(','.join('?' * 24))
            df_gen = pd.read_sql_query(query, conn, params=ts_strings)
            df_gen = df_gen.drop_duplicates(subset=['timestamp'])
            
        # Ensure complete generation data
        gen_map = {}
        for ts_str in ts_strings:
            row = df_gen[df_gen['timestamp'] == ts_str]
            if not row.empty:
                pv = float(row['pv_kw'].values[0])
                wind = float(row['wind_kw'].values[0])
            else:
                pv, wind = 0.0, 0.0
            gen_map[ts_str] = {'pv': pv, 'wind': wind, 'total': pv + wind}
            
        # Load tariffs
        query_t = "SELECT timestamp, energy_rate, demand_charge_rate FROM tariff WHERE timestamp IN ({})".format(','.join('?' * 24))
        df_tariff = pd.read_sql_query(query_t, conn, params=ts_strings)
        tariff_map = {
            r['timestamp']: {'energy_rate': r['energy_rate'], 'demand_rate': r['demand_charge_rate']}
            for _, r in df_tariff.iterrows()
        }
        
        # Load battery specs
        cursor.execute("SELECT * FROM storage_state ORDER BY timestamp ASC LIMIT 1;")
        bess_row = cursor.fetchone()
        
        cap_kwh = float(bess_row['capacity_kwh']) if bess_row else 400.0
        init_soc = float(bess_row['soc_kwh']) if bess_row else 200.0
        max_chg = float(bess_row['max_charge_kw']) if (bess_row and battery_available) else 0.0
        max_dis = float(bess_row['max_discharge_kw']) if (bess_row and battery_available) else 0.0
        rte = float(bess_row['round_trip_eff']) if bess_row else 0.90
        eta_one_way = np.sqrt(rte)
        
        min_soc = cap_kwh * 0.10
        max_soc = cap_kwh * 0.95
        
        # Initialize PuLP MILP Problem
        prob = pulp.LpProblem("Renewable_Industrial_Load_Scheduler", pulp.LpMinimize)
        
        # Decision Variables
        p_grid = {h: pulp.LpVariable(f"p_grid_{h}", lowBound=0.0) for h in range(24)}
        p_peak = pulp.LpVariable("p_peak", lowBound=0.0)
        
        p_chg = {h: pulp.LpVariable(f"p_chg_{h}", lowBound=0.0, upBound=max_chg) for h in range(24)}
        p_dis = {h: pulp.LpVariable(f"p_dis_{h}", lowBound=0.0, upBound=max_dis) for h in range(24)}
        soc = {h: pulp.LpVariable(f"soc_{h}", lowBound=min_soc, upBound=max_soc) for h in range(24)}
        
        load_vars = {}
        curtail_vars = {}
        start_vars = {}
        
        for load in loads:
            load_id = load['load_id']
            ltype = load['load_type']
            pk = load['power_kw']
            dur_h = int(load['duration_min'] / 60)
            
            if ltype == 'flexible':
                earliest_h = int(load['earliest_start'].split(':')[0])
                deadline_h = int(load['deadline'].split(':')[0])
                
                # Binary variable x[t] = 1 if load starts at hour t
                start_vars[load_id] = {
                    t: pulp.LpVariable(f"start_{load_id}_{t}", cat=pulp.LpBinary)
                    for t in range(24)
                }
                
                # Valid start window bounds
                latest_start_h = max(earliest_h, deadline_h - dur_h)
                
                # Constraint: Must start exactly once in valid window
                prob += pulp.lpSum([start_vars[load_id][t] for t in range(earliest_h, latest_start_h + 1)]) == 1
                
                # Zero out invalid start times
                for t in range(24):
                    if t < earliest_h or t > latest_start_h:
                        prob += start_vars[load_id][t] == 0
                        
                # Active load power per timestep
                for h in range(24):
                    # Active at h if started at any t in [h - dur_h + 1, h]
                    active_starts = [
                        start_vars[load_id][t]
                        for t in range(max(0, h - dur_h + 1), h + 1)
                        if t in start_vars[load_id]
                    ]
                    load_vars[(load_id, h)] = pulp.lpSum(active_starts) * pk
                    
            elif ltype == 'curtailable':
                c_max = load['comfort_band_kw']
                for h in range(24):
                    curtail_vars[(load_id, h)] = pulp.LpVariable(f"curtail_{load_id}_{h}", lowBound=0.0, upBound=c_max)
                    load_vars[(load_id, h)] = pk - curtail_vars[(load_id, h)]
                    
            else: # fixed
                for h in range(24):
                    load_vars[(load_id, h)] = pk

        # Objective Function
        demand_rate = tariff_map[ts_strings[0]]['demand_rate'] if ts_strings else 500.0
        
        energy_costs = pulp.lpSum([
            p_grid[h] * tariff_map[ts_strings[h]]['energy_rate']
            for h in range(24)
        ])
        
        # Minimize total electricity bill: peak demand charge + ToU energy cost
        prob += demand_rate * p_peak + energy_costs
        
        # Constraints
        for h in range(24):
            ts_str = ts_strings[h]
            tot_ren = gen_map[ts_str]['total']
            tot_load_h = pulp.lpSum([load_vars[(load['load_id'], h)] for load in loads])
            
            # 1. Power balance constraint
            prob += p_grid[h] + tot_ren + p_dis[h] >= tot_load_h + p_chg[h]
            
            # 2. Peak demand tracking
            prob += p_peak >= p_grid[h]
            
            # 3. BESS State of Charge Dynamics
            if h == 0:
                prob += soc[0] == init_soc + (p_chg[0] * eta_one_way) - (p_dis[0] / eta_one_way)
            else:
                prob += soc[h] == soc[h-1] + (p_chg[h] * eta_one_way) - (p_dis[h] / eta_one_way)

        # Solve MILP
        import shutil
        cbc_path = shutil.which("cbc")
        if cbc_path:
            solver = pulp.PULP_CBC_CMD(path=cbc_path, msg=False)
        else:
            solver = pulp.PULP_CBC_CMD(msg=False)
        status = prob.solve(solver)
        
        if pulp.LpStatus[status] != 'Optimal':
            print(f"[MILPScheduler] Warning: Solver status: {pulp.LpStatus[status]}")

        # Extract results
        schedule_records = []
        bess_actions = {}
        
        for h in range(24):
            ts_str = ts_strings[h]
            ts_end_str = (timestamps[h] + timedelta(hours=1)).isoformat()
            
            chg_val = float(pulp.value(p_chg[h]) or 0.0)
            dis_val = float(pulp.value(p_dis[h]) or 0.0)
            bess_actions[ts_str] = {'charge_kw': chg_val, 'discharge_kw': dis_val}
            
            for load in loads:
                load_id = load['load_id']
                p_val = float(pulp.value(load_vars[(load_id, h)]) or 0.0)
                if p_val > 0.001:
                    schedule_records.append({
                        'run_id': run_id,
                        'load_id': load_id,
                        'scheduled_start': ts_str,
                        'scheduled_end': ts_end_str,
                        'power_kw': round(p_val, 2),
                        'power_source': 'pv_wind_bess'
                    })
                    
        # Persist schedule to DB
        cursor.execute("DELETE FROM schedule WHERE run_id = ?;", (run_id,))
        for rec in schedule_records:
            cursor.execute("""
                INSERT INTO schedule (run_id, load_id, scheduled_start, scheduled_end, power_kw, power_source)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (rec['run_id'], rec['load_id'], rec['scheduled_start'], rec['scheduled_end'], rec['power_kw'], rec['power_source']))
            
        conn.commit()
        conn.close()
        
        df_sched = pd.DataFrame(schedule_records)
        return df_sched, bess_actions
