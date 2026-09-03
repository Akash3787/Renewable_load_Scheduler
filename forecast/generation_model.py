import math

def calculate_pv_power(
    ghi: float,
    temp_c: float,
    capacity_kwp: float = 500.0,
    derate_factor: float = 0.85,
    temp_coeff: float = -0.004, # -0.4% per degree C above 25°C
    noct: float = 45.0          # Nominal Operating Cell Temperature
) -> float:
    """
    Calculate PV power output (kW) using standard physical cell temperature and derating models.
    """
    if ghi <= 0.0:
        return 0.0
    
    # Estimate PV cell temperature from ambient temperature and irradiance
    cell_temp = temp_c + (ghi / 800.0) * (noct - 20.0)
    
    # Temperature loss/gain relative to STC (25°C)
    temp_multiplier = 1.0 + temp_coeff * (cell_temp - 25.0)
    temp_multiplier = max(0.5, temp_multiplier) # Physical safety bound
    
    # Power calculation
    power_kw = capacity_kwp * (ghi / 1000.0) * derate_factor * temp_multiplier
    return max(0.0, power_kw)


def calculate_wind_power(
    wind_speed: float,
    rated_power_kw: float = 300.0,
    cut_in_speed: float = 3.0,
    rated_speed: float = 12.0,
    cut_out_speed: float = 25.0
) -> float:
    """
    Calculate wind power output (kW) using a realistic 3-stage cubic power curve.
    """
    if wind_speed < cut_in_speed or wind_speed >= cut_out_speed:
        return 0.0
    elif wind_speed >= rated_speed:
        return rated_power_kw
    else:
        # Cubic curve between cut-in and rated speeds
        num = (wind_speed ** 3) - (cut_in_speed ** 3)
        den = (rated_speed ** 3) - (cut_in_speed ** 3)
        fraction = num / den
        return rated_power_kw * max(0.0, min(1.0, fraction))
