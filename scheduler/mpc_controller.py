import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

from db import get_connection
from scheduler.optimizer import MILPScheduler

class MPCRollingHorizonController:
    """
    Closed-Loop Model Predictive Control (MPC) Rolling Horizon Controller.
    Re-optimizes MILP over a receding 24-hour horizon at every hourly timestep t.
    Applies immediate control actions, tracks stateful in-progress flexible load execution,
    updates state of charge from ground truth actuals, and advances the horizon forward seamlessly.
    """
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path
        self.optimizer = MILPScheduler(db_path=db_path)

    def run_closed_loop_mpc(
        self,
        start_date: datetime,
        run_id: str = "mpc_closed_loop_run"
    ) -> Dict[str, Any]:
        """
        Execute 24-step closed-loop MPC rolling horizon simulation with stateful load tracking.
        """
        conn = get_connection(self.db_path) if self.db_path else get_connection()
        cursor = conn.cursor()
        
        timestamps = [start_date + timedelta(hours=h) for h in range(24)]
        ts_strings = [ts.isoformat() for ts in timestamps]
        
        cursor.execute("SELECT * FROM loads ORDER BY priority, load_id;")
        loads = [dict(r) for r in cursor.fetchall()]
        loads_map = {l['load_id']: l for l in loads}
        
        query_act = "SELECT a.timestamp as timestamp, a.pv_kw_actual, a.wind_kw_actual, t.energy_rate, t.demand_charge_rate FROM generation_actual a JOIN tariff t ON a.timestamp = t.timestamp WHERE a.timestamp IN ({})".format(','.join('?'*24))
        df_actuals = pd.read_sql_query(query_act, conn, params=ts_strings)
        
        cursor.execute("SELECT * FROM storage_state ORDER BY timestamp ASC LIMIT 1;")
        bess_spec = cursor.fetchone()
        
        soc_kwh = bess_spec['soc_kwh'] if bess_spec else 200.0
        cap_kwh = bess_spec['capacity_kwh'] if bess_spec else 400.0
        max_chg = bess_spec['max_charge_kw'] if bess_spec else 100.0
        max_dis = bess_spec['max_discharge_kw'] if bess_spec else 100.0
        rte = bess_spec['round_trip_eff'] if bess_spec else 0.90
        eta_one_way = np.sqrt(rte)
        
        min_soc = cap_kwh * 0.10
        max_soc = cap_kwh * 0.95
        
        conn.close()
        
        # State tracking for flexible loads in closed-loop MPC
        # active_in_progress[load_id] = remaining_hours_to_run
        active_in_progress = {}
        completed_loads = set()
        
        mpc_history = []
        bess_actions_closed_loop = {}
        schedule_records_closed_loop = []
        
        total_energy_cost = 0.0
        max_grid_peak_kw = 0.0
        total_ren_gen_kwh = 0.0
        total_ren_consumed_kwh = 0.0
        total_grid_import_kwh = 0.0
        
        for step_h in range(24):
            current_ts = ts_strings[step_h]
            current_dt = timestamps[step_h]
            
            # Receding horizon solve starting at current_dt
            df_sched_window, bess_actions_window = self.optimizer.schedule_day(
                start_date=current_dt,
                run_id=f"{run_id}_step_{step_h}"
            )
            
            current_bess_action = bess_actions_window.get(current_ts, {'charge_kw': 0.0, 'discharge_kw': 0.0})
            chg_req = current_bess_action['charge_kw']
            dis_req = current_bess_action['discharge_kw']
            
            act_row = df_actuals[df_actuals['timestamp'] == current_ts].iloc[0]
            pv_act = float(act_row['pv_kw_actual'])
            wind_act = float(act_row['wind_kw_actual'])
            energy_rate = float(act_row['energy_rate'])
            demand_rate = float(act_row['demand_charge_rate'])
            ren_gen_kw = pv_act + wind_act
            total_ren_gen_kwh += ren_gen_kw
            
            # Determine load power active at current_ts
            total_load_kw = 0.0
            
            for load in loads:
                load_id = load['load_id']
                ltype = load['load_type']
                pk = float(load['power_kw'])
                dur_h = int(load['duration_min'] / 60)
                
                if ltype in ['fixed', 'curtailable']:
                    # Look up solved power from MPC window
                    matched = df_sched_window[(df_sched_window['load_id'] == load_id) & (df_sched_window['scheduled_start'] == current_ts)]
                    p_val = matched['power_kw'].values[0] if not matched.empty else pk
                    total_load_kw += p_val
                    schedule_records_closed_loop.append({
                        'run_id': run_id,
                        'load_id': load_id,
                        'scheduled_start': current_ts,
                        'scheduled_end': (current_dt + timedelta(hours=1)).isoformat(),
                        'power_kw': round(p_val, 2),
                        'power_source': 'pv_wind_bess'
                    })
                    
                elif ltype == 'flexible':
                    # Check if load is already in-progress
                    if load_id in active_in_progress and active_in_progress[load_id] > 0:
                        total_load_kw += pk
                        active_in_progress[load_id] -= 1
                        schedule_records_closed_loop.append({
                            'run_id': run_id,
                            'load_id': load_id,
                            'scheduled_start': current_ts,
                            'scheduled_end': (current_dt + timedelta(hours=1)).isoformat(),
                            'power_kw': round(pk, 2),
                            'power_source': 'pv_wind_bess'
                        })
                        if active_in_progress[load_id] == 0:
                            completed_loads.add(load_id)
                    elif load_id not in completed_loads:
                        # Check if MPC schedule decides to start it at current_ts or if forced by deadline
                        matched = df_sched_window[(df_sched_window['load_id'] == load_id) & (df_sched_window['scheduled_start'] == current_ts)]
                        deadline_h = int(load['deadline'].split(':')[0])
                        must_start = (step_h >= (deadline_h - dur_h))
                        
                        if not matched.empty or must_start:
                            total_load_kw += pk
                            active_in_progress[load_id] = dur_h - 1
                            if active_in_progress[load_id] == 0:
                                completed_loads.add(load_id)
                            schedule_records_closed_loop.append({
                                'run_id': run_id,
                                'load_id': load_id,
                                'scheduled_start': current_ts,
                                'scheduled_end': (current_dt + timedelta(hours=1)).isoformat(),
                                'power_kw': round(pk, 2),
                                'power_source': 'pv_wind_bess'
                            })

            # Apply BESS physical limits and update SOC
            chg_kw = min(chg_req, max_chg, (max_soc - soc_kwh) / eta_one_way)
            dis_kw = min(dis_req, max_dis, (soc_kwh - min_soc) * eta_one_way)
            
            soc_kwh = soc_kwh + (chg_kw * eta_one_way) - (dis_kw / eta_one_way)
            soc_kwh = np.clip(soc_kwh, min_soc, max_soc)
            
            # Power balance
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
                
            timestep_cost = grid_import_kw * energy_rate
            total_energy_cost += timestep_cost
            
            bess_actions_closed_loop[current_ts] = {'charge_kw': chg_kw, 'discharge_kw': dis_kw}
            
            mpc_history.append({
                'timestamp': current_ts,
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
                'energy_cost': timestep_cost
            })
            
        demand_charge_cost = max_grid_peak_kw * demand_rate
        total_bill = total_energy_cost + demand_charge_cost
        self_consumption_pct = (total_ren_consumed_kwh / total_ren_gen_kwh * 100.0) if total_ren_gen_kwh > 0 else 0.0
        
        conn = get_connection(self.db_path) if self.db_path else get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM schedule WHERE run_id = ?;", (run_id,))
        for rec in schedule_records_closed_loop:
            cursor.execute("""
                INSERT INTO schedule (run_id, load_id, scheduled_start, scheduled_end, power_kw, power_source)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (rec['run_id'], rec['load_id'], rec['scheduled_start'], rec['scheduled_end'], rec['power_kw'], rec['power_source']))
        conn.commit()
        conn.close()
        
        return {
            'run_id': run_id,
            'total_load_kwh': sum(h['total_load_kw'] for h in mpc_history),
            'total_ren_gen_kwh': total_ren_gen_kwh,
            'total_ren_consumed_kwh': total_ren_consumed_kwh,
            'self_consumption_pct': round(self_consumption_pct, 2),
            'total_grid_import_kwh': total_grid_import_kwh,
            'max_peak_grid_kw': round(max_grid_peak_kw, 2),
            'energy_charge_cost': round(total_energy_cost, 2),
            'demand_charge_cost': round(demand_charge_cost, 2),
            'total_bill': round(total_bill, 2),
            'history': pd.DataFrame(mpc_history),
            'bess_actions': bess_actions_closed_loop
        }
