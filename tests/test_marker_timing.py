"""Synthetic tests of the marker-timing correction (analysis/marker_timing.py).

A recording is simulated from first principles: the amplifier acquires sample k at
A-clock time acq(k) (with clock drift), delivers frames of 8 samples, and the model
processes each frame either in a burst on arrival or steadily one frame behind.
Markers are sent on B at known times; the correction must recover the true onsets.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import marker_timing as mt  # noqa: E402

FS = 600.0
FRAME = 8
TRANSFER_S = 0.002
DISPLAY_S = 0.050           # true light delay after the marker is sent
OFFSET_BA = -123.456        # B clock + OFFSET_BA = A clock
A0 = 1000.0                 # A-clock time of sample 0


def simulate(duration_s=120.0, mode="burst", drift_ppm=0.0, events_s=None, stall=None):
    n = int(duration_s * FS)
    k = np.arange(n)
    tsim = k / FS
    acq = A0 + tsim * (1 + drift_ppm * 1e-6)
    if mode == "burst":                                  # whole frame processed when its last sample arrives
        last = (k // FRAME) * FRAME + FRAME - 1
        t_a = acq[np.minimum(last, n - 1)] + TRANSFER_S + (k % FRAME) * 20e-6
    else:                                                # steady: each sample processed as late as the first
        t_a = acq + (FRAME - 1) / FS + TRANSFER_S        # sample of a burst frame, one step per sample period
    if stall is not None:                                # (at_s, length_s, caught_up)
        at, length, caught = stall
        i = int(at * FS)
        t_a[i:] += length
        if caught:                                       # model runs fast until it is back in step
            back = np.arange(n - i)
            t_a[i:] -= np.minimum(length, back * (length / (0.5 * FS)))
    timing = np.zeros((n, 6))
    timing[:, 2] = np.nan
    timing[:, 3] = OFFSET_BA
    timing[:, 4] = t_a
    timing[:, 5] = 1
    truth = []
    for j, tau_light in enumerate(events_s or []):
        sent_a = A0 + tau_light * (1 + drift_ppm * 1e-6) - DISPLAY_S
        step = int(np.searchsorted(t_a, sent_a))
        timing[step, 1] = 11 + j % 4
        timing[step, 2] = sent_a - OFFSET_BA
        truth.append(tau_light)
    return tsim, timing, np.array(truth)


def correction_for_sim():
    """The constant this simulated set-up needs: display delay + the delay between the
    acquisition of the first sample of a frame and its processing (the upper envelope)."""
    return (DISPLAY_S + (FRAME - 1) / FS + TRANSFER_S) * 1000


@pytest.mark.parametrize("mode", ["burst", "steady"])
def test_onsets_recovered_in_both_model_states(mode):
    events = list(np.arange(15.0, 110.0, 0.6) + 0.0123)
    tsim, timing, truth = simulate(mode=mode, events_s=events)
    ev = mt.place_events(tsim, timing, correction_ms=correction_for_sim())
    assert len(ev) == len(truth)
    err_ms = (ev.onset_s.to_numpy() - truth) * 1000
    assert np.abs(err_ms).max() < 1.0
    assert np.all(np.abs(ev["sample"].to_numpy() / FS - truth) <= 0.5 / FS + 1e-3)


def test_clock_drift_is_followed():
    events = list(np.arange(15.0, 1790.0, 5.0))
    tsim, timing, truth = simulate(duration_s=1800.0, drift_ppm=50.0, events_s=events)
    ev = mt.place_events(tsim, timing, correction_ms=correction_for_sim())
    err_ms = (ev.onset_s.to_numpy() - truth) * 1000
    assert np.abs(err_ms).max() < 1.0                   # one per-session base would be 90 ms off at the end


def test_session_qc_flags_lasting_backlog_only():
    tsim, timing, _ = simulate(stall=(60.0, 0.3, False))
    qc = mt.session_qc(tsim, timing)
    assert qc["stalls_over_100ms"] == 1
    assert qc["lasting_backlog_ms"] > mt.MAX_LASTING_BACKLOG_MS

    tsim, timing, _ = simulate(stall=(60.0, 0.3, True))
    qc = mt.session_qc(tsim, timing)
    assert qc["stalls_over_100ms"] == 1
    assert qc["lasting_backlog_ms"] < mt.MAX_LASTING_BACKLOG_MS


def test_edges_without_timestamp_are_dropped_with_warning():
    tsim, timing, _ = simulate(events_s=[20.0, 30.0])
    e = np.flatnonzero(timing[:, 1])
    timing[e[0], 2] = np.nan
    with pytest.warns(UserWarning):
        ev = mt.place_events(tsim, timing)
    assert len(ev) == 1


def test_to_mne_events():
    tsim, timing, _ = simulate(events_s=[20.0, 30.0, 40.0])
    ev = mt.place_events(tsim, timing)
    arr = mt.to_mne_events(ev, codes=[11, 13])
    assert arr.shape == (2, 3)
    assert list(arr[:, 2]) == [11, 13]
    assert np.all(arr[:, 1] == 0)
