# User Guide — Renewable-Aware Industrial Load Scheduler

Welcome to the **Renewable-Aware Industrial Load Scheduler** user guide. This manual explains how facility engineers and plant managers can operate, configure, and inspect the load scheduling system.

---

## 1. System Scope & Non-Negotiable Boundaries

- **What the system DOES**:
  - Automatically shifts flexible equipment loads (curing ovens, water pumps, forklift charging, compressor cycling) to align with peak forecasted solar and wind generation.
  - Dynamically charges and discharges the Battery Energy Storage System (BESS) to shave peak grid demand spikes and minimize Time-of-Use electricity bills.
  - Throttles curtailable HVAC / Chilled water buffers within pre-approved comfort bands.

- **What the system NEVER DOES**:
  - Never overrides safety-critical continuous fixed assembly loads.
  - Never causes a flexible load to miss its operational deadline.
  - Never exceeds curtailable load comfort boundaries.

---

## 2. Setting Up Facility Scenarios (`config/scenario.yaml`)

Facility profiles are defined in [`config/scenario.yaml`](config/scenario.yaml). To adapt the system to a new industrial site:

1. Open `config/scenario.yaml`.
2. Update `facility.location` latitude and longitude for weather forecasting.
3. Update `renewable_assets` (PV capacity in kWp, Wind rated kW).
4. Define equipment loads under `loads`:
   ```yaml
   - load_id: "FLEX_OVEN_1"
     name: "Batch Curing Oven #1"
     load_type: "flexible" # 'fixed' | 'flexible' | 'curtailable'
     power_kw: 80.0
     duration_min: 180
     earliest_start: "06:00"
     deadline: "18:00"
     comfort_band_kw: 0.0
     priority: 2
   ```
5. Configure electricity tariffs under `tariff` (energy rate, peak hours, demand charge rate per kW).

---

## 3. Running Backtests & Operating Dashboard

Launch the interactive results dashboard:
```bash
streamlit run app/dashboard.py
```
- **Schedule & Power Dispatch Tab**: View 24-hour factory power draw, grid import reduction, and battery SOC state.
- **Generation Forecast & Confidence Bands Tab**: View P10–P90 solar/wind forecast uncertainty intervals vs ground truth actuals.
- **Performance Matrix Tab**: Compare Baseline (BAU) vs. MILP Optimizer vs. Perfect-Foresight Oracle bills side-by-side.

---

## 4. Logging Field Events (`app/field_capture.py`)

Plant operators can log equipment overrides, complaints, or maintenance events from any mobile device or terminal (works offline):
```bash
streamlit run app/field_capture.py
```
1. Enter Engineer ID.
2. Select equipment load from dropdown.
3. Select event type (`override`, `complaint`, `deviation`, `note`).
4. Enter one-line explanation and tap **Save Field Event**.

---

## 5. Manual Override Procedure

If an operator needs to manually force a flexible load to run immediately:
1. Open `app/field_capture.py` and log an `override` event.
2. The scheduler will automatically allocate grid power to serve the load while keeping other flexible loads optimized.
