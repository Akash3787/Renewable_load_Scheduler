# System Architecture

The architecture decouples the **Ingestion & Forecast Engine**, the **Core Scheduling Engine**, and the **Simulation / Backtest Engine**.

```mermaid
flowchart LR
    subgraph Ingestion
        A1[Weather/Forecast API<br/>Open-Meteo] --> A2[Forecast Adapter]
        A3[Cached/Offline Forecast Store<br/>SQLite/CSV] --> A2
        A4[Field Data Capture App<br/>Streamlit form] --> A5[(field_log table)]
    end
    A2 --> B1[Generation Model<br/>PV physical model / Wind power curve]
    B1 --> C1[(generation_forecast table)]
    subgraph Core Engine
        C1 --> D1[Scenario/Uncertainty Generator]
        D1 --> D2[Renewable-Aware Scheduler<br/>MILP: PuLP/OR-Tools]
        E1[(loads table)] --> D2
        E2[(storage_state / battery model)] --> D2
        E3[(tariff table)] --> D2
        D2 --> F1[(schedule table)]
    end
    subgraph Evaluation
        F1 --> G1[Simulation / Backtest Engine]
        G0[Baseline Scheduler<br/>business-as-usual] --> G1
        G1 --> G2[Metrics: self-consumption %,<br/>peak kW, demand charge $,<br/>violations, forecast error]
        G2 --> G3[Confidence & Failure Analysis]
    end
    G2 --> H1[Dashboard<br/>Streamlit: before/after, uncertainty bands]
    A5 --> G3
```

## Modular Responsibilities

1. **Forecast Adapter (`forecast/adapter.py`)**:
   - Queries Open-Meteo hourly GHI, wind speeds (10m & 100m), temperature, and cloud cover.
   - Falls back gracefully: `live_api` -> SQLite `cache` -> `climatology_fallback`.

2. **Physical Generation Models (`forecast/generation_model.py`)**:
   - **PV Model**: Incorporates cell temperature derating ($T_{cell} = T_{amb} + \frac{GHI}{800}(NOCT-20)$) and panel degradation factors.
   - **Wind Power Curve**: Implements cubic power ramp between cut-in ($3.0$ m/s) and rated ($12.0$ m/s) wind speeds.

3. **Core MILP Scheduler (`scheduler/optimizer.py`)**:
   - Uses PuLP / CBC Mixed-Integer Linear Programming to co-optimize load shifting and battery charge/discharge over rolling horizons.

4. **Simulation & Backtest Engine (`sim/backtest_engine.py`)**:
   - Strictly decoupled from scheduler. Replays baseline and optimized schedules against ground truth `generation_actual` data to measure real-world performance defensively.
