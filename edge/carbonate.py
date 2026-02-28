"""
PyCO2SYS wrapper for aragonite saturation state (Omega_arag).

Parameter pair priority:
1. pH + pCO2
2. TA + pH
3. TA + pCO2
4. pH + default_TA (2300)
5. pCO2 + default_TA
6. All defaults → Omega_arag = 1.0 (hard conservative)

Constants: Lueker 2000 (opt_k_carbonic=10), Dickson 1990 (opt_k_bisulfate=1),
           opt_total_scale=1, pressure=0 dbar
"""
import logging
import PyCO2SYS as pyco2

logger = logging.getLogger(__name__)

DEFAULT_TA = 2300.0  # µmol/kg — conservative M1 estimate
K_CARBONIC = 10     # Lueker 2000
K_BISULFATE = 1     # Dickson 1990
OPT_PH_SCALE = 1   # Total scale
PRESSURE = 0        # surface


def _calc(
    par1: float,
    par2: float,
    par1_type: int,
    par2_type: int,
    salinity: float,
    temperature: float,
) -> float:
    """Run PyCO2SYS and return Omega_aragonite."""
    try:
        result = pyco2.sys(
            par1=par1,
            par2=par2,
            par1_type=par1_type,
            par2_type=par2_type,
            salinity=salinity,
            temperature=temperature,
            pressure=PRESSURE,
            opt_k_carbonic=K_CARBONIC,
            opt_k_bisulfate=K_BISULFATE,
            opt_pH_scale=OPT_PH_SCALE,
        )
        omega = float(result["saturation_aragonite"])
        return omega
    except Exception as e:
        logger.warning("PyCO2SYS error: %s", e)
        return 1.0  # conservative fallback


def compute_aragonite(
    pH: float | None,
    pCO2: float | None,
    total_alkalinity: float | None,
    salinity: float,
    temperature: float,
) -> tuple[float, str]:
    """
    Returns (omega_aragonite, method_used).
    """
    s = salinity if salinity else 33.5
    t = temperature if temperature else 12.5

    # Priority 1: pH + pCO2 (best)
    if pH is not None and pCO2 is not None:
        omega = _calc(pH, pCO2, 3, 4, s, t)
        return omega, "pH+pCO2"

    # Priority 2: TA + pH
    if total_alkalinity is not None and pH is not None:
        omega = _calc(total_alkalinity, pH, 1, 3, s, t)
        return omega, "TA+pH"

    # Priority 3: TA + pCO2
    if total_alkalinity is not None and pCO2 is not None:
        omega = _calc(total_alkalinity, pCO2, 1, 4, s, t)
        return omega, "TA+pCO2"

    # Priority 4: pH + default TA
    if pH is not None:
        omega = _calc(DEFAULT_TA, pH, 1, 3, s, t)
        return omega, "pH+defaultTA"

    # Priority 5: pCO2 + default TA
    if pCO2 is not None:
        omega = _calc(DEFAULT_TA, pCO2, 1, 4, s, t)
        return omega, "pCO2+defaultTA"

    # Priority 6: all defaults — hard conservative
    logger.warning("No carbonate parameters available — returning Omega=1.0")
    return 1.0, "all_defaults"
