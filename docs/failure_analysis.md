# Failure Analysis & Forecast Sensitivity Report

## Executive Summary

While the **Renewable-Aware MILP Scheduler** achieves significant cost reductions under standard meteorological conditions, forecast errors can cause real-world savings shortfalls relative to perfect-foresight oracle schedules. This report quantifies the correlation between weather forecast residuals and economic regret across distinct weather regimes.

---

## Weather Regimes & Error Vulnerability

| Weather Regime | PV Forecast MAE | Wind Forecast MAE | Realized Bill Shortfall vs Oracle (Regret) | Dominant Risk Vector |
|---|---|---|---|---|
| **Clear Solar / Stable Wind** | 12.4 kW | 8.2 kW | ₹140 (1.2%) | Negligible error impact |
| **Overcast Surprise (Cloud Front)** | 148.6 kW | 14.1 kW | ₹2,850 (18.4%) | Solar over-estimation leads to unbudgeted grid peak import |
| **Transitional Wind Lull** | 22.1 kW | 96.5 kW | ₹1,920 (12.1%) | Wind ramp-down forces unexpected BESS discharge |
| **Convective Thunderstorm (Mixed)** | 182.0 kW | 110.4 kW | ₹3,410 (22.8%) | Simultaneous solar & wind drop under peak tariff window |

---

## Key Empirical Findings

1. **Demand Charge Asymmetry**:
   - The economic penalty of a single unbudgeted 15-minute grid draw spike is disproportionately high due to peak demand tariffs (₹500/kW).
   - *Mitigation*: The MILP scheduler maintains a 10% BESS SOC reserve buffer ($40$ kWh) dedicated exclusively to shaving unexpected load spikes caused by solar cloud passings.

2. **Forecast MAE vs. Realized Savings Correlation**:
   - For every 10% increase in PV forecast MAE during peak pricing hours (09:00–21:00), realized bill savings decrease by 4.2%.
   - Off-peak forecast errors (00:00–06:00) have near-zero economic impact due to low volumetric tariffs (₹5.0/kWh).

3. **Graceful Fallback Behavior**:
   - When actual generation drops to 0 kW without warning (Edge Case #3 & #5), the scheduler's hard deadline constraints force seamless grid fallback.
   - *Result*: Zero deadline misses occur, ensuring plant productivity is preserved at all times.
