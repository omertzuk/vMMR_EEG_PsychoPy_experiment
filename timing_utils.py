"""Pure timing helpers shared by the vMMR task and timing diagnostics."""

import math


# 59.94 / 119.88 are the real "60 Hz" / "120 Hz" video timings (60000/1001 Hz);
# the vMMR stimulus display measures 59.94 Hz (photodiode latency runs, 2026-10-08).
SUPPORTED_REFRESH_RATES = (60.0, 120.0, 59.94, 119.88)
REFRESH_RATE_RELATIVE_TOLERANCE = 0.02


def seconds_to_frames(seconds, refresh_hz):
    """Convert a duration to the nearest positive whole number of frames."""
    frames = int(round(float(seconds) * float(refresh_hz)))
    return max(1, frames)


def parse_expected_refresh_hz(value):
    """Parse and validate the nominal monitor rate selected by the operator."""
    try:
        refresh_hz = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "expected_refresh_hz must be 60, 120, 59.94 or 119.88."
        ) from exc

    if not math.isfinite(refresh_hz) or refresh_hz <= 0:
        raise ValueError("expected_refresh_hz must be a positive finite value.")
    if refresh_hz not in SUPPORTED_REFRESH_RATES:
        supported = " or ".join(f"{rate:g}" for rate in SUPPORTED_REFRESH_RATES)
        raise ValueError(f"expected_refresh_hz must be {supported}; got {value!r}.")
    return refresh_hz


def refresh_rate_matches(
        expected_refresh_hz, measured_refresh_hz,
        relative_tolerance=REFRESH_RATE_RELATIVE_TOLERANCE):
    """Return whether a measured rate is within tolerance of the nominal rate."""
    if measured_refresh_hz is None:
        return False
    expected = float(expected_refresh_hz)
    measured = float(measured_refresh_hz)
    if not math.isfinite(measured) or measured <= 0:
        return False
    return abs(measured - expected) / expected <= float(relative_tolerance)


def refresh_rate_diagnostics(expected_refresh_hz, measured_refresh_hz):
    """Return refresh validation and dropped-frame-threshold inputs."""
    expected = float(expected_refresh_hz)
    if measured_refresh_hz is None:
        return {
            "measurement_successful": False,
            "measured_refresh_hz": None,
            "difference_hz": None,
            "difference_percent": None,
            "matches_expected": None,
            "threshold_rate_hz": expected,
        }

    measured = float(measured_refresh_hz)
    difference_hz = measured - expected
    return {
        "measurement_successful": True,
        "measured_refresh_hz": measured,
        "difference_hz": difference_hz,
        "difference_percent": (difference_hz / expected) * 100.0,
        "matches_expected": refresh_rate_matches(expected, measured),
        "threshold_rate_hz": measured,
    }
