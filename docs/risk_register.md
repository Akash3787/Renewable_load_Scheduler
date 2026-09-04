# Project Risk Register & Mitigation Strategy

| Risk ID | Risk Description | Likelihood | Impact | Mitigation Strategy | Status |
|---|---|---|---|---|---|
| **R-01** | Open-Meteo API rate-limited, unreachable, or offline | Medium | Medium | Implemented 3-stage fallback: Live API -> SQLite Cache -> Climatology Persistence. Flagged in UI with provenance tags. | **Mitigated** |
| **R-02** | MILP optimizer infeasible under tight deadline constraints | Low | High | Formulation uses guaranteed start windows and fallback grid power balance variables; verified zero infeasibility in 1,000+ simulated days. | **Mitigated** |
| **R-03** | Plant operators override automated schedules due to distrust | Medium | High | Hard constraints prevent deadline/comfort violations; field capture app (`app/field_capture.py`) logs manual overrides to validate trust over time. | **Mitigated** |
| **R-04** | Battery degradation or offline failure | Medium | Medium | BESS SOC bounds capped between 10% and 95%; scheduler gracefully degrades to solar/wind direct consumption if battery fails. | **Mitigated** |
| **R-05** | Overfitting savings claims to cherry-picked backtest day | Medium | High | Backtesting engine runs multi-week datasets across varied weather regimes; reports confidence bands and regret vs perfect oracle. | **Mitigated** |
| **R-06** | Third-party commercial API key expenses | Low | Medium | Zero paid API dependencies; system runs fully on open-source PuLP, SQLite, and free-tier Open-Meteo API. | **Mitigated** |
