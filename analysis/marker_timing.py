"""Marker-timing correction for vMMR EEG recordings (g.HIamp + Simulink + LSL).

Places every LSL marker of a recording on the EEG time axis by its LSL send timestamp
and adds the calibrated display delay, so each event time is the moment the stimulus
light appears at the screen centre.

    from marker_timing import correct_events
    events, qc = correct_events("main_..._run01.mat")            # needs ..._LSLtiming.mat next to it
    events[["code", "onset_s", "sample"]]                         # corrected time / EEG row index

Command line:
    .venv/Scripts/python analysis/marker_timing.py <recording.mat> [--run-info <B run_info.txt>] [--out events.csv]

How an event is placed (docs/supplement_marker_timing_calibration_2026-10-15.docx, S1.4):
    lag(k)   = t_A(k) - tau(k)               A's LSL clock minus EEG model time, every step k
    B        = 90th percentile of lag within +-10 s of the event (local upper envelope)
    onset    = t_B + offset_BA - B + CORRECTION_MS
t_B (send timestamp on computer B), offset_BA (LSL time_correction) and t_A come from the
LSLMarkerTimestamps block (matlab/on_eeg_computer/), saved as <recording>_LSLtiming.mat.
The constant CORRECTION_MS was estimated with exactly this mapping; do not combine it with
another mapping (e.g. the marker channel recorded by the g.HIsys LSL Receive block).

Validity: stimuli at the screen centre, the configuration in docs/lab_guide_marker_timing_2026-10.docx
(display 59.94 Hz, LSL 600 Hz, g.HIamp 600 Hz frame length 8, sender v1). Bottom-right corner
stimuli appear ~2 ms later.
"""
import argparse
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

# --- calibration result (22 sessions, 14-15 Oct 2026; analysis/calibration_database_analysis.py)
CORRECTION_MS = 62.4          # light at screen centre after the timestamp-placed marker
CORRECTION_CI95_MS = (61.7, 63.0)
CORRECTION_PI95_MS = (59.4, 65.3)   # expected range for a single new session

# --- clock mapping (must match the calibration) --------------------------------------
BASE_PERCENTILE = 90
BASE_HALF_WINDOW_S = 10.0
SKIP_START_S = 1.0            # model start-up, left out of the lag statistics

# --- quality control -------------------------------------------------------------------
STALL_MS = 100                # a model step longer than this is a stall
MAX_LASTING_BACKLOG_MS = 5.0  # a stall that is not caught up shifts the mapping -> session flagged
TIMING_COLS = ["marker", "edge_code", "edge_ts_B", "offset", "t_A", "n_pulled"]


# =============================================================================
# File loading
# =============================================================================

def load_columns(path, columns=(0, -2, -1)):
    """Selected columns of EEG_data (samples x len(columns)); default: model time,
    optical sensor, marker. Reads only those columns (files can be > 500 MB)."""
    import h5py
    with h5py.File(path, "r") as f:
        ds = f["EEG_data"]
        if ds.shape[0] < ds.shape[1]:                     # channels x samples
            n_ch = ds.shape[0]
            idx = sorted({c % n_ch for c in columns})
            a = ds[idx, :].T
        else:                                             # samples x channels
            n_ch = ds.shape[1]
            idx = sorted({c % n_ch for c in columns})
            a = ds[:, idx]
    a = np.asarray(a, float)
    return a[:, [idx.index(c % n_ch) for c in columns]]


def load_timing(path, n):
    """LSLMarkerTimestamps output saved by a To File block as a Simulink Timeseries
    (MATLAB v7.3). Returns (model time [n], data [n x 6], columns as TIMING_COLS)."""
    import h5py
    with h5py.File(path, "r") as f:
        refs = f["#refs#"]
        arrays = [refs[k][()] for k in refs
                  if isinstance(refs[k], h5py.Dataset) and refs[k].dtype == np.float64]
    data = np.squeeze(next(a for a in arrays if a.size == 6 * n and 6 in a.shape))
    data = data.T if data.shape == (6, n) else data.reshape(n, 6)
    tsim = next(a.ravel() for a in arrays if a.size == n)
    return tsim, data


def read_run_info(path):
    """Computer-B *_run_info.txt as a dict ("key: value" lines)."""
    path = Path(path)
    if not path.exists():
        return {}
    return dict(l.split(": ", 1) for l in path.read_text(encoding="utf-8").splitlines() if ": " in l)


# =============================================================================
# Clock mapping
# =============================================================================

def lag_ms(tsim, timing):
    """t_A - model time for every model step (ms)."""
    return (timing[:, 4] - tsim) * 1000.0


def local_base_ms(lag, steps, fs, q=BASE_PERCENTILE, half_s=BASE_HALF_WINDOW_S, skip_s=SKIP_START_S):
    """q-th percentile of lag within +-half_s of each step (the clock mapping B)."""
    half, lo = int(round(half_s * fs)), int(round(skip_s * fs))
    return np.array([np.percentile(lag[max(lo, s - half):max(s + half, lo + 1)], q)
                     for s in np.asarray(steps, int)])


