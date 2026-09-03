import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path

from db import get_connection

class BaselineScheduler:
    """
    Business-as-usual naive baseline scheduler.
    - Fixed loads run continuously.
    - Flexible loads start immediately at earliest_start.
    - Curtailable loads operate at 100% full rating without optimization.
    - BESS is idle (0 charge/discharge).
    """
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def schedule_day(self, start_date: datetime, run_id: str = "baseline_run_1") -> pd.DataFrame:
        conn = get_connection(self.db_path) if self.db_path else get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM loads ORDER BY priority, load_id;")
        loads = cursor.fetchall()
        
        timestamps = [start_date + timedelta(hours=h) for h in range(24)]
        ts_strings = [ts.isoformat() for ts in timestamps]
        
        schedule_records = []
        
        for load in loads:
            load_id = load['load_id']
            load_type = load['load_type']
            power_kw = load['power_kw']
            duration_hours = int(load['duration_min'] / 60)
            earliest_str = load['earliest_start']
            
            # Parse earliest start hour
            earliest_hour = int(earliest_str.split(':')[0])
            
            for h_idx, ts_str in enumerate(ts_strings):
                load_active_kw = 0.0
                
                if load_type == 'fixed' or load_type == 'curtailable':
                    load_active_kw = power_kw # Always runs at 100% full load
                elif load_type == 'flexible':
                    # Starts at earliest_start and runs for duration_hours
                    if earliest_hour <= h_idx < (earliest_hour + duration_hours):
                        load_active_kw = power_kw
                
                if load_active_kw > 0.0:
                    schedule_records.append({
                        'run_id': run_id,
                        'load_id': load_id,
                        'scheduled_start': ts_str,
                        'scheduled_end': (timestamps[h_idx] + timedelta(hours=1)).isoformat(),
                        'power_kw': load_active_kw,
                        'power_source': 'mixed'
                    })
        
        # Save to database
        cursor.execute("DELETE FROM schedule WHERE run_id = ?;", (run_id,))
        for rec in schedule_records:
            cursor.execute("""
                INSERT INTO schedule (run_id, load_id, scheduled_start, scheduled_end, power_kw, power_source)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (rec['run_id'], rec['load_id'], rec['scheduled_start'], rec['scheduled_end'], rec['power_kw'], rec['power_source']))
            
        conn.commit()
        conn.close()
        
        df_sched = pd.DataFrame(schedule_records)
        return df_sched
