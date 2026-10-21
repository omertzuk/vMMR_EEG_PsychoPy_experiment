import pytest

from timing_utils import (
    parse_expected_refresh_hz,
    refresh_rate_diagnostics,
    refresh_rate_matches,
    seconds_to_frames,
)


@pytest.mark.parametrize(
    ("refresh_hz", "expected"),
    [
        (
            60,
            {
                0.500: 30,
                0.700: 42,
                0.600: 36,
                0.250: 15,
                0.350: 21,
            },
        ),
        (
            120,
            {
                0.500: 60,
                0.700: 84,
                0.600: 72,
                0.250: 30,
                0.350: 42,
            },
        ),
    ],
)
def test_expected_experiment_frame_counts(refresh_hz, expected):
    for duration, frames in expected.items():
        assert seconds_to_frames(duration, refresh_hz) == frames

    face_on = seconds_to_frames(0.250, refresh_hz)
    blank = seconds_to_frames(0.350, refresh_hz)
    face_soa = seconds_to_frames(0.600, refresh_hz)
    assert face_on + blank == face_soa


@pytest.mark.parametrize("value", ["60", 60.0, "120", 120.0])
def test_expected_refresh_parser_accepts_supported_rates(value):
    assert parse_expected_refresh_hz(value) in (60.0, 120.0)


@pytest.mark.parametrize(("value", "expected"),
                         [("59.94", 59.94), (59.94, 59.94), ("119.88", 119.88)])
def test_expected_refresh_parser_accepts_fractional_video_rates(value, expected):
    assert parse_expected_refresh_hz(value) == expected


def test_frame_counts_at_59_94_match_60():
    # Measured stimulus display rate: same frame counts as 60 Hz, SOA intact.
    for duration in (0.500, 0.700, 0.600, 0.250, 0.350, 1.000, 2.000, 0.750):
        assert seconds_to_frames(duration, 59.94) == seconds_to_frames(duration, 60)
    assert (seconds_to_frames(0.250, 59.94) + seconds_to_frames(0.350, 59.94)
            == seconds_to_frames(0.600, 59.94))


@pytest.mark.parametrize("value", ["", "not-a-rate", 0, -60, 75, 59.9, float("inf")])
def test_expected_refresh_parser_rejects_invalid_or_unsupported_rates(value):
    with pytest.raises(ValueError):
        parse_expected_refresh_hz(value)


def test_refresh_rate_validation_accepts_common_fractional_rates():
    assert refresh_rate_matches(60, 59.94)
    assert refresh_rate_matches(120, 119.88)


def test_refresh_rate_validation_rejects_wrong_monitor_mode():
    assert not refresh_rate_matches(60, 120)
    assert not refresh_rate_matches(120, 60)


def test_missing_refresh_measurement_uses_expected_rate_for_threshold():
    diagnostics = refresh_rate_diagnostics(120, None)
    assert diagnostics["measurement_successful"] is False
    assert diagnostics["matches_expected"] is None
    assert diagnostics["threshold_rate_hz"] == 120
    assert diagnostics["measured_refresh_hz"] is None
