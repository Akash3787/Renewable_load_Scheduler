# Stakeholder Assumptions

The **Renewable-Aware Industrial Load Scheduler** operates under the following explicit stakeholder baseline assumptions:

1. **Load Classification & Process Rigor**:
   - **Fixed Loads**: Non-negotiable continuous line processes and safety systems that must run 24/7 at 100% power allocation.
   - **Flexible/Shiftable Loads**: Batch processes (curing ovens, water pumps, forklift EV fleet charging, air compressor tanks) that can be scheduled dynamically within an `[earliest_start, deadline]` window for a required cumulative duration.
   - **Curtailable/Comfort-bound Loads**: Environmental and thermal buffer processes (HVAC, chilled water buffering) that can be throttled within a pre-approved comfort tolerance band (e.g., maximum 30 kW reduction).

2. **Battery Energy Storage System (BESS)**:
   - The facility possesses (or simulates) a lithium-ion BESS with 400 kWh capacity, 100 kW charge/discharge power limits, and a 90% round-trip efficiency (RTE).
   - Battery state of charge (SOC) must remain bounded between 10% (reserve buffer) and 95% (cell longevity cap).

3. **Tariff & Commercial Terms**:
   - Energy rate consists of a Time-of-Use (ToU) volumetric rate (Off-peak ₹5.0/kWh vs. Peak ₹12.0/kWh between 09:00 and 21:00).
   - Demand Charge: Tariff penalty billed on the facility's highest peak grid draw (₹500/kW) during the billing period.

4. **Zero-Capital Low-Friction Field Integration**:
   - Facility engineers and operators are primary users. They require a mobile-friendly, low-bandwidth tool (`app/field_capture.py`) to log field events (overrides, deviations, complaints) offline without complex software installation.
   - System is built with open-source software (Python, PuLP, SQLite, Open-Meteo, Streamlit) with zero paid API key dependencies.

5. **Hard Constraint Non-Negotiability**:
   - Hard deadline misses or comfort band violations are strictly forbidden. The MILP solver treats deadlines and comfort boundaries as enforced hard constraints, falling back to grid power if renewable availability is insufficient.