def place_events(tsim, timing, correction_ms=CORRECTION_MS):
    """Core of the correction, on arrays (no file access).

    tsim:   model time of every EEG sample (s), = EEG_data column 0
    timing: LSLMarkerTimestamps output, n x 6
    Returns one row per marker edge received by the timestamp block."""
    tsim = np.asarray(tsim, float)
    fs = 1.0 / np.median(np.diff(tsim))
    lag = lag_ms(tsim, timing)
    e = np.flatnonzero(timing[:, 1] != 0)
    ev = pd.DataFrame({"code": timing[e, 1].astype(int), "receive_step": e,
                       "recorded_s": tsim[e], "ts_B": timing[e, 2], "offset_BA": timing[e, 3]})
    ok = np.isfinite(ev.ts_B) & np.isfinite(ev.offset_BA)
    if not ok.all():
        warnings.warn(f"{int((~ok).sum())} marker edges without an LSL timestamp were left out")
    ev = ev[ok].reset_index(drop=True)
    ev["base_ms"] = local_base_ms(lag, ev.receive_step.to_numpy(), fs)
    ev["onset_s"] = ev.ts_B + ev.offset_BA - ev.base_ms / 1000.0 + correction_ms / 1000.0
    ev["sample"] = np.rint((ev.onset_s - tsim[0]) * fs).astype(int)       # EEG_data row index
    ev["shift_vs_recorded_ms"] = (ev.onset_s - ev.recorded_s) * 1000.0
    return ev


def session_qc(tsim, timing):
    """Stalls of the recording model and whether any left a lasting backlog."""
    tsim = np.asarray(tsim, float)
    n, fs = len(tsim), 1.0 / np.median(np.diff(tsim))
    lag = lag_ms(tsim, timing)
    lo = int(round(SKIP_START_S * fs))
    gaps = np.diff(timing[:, 4])
    stall_idx = np.flatnonzero(gaps > STALL_MS / 1000.0)
    w = int(fs)

    def med(i0, i1):
        i0, i1 = max(lo, i0), min(n, i1)
        return np.median(lag[i0:i1]) if i1 > i0 else np.nan

    kept = np.array([med(i + 2 * w, i + 3 * w) - med(i - 2 * w, i - w) for i in stall_idx])
    lasting = float(np.nanmax(np.abs(kept))) if kept.size else 0.0
    t_min = tsim[lo:] / 60.0
    drift = float(np.polyfit(t_min[::60], lag[lo::60], 1)[0]) if n > lo + 600 else np.nan
    return {"duration_min": (tsim[-1] - tsim[0]) / 60, "fs_hz": fs,
            "stalls_over_100ms": int(stall_idx.size),
            "largest_stall_ms": float(gaps[stall_idx].max() * 1000) if stall_idx.size else 0.0,
            "lasting_backlog_ms": lasting, "clock_drift_ms_per_min": drift,
            "lsl_samples_per_s": float(timing[:, 5].sum() / (tsim[-1] - tsim[0]))}


# =============================================================================
# File-level entry point
# =============================================================================

def correct_events(eeg_mat, timing_mat=None, run_info=None, correction_ms=CORRECTION_MS):
    """Corrected event table and QC for one recording.

    eeg_mat:    EEG .mat written by the Simulink model (EEG_data)
    timing_mat: <eeg_mat stem>_LSLtiming.mat by default
    run_info:   optional computer-B *_run_info.txt of the same session (lsl_resyncs check)
    Returns (events, qc). qc["passed"] is False if a check failed; the reasons are in
    qc["problems"] and a warning is issued. Events are returned in any case."""
    eeg_mat = Path(eeg_mat)
    timing_mat = Path(timing_mat) if timing_mat else eeg_mat.with_name(eeg_mat.stem + "_LSLtiming.mat")
    if not timing_mat.exists():
        raise FileNotFoundError(f"{timing_mat.name} not found: the correction needs the LSLMarkerTimestamps output")
    t = load_columns(eeg_mat, columns=(0,))[:, 0]
    tsim, timing = load_timing(timing_mat, len(t))
    if not np.allclose(tsim, t, atol=1e-6):
        raise ValueError("timing file and EEG file have different time axes")
    events = place_events(tsim, timing, correction_ms)
    qc = session_qc(tsim, timing)
    qc.update({"eeg_file": eeg_mat.name, "timing_file": timing_mat.name, "n_events": len(events),
               "correction_ms": correction_ms})
    problems = []
    if qc["lasting_backlog_ms"] > MAX_LASTING_BACKLOG_MS:
        problems.append(f"lasting backlog {qc['lasting_backlog_ms']:.1f} ms after a stall")
    if run_info is not None:
        info = read_run_info(run_info)
        resyncs = info.get("lsl_resyncs")
        qc["lsl_resyncs"] = float(resyncs) if resyncs not in (None, "None") else np.nan
        if not qc["lsl_resyncs"] == 0:
            problems.append(f"lsl_resyncs = {resyncs} on computer B")
    if not len(events):
        problems.append("no marker edges in the timing file")
    qc["problems"] = problems
    qc["passed"] = not problems
    if problems:
        warnings.warn(f"{eeg_mat.name}: " + "; ".join(problems))
    return events, qc


def to_mne_events(events, codes=None):
    """MNE-style event array (sample, 0, code), optionally only the given codes."""
    ev = events if codes is None else events[events.code.isin(codes)]
    return np.column_stack([ev["sample"].to_numpy(), np.zeros(len(ev), int), ev["code"].to_numpy()])


def main():
    ap = argparse.ArgumentParser(description="Corrected event times for one vMMR EEG recording.")
    ap.add_argument("eeg_mat", type=Path)
    ap.add_argument("--timing-mat", type=Path, default=None)
    ap.add_argument("--run-info", type=Path, default=None, help="computer-B *_run_info.txt (lsl_resyncs check)")
    ap.add_argument("--out", type=Path, default=None, help="CSV for the corrected events")
    ap.add_argument("--correction-ms", type=float, default=CORRECTION_MS)
    args = ap.parse_args()
    events, qc = correct_events(args.eeg_mat, args.timing_mat, args.run_info, args.correction_ms)
    out = args.out or args.eeg_mat.with_name(args.eeg_mat.stem + "_events_corrected.csv")
    events.to_csv(out, index=False)
    print(f"{len(events)} events -> {out}")
    print("QC:", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in qc.items()})


if __name__ == "__main__":
    main()
