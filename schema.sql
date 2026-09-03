-- Database Schema for Renewable-Aware Industrial Load Scheduler

CREATE TABLE IF NOT EXISTS generation_forecast (
    forecast_run_time TEXT,
    target_timestamp TEXT,
    horizon_hours REAL,
    ghi REAL,
    cloud_cover_pct REAL,
    temp_c REAL,
    wind_speed_10m REAL,
    wind_speed_100m REAL,
    pv_kw_p50 REAL,
    pv_kw_p10 REAL,
    pv_kw_p90 REAL,
    wind_kw_p50 REAL,
    wind_kw_p10 REAL,
    wind_kw_p90 REAL,
    source TEXT, -- 'live_api' | 'cache' | 'climatology_fallback'
    PRIMARY KEY (forecast_run_time, target_timestamp)
);

CREATE TABLE IF NOT EXISTS generation_actual (
    timestamp TEXT PRIMARY KEY,
    ghi REAL,
    cloud_cover_pct REAL,
    temp_c REAL,
    wind_speed_10m REAL,
    wind_speed_100m REAL,
    pv_kw_actual REAL,
    wind_kw_actual REAL
);

CREATE TABLE IF NOT EXISTS loads (
    load_id TEXT PRIMARY KEY,
    name TEXT,
    load_type TEXT, -- 'fixed' | 'flexible' | 'curtailable'
    power_kw REAL,
    duration_min INTEGER,
    earliest_start TEXT,
    deadline TEXT,
    comfort_band_kw REAL,
    priority INTEGER
);

CREATE TABLE IF NOT EXISTS storage_state (
    timestamp TEXT PRIMARY KEY,
    soc_kwh REAL,
    capacity_kwh REAL,
    max_charge_kw REAL,
    max_discharge_kw REAL,
    round_trip_eff REAL
);

CREATE TABLE IF NOT EXISTS tariff (
    timestamp TEXT PRIMARY KEY,
    energy_rate REAL,
    demand_charge_rate REAL,
    is_peak_window INTEGER
);

CREATE TABLE IF NOT EXISTS schedule (
    run_id TEXT,
    load_id TEXT,
    scheduled_start TEXT,
    scheduled_end TEXT,
    power_kw REAL,
    power_source TEXT, -- 'grid' | 'pv' | 'wind' | 'battery' | 'mixed'
    PRIMARY KEY (run_id, load_id, scheduled_start)
);

CREATE TABLE IF NOT EXISTS field_log (
    timestamp TEXT,
    engineer_id TEXT,
    load_id TEXT,
    event_type TEXT, -- 'deviation' | 'complaint' | 'override' | 'note'
    note TEXT
);
