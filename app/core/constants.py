# Extreme Sea State (ESS) thresholds for Wave Glider navigation guidance.
# Liquid Robotics "Recommended Course" uses 5 m; this app defaults to 4.5 m per operator standard.
# Consider making configurable (e.g. via config) if alignment with 5 m is needed.

ESS_WAVE_HEIGHT_THRESHOLD_M = 4.5  # >= this: extreme seas, figure-8 (bow-tie) pattern required
ESS_APPROACHING_THRESHOLD_M = 2.5  # [approaching, ESS): increasing seas; < this: calm


def get_ess_state(wave_height_m: float | None) -> str | None:
    """Return 'calm' | 'increasing' | 'extreme' from wave height (m), or None if no data."""
    if wave_height_m is None:
        return None
    try:
        h = float(wave_height_m)
    except (TypeError, ValueError):
        return None
    if h != h:  # NaN
        return None
    if h >= ESS_WAVE_HEIGHT_THRESHOLD_M:
        return "extreme"
    if h >= ESS_APPROACHING_THRESHOLD_M:
        return "increasing"
    return "calm"
