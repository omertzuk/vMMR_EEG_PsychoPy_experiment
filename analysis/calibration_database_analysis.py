"""Marker-timing calibration database: analysis.

Estimates the constant that maps an LSL marker, placed on the EEG time axis by its LSL
timestamp, to the moment the stimulus light reaches the optical sensor at the screen centre.

Inputs (data/EEG/final database/, see run_manifest.csv there):
    EEG_Computer_A/main_<YYYYMMDD>_fl_<frame length>_sqcenter_<run>.mat
        EEG_data: samples x channels; col 0 = model time (s), col -2 = optical sensor
        (g.TRIGbox -> g.HIamp digital input), col -1 = LSL marker (g.HIsys LSL Receive)
    EEG_Computer_A/<same name>_LSLtiming.mat
        output of matlab/on_eeg_computer/LSLMarkerTimestamps.m, one row per model step:
        [marker, edge_code, edge_ts_B, offset_B->A, t_A, n_pulled]
    Computer_B/*_photodiode_latency_latency_flashes.csv and *_run_info.txt (PsychoPy),
        matched to each recording through identical LSL push timestamps.
Loading and the clock mapping come from marker_timing.py (the correction function).
Validation set (not used to choose the method): the eight 13 October runs in
    data/EEG/finding final config/photodiode_test_20261013_*  (square in the bottom-right corner).

Clock mapping (A's LSL clock -> EEG model time) and the correction, per flash:
    lag(k)   = t_A(k) - model_time(k)       for every model step k
    sent_A   = edge_ts_B + offset            time the marker was pushed on B, on A's clock
    base     = 90th percentile of lag within +-10 s of the flash ("local upper envelope")
    offset_i = photodiode onset (model time) - (sent_A - base)
The amplifier delivers frames of 8 samples; the model steps through a frame in a burst,
so lag varies by up to one frame. Its upper envelope (the first sample of each frame,
which waited a whole frame) tracks the acquisition time, independent of whether the model
runs in bursts or steadily one frame behind, and follows slow drift between the amplifier
and PC clocks. The previous method (one median of lag per run, as in
notebooks/photodiode_latency_compare.ipynb) is reported alongside as "median base".
Detection and pairing follow the compare notebook (cells 1 and 3).

Output (data/analysis/calibration_database/, git-ignored):
    runs.csv, flashes.csv, model_lag.csv, summary.json, figures/*.png

Run:  .venv/Scripts/python analysis/calibration_database_analysis.py [--extra-path <h5py dir>]
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import marker_timing as mt                                  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DB_ROOT = REPO / "data" / "EEG" / "final database"
DB_DIR = DB_ROOT / "EEG_Computer_A"                         # EEG + _LSLtiming .mat from computer A
VAL_DIR = REPO / "data" / "EEG" / "finding final config"
VAL_GLOB = "photodiode_test_20261013_*_timestamped_LSL_*expstart.mat"
PSYCHOPY_DIRS = [DB_ROOT / "Computer_B", REPO / "data"]    # PsychoPy output (database runs, then the rest)
OUT_DIR = REPO / "data" / "analysis" / "calibration_database"

# --- recording layout and stimulus parameters (as in the compare notebook) -----------
MARKER_CH, PHOTO_CH = -1, -2
FLASH_CODE, BLOCK_CODE = 20, 7
EXP_START_CODE = 1
RAMP_CYCLE = 100          # duration ramp repeats every 100 flashes (on_cycle 100; = no repeat for 100-flash runs)
ON_START_MS = 100.0
ON_STEP_MS = 1000 / 60    # one display frame after rounding (16.68 ms at 59.94 Hz)
MAX_GAP = 0.030           # s; gaps shorter than this inside a pulse are bridged
MIN_PULSE = 0.030         # s; pulses shorter than this are ignored
OUTLIER_MS = 150          # paired delays further than this from the run trend are left out
STALL_MS = 100            # a model step longer than this counts as a stall (normal: 1.67 ms)

# --- clock mapping (defined in marker_timing.py) -------------------------------------
BASE_PERCENTILE = mt.BASE_PERCENTILE         # upper envelope of t_A - model time
BASE_HALF_WINDOW_S = mt.BASE_HALF_WINDOW_S   # window around each event
SKIP_START_S = mt.SKIP_START_S               # model start-up, left out of the lag statistics
SCAN_PERCENTILES = [50, 75, 80, 85, 88, 90, 92, 95, 97]

# --- exclusion rules, fixed before the database was recorded (database plan, Table 4) --
MAX_RESYNCS = 0
MAX_BACKLOG_MS = 5.0
MIN_PAIRED_FRAC = 0.95
MAX_DROPPED_FRAC = 0.01

DB_RE = re.compile(r"main_(\d{8})_fl_(\d+)_sqcenter_(run(?:_long|_full_exp_length)?_?(\d+))")
VAL_RE = re.compile(r"photodiode_test_(\d{8})_(\d+)_slx_frame_length_(\d+)")


# =============================================================================
# Loading and clock mapping: shared with the correction function (marker_timing.py),
# so the calibration and the correction of experimental data use identical code.
# =============================================================================

def load_columns(path):
    """Model time, photodiode and marker columns only (the full file can be > 500 MB)."""
    return mt.load_columns(path, columns=(0, PHOTO_CH, MARKER_CH))


load_timing = mt.load_timing
read_run_info = mt.read_run_info


# =============================================================================
# Detection and pairing (notebooks/photodiode_latency_compare.ipynb, cell 3)
# =============================================================================

def pulses(mask, t, fs):
    d = np.diff(np.r_[0, mask.astype(int), 0])
    on, off = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    if on.size == 0:
        return pd.DataFrame({"onset_s": [], "width_ms": []})
    keep = np.r_[True, (on[1:] - off[:-1]) / fs > MAX_GAP]
    on, off = on[keep], off[np.r_[keep[1:], True]]
    ok = (off - on) / fs >= MIN_PULSE
    return pd.DataFrame({"onset_s": t[on[ok]], "width_ms": (off[ok] - on[ok]) / fs * 1000})


def ramp_score(p):
    dw = np.diff(p.width_ms)
    return np.mean((dw > 0.3 * ON_STEP_MS) & (dw < 1.8 * ON_STEP_MS)) if len(dw) else 0.0


def trend(m):
    keep = np.ones(len(m), bool)
    for _ in range(3):
        c = np.polyfit(m.onset_s_mk[keep], m.delay_ms[keep], 1)
        r = m.delay_ms - np.polyval(c, m.onset_s_mk)
        mad = 1.4826 * np.median(np.abs(r - np.median(r))) + 1e-9
        keep = (np.abs(r - np.median(r)) < 4 * mad).to_numpy()
    return c, r, mad


def detect(t, fs, marker, photo_raw):
    codes = [c for c in np.unique(marker) if c != 0]
    ev = pd.concat([pulses(marker == c, t, fs).assign(code=c) for c in codes]) \
        .sort_values("onset_s").reset_index(drop=True)
    t_exp = ev.loc[ev.code == EXP_START_CODE, "onset_s"].min()
    if np.isfinite(t_exp):
        ev = ev[ev.onset_s >= t_exp].reset_index(drop=True)
    mk = ev[ev.code == FLASH_CODE].reset_index(drop=True)
    mk["flash"] = np.arange(1, len(mk) + 1)
    mk["ramp"] = (mk.flash - 1) % RAMP_CYCLE + 1
    mk["intended_ms"] = ON_START_MS + (mk.ramp - 1) * ON_STEP_MS
    t_block = ev.loc[ev.code == BLOCK_CODE, "onset_s"].min()
    if np.isnan(t_block):
        t_block = t[0]
    thr = (photo_raw.min() + photo_raw.max()) / 2
    photo_hi = photo_raw > thr
    max_w = mk.intended_ms.max() * 1.6

    def flash_pulses(mask):
        p = pulses(mask, t, fs)
        return p[(p.onset_s > t_block) & (p.width_ms <= max_w)].reset_index(drop=True)

    cands = {"HIGH": flash_pulses(photo_hi), "LOW": flash_pulses(~photo_hi)}
    scores = {k: ramp_score(v) for k, v in cands.items()}
    pol = max(scores, key=scores.get)
    return ev, mk, cands[pol], pol, t_exp


def pair_flashes(mk, pdp):
    """Order pairing: one photodiode pulse per marker and the widths follow the markers
    (r > 0.99) -> the n-th pulse is flash n. (The notebook's width-numbering fallback is
    not used; a run that cannot be paired in order is reported as such.)"""
    r_w = np.corrcoef(pdp.width_ms, mk.width_ms)[0, 1] if len(pdp) == len(mk) else np.nan
    if not r_w > 0.99:
        raise ValueError(f"cannot pair in order: {len(pdp)} pulses for {len(mk)} markers, r = {r_w}")
    pairs = pdp.assign(flash=mk.flash.to_numpy()).merge(
        mk[["flash", "onset_s", "width_ms", "intended_ms"]], on="flash", suffixes=("_pd", "_mk"))
    pairs["delay_ms"] = (pairs.onset_s_pd - pairs.onset_s_mk) * 1000
    c, res, mad = trend(pairs)
    outliers = pairs[np.abs(res) > OUTLIER_MS]
    return pairs[np.abs(res) <= OUTLIER_MS].reset_index(drop=True), outliers, r_w


# =============================================================================
# LSL timestamps and clock mapping
# =============================================================================

def analyze_timing(timing_path, t, fs, pairs):
    n = len(t)
    tsim, d = load_timing(timing_path, n)
    assert np.allclose(tsim, t, atol=1e-6), "timing file and EEG file have different time axes"
    tA, off = d[:, 4], d[:, 3]
    lag_ms = (tA - tsim) * 1000
    gaps = np.diff(tA)
    stall_idx = np.flatnonzero(gaps > STALL_MS / 1000)
    lo = int(SKIP_START_S * fs)
    first = stall_idx[0] if stall_idx.size else n - 1
    base_med = np.median(lag_ms[min(lo, first // 2):first + 1])     # previous method: one value per run
    rel = lag_ms - base_med
    w = int(fs)

    def med(i0, i1):
        i0, i1 = max(0, i0), min(n, i1)
        return np.median(rel[i0:i1]) if i1 > i0 else np.nan

    stalls = pd.DataFrame({"sim_s": tsim[stall_idx], "gap_ms": gaps[stall_idx] * 1000,
                           "kept_ms": [med(i + 2 * w, i + 3 * w) - med(i - 2 * w, i - w) for i in stall_idx]})

    e = np.flatnonzero(d[:, 1] != 0)
    edges = pd.DataFrame({"step": e, "code": d[e, 1].astype(int), "ts_B": d[e, 2], "sent_A": d[e, 2] + off[e]})
    p = pairs.sort_values("flash").reset_index(drop=True)
    s_mk = np.searchsorted(t, p.onset_s_mk.to_numpy())
    s_pd = np.searchsorted(t, p.onset_s_pd.to_numpy())
    fl = edges[edges.code == FLASH_CODE].reset_index(drop=True)
    fsteps = fl.step.to_numpy()
    j = np.abs(fsteps[None, :] - s_mk[:, None]).argmin(axis=1)
    ok = np.abs(fsteps[j] - s_mk) < 0.2 * fs
    f = fl.iloc[j].reset_index(drop=True)
    raw_ms = (t[s_pd] - f.sent_A.to_numpy()) * 1000                    # photodiode - sent, before mapping
    base_loc = mt.local_base_ms(lag_ms, s_pd, fs)                     # BASE_PERCENTILE within +-10 s
    flash = pd.DataFrame({
        "flash": p.flash.to_numpy(), "onset_s": p.onset_s_mk.to_numpy(),
        "width_ms_pd": p.width_ms_pd.to_numpy(), "intended_ms": p.intended_ms.to_numpy(),
        "transit_ms": (tA[f.step] - f.sent_A) * 1000,
        "delay_ms": p.delay_ms.to_numpy(),                             # photodiode - recorded marker
        "backlog_ms": [med(s - w // 10, s + w // 10) for s in s_mk],
        "base_local_ms": base_loc,
        "offset_ms": raw_ms + base_loc,                                # primary: local upper envelope
        "offset_median_base_ms": raw_ms + base_med,                    # previous method
        "ts_B": f.ts_B.to_numpy()})[ok].reset_index(drop=True)
    scan = {q: float(np.mean(raw_ms[ok] + mt.local_base_ms(lag_ms, s_pd[ok], fs, q=q)))
            for q in SCAN_PERCENTILES}
    lag_trace = pd.DataFrame({"sim_s": tsim[lo::60], "lag_rel_ms": rel[lo::60]})
    lag_stats = {"lag_iqr_ms": float(np.subtract(*np.percentile(lag_ms[lo:], [75, 25]))),
                 "lag_p90_minus_p10_ms": float(np.subtract(*np.percentile(lag_ms[lo:], [90, 10]))),
                 "lag_hist": np.histogram(rel[lo:], bins=np.arange(-20, 30.5, 0.5))[0].tolist()}
    rate = d[:, 5].sum() / (tsim[-1] - tsim[0])
    return flash, stalls, lag_trace, lag_stats, scan, rate


def match_psychopy(ts_B, csvs):
    """The PsychoPy run on computer B whose flash timestamps equal the received ones."""
    for path, c in csvs.items():
        k = int(np.isin(np.round(c.lsl_push_timestamp.to_numpy(), 6), np.round(ts_B, 6)).sum())
        if k:
            info = read_run_info(path.with_name(path.name.replace("_latency_flashes.csv", "_run_info.txt")))
            return path, c, k, info
    return None, None, 0, {}


# =============================================================================
# One run
# =============================================================================

def parse_name(path):
    m = DB_RE.search(path.stem)
    if m:
        run_name = m.group(3)
        run_type = "full" if "full_exp_length" in run_name else "long" if "long" in run_name else "short"
        return {"set": "database", "date": m.group(1), "frame_length": int(m.group(2)),
                "run_type": run_type, "run_no": int(m.group(4)), "square": "centre"}
    m = VAL_RE.search(path.stem)
    return {"set": "validation", "date": m.group(1), "frame_length": int(m.group(3)),
            "run_type": "short", "run_no": int(m.group(2)), "square": "corner"}


def analyze_run(path, csvs):
    meta = parse_name(path)
    a = load_columns(path)
    t, photo, marker = a[:, 0], a[:, 1], np.rint(a[:, 2]).astype(int)
    fs = 1.0 / np.median(np.diff(t))
    ev, mk, pdp, pol, t_exp = detect(t, fs, marker, photo)
    pairs, outliers, r_w = pair_flashes(mk, pdp)
    timing = path.with_name(path.stem + "_LSLtiming.mat")
    flash, stalls, lag_trace, lag_stats, scan, lsl_rate = analyze_timing(timing, t, fs, pairs)

    csv_path, csv, n_match, info = match_psychopy(flash.ts_B.to_numpy(), csvs)
    dropped = int(csv.dropped_frames_delta.sum()) if csv is not None else np.nan
    n_frames_shown = int((csv.on_frames + csv.off_frames).sum()) if csv is not None else np.nan
    x_min = (flash.onset_s - flash.onset_s.iloc[0]) / 60

    def fit(y):
        c = np.polyfit(x_min, y, 1)
        return c[0], y - np.polyval(c, x_min)

    slope, detr = fit(flash.offset_ms)
    slope_med, _ = fit(flash.offset_median_base_ms)
    run_id = f"{meta['date']}_{meta['run_type']}_{meta['run_no']:02d}" if meta["set"] == "database" \
        else f"{meta['date']}_corner_{meta['run_no']}_fl{meta['frame_length']}"
    row = {
        "run_id": run_id, "file": path.name, **meta,
        "duration_min": (t[-1] - t[0]) / 60, "fs_hz": fs, "polarity_on": pol,
        "exp_start_found": bool(np.isfinite(t_exp)),
        "flash_markers": len(mk), "photodiode_pulses": len(pdp), "width_r": r_w,
        "paired": len(pairs), "left_out": len(outliers), "with_timestamp": len(flash),
        "paired_frac": len(flash) / len(mk),
        "offset_mean_ms": flash.offset_ms.mean(), "offset_median_ms": flash.offset_ms.median(),
        "offset_sd_ms": flash.offset_ms.std(), "offset_sd_detrended_ms": detr.std(),
        "offset_drift_ms_per_min": slope,
        "offset_first100_ms": flash.offset_ms.iloc[:100].mean(),
        "offset_last100_ms": flash.offset_ms.iloc[-100:].mean(),
        "offset_medbase_mean_ms": flash.offset_median_base_ms.mean(),
        "offset_medbase_drift_ms_per_min": slope_med,
        "delay_mean_ms": flash.delay_ms.mean(), "delay_sd_ms": flash.delay_ms.std(),
        "transit_mean_ms": flash.transit_ms.mean(), "transit_max_ms": flash.transit_ms.max(),
        "lag_iqr_ms": lag_stats["lag_iqr_ms"],
        "base_local_range_ms": flash.base_local_ms.max() - flash.base_local_ms.min(),
        "backlog_ms": flash.backlog_ms.median(), "stalls_over_100ms": len(stalls),
        "stalls_kept_over_50ms": int((stalls.kept_ms > 50).sum()) if len(stalls) else 0,
        "largest_stall_ms": stalls.gap_ms.max() if len(stalls) else 0.0,
        "lsl_samples_per_s_received": lsl_rate,
        "psychopy_csv": csv_path.name if csv_path else None, "timestamps_matched": n_match,
        "lsl_resyncs": float(info.get("lsl_resyncs", "nan")),
        "lsl_rate_hz_sent": float(info.get("lsl_rate_hz", "nan")),
        "measured_refresh_hz": float(info.get("measured_refresh_hz", "nan")),
        "n_flashes_dialog": int(info.get("n_flashes", 0) or 0),
        "on_cycle": info.get("on_cycle", "0 (field absent)"), "script": info.get("script"),
        "dropped_frames": dropped,
        "dropped_frac": dropped / n_frames_shown if csv is not None else np.nan,
        **{f"scan_q{q}_ms": v for q, v in scan.items()},
    }
    flash = flash.assign(run_id=run_id, set=meta["set"], date=meta["date"], run_type=meta["run_type"],
                         t_min=x_min.to_numpy(), offset_detrended_ms=detr.to_numpy())
    return row, flash, lag_trace.assign(run_id=run_id), lag_stats["lag_hist"]


def exclusion_reasons(r):
    why = []
    if not r["lsl_resyncs"] <= MAX_RESYNCS:
        why.append(f"lsl_resyncs {r['lsl_resyncs']}")
    if not abs(r["backlog_ms"]) <= MAX_BACKLOG_MS:
        why.append(f"backlog {r['backlog_ms']:.1f} ms")
    if not r["paired_frac"] >= MIN_PAIRED_FRAC:
        why.append(f"paired {r['paired_frac']:.0%}")
    if not r["dropped_frac"] <= MAX_DROPPED_FRAC:
        why.append(f"dropped frames {r['dropped_frac']:.1%}")
    if r["n_flashes_dialog"] and r["flash_markers"] != r["n_flashes_dialog"]:
        why.append(f"incomplete ({r['flash_markers']}/{r['n_flashes_dialog']} flashes)")
    return "; ".join(why)


# =============================================================================
# Database statistics
# =============================================================================

def summary_stats(x):
    from scipy import stats
    x = np.asarray(x, float)
    n, mean, sd = len(x), x.mean(), x.std(ddof=1)
    tq = stats.t.ppf(0.975, n - 1)
    return {"n": n, "mean": mean, "sd": sd, "sem": sd / np.sqrt(n), "median": float(np.median(x)),
            "min": x.min(), "max": x.max(),
            "ci95": [mean - tq * sd / np.sqrt(n), mean + tq * sd / np.sqrt(n)],
            "pi95": [mean - tq * sd * np.sqrt(1 + 1 / n), mean + tq * sd * np.sqrt(1 + 1 / n)]}


def error_stats(e):
    return {"n": int(len(e)), "mean": e.mean(), "sd": e.std(), "p2.5": e.quantile(0.025), "p97.5": e.quantile(0.975),
            "within_5ms": (e.abs() <= 5).mean(), "within_10ms": (e.abs() <= 10).mean(),
            "within_1frame": (e.abs() <= 1000 / 59.94).mean(), "max_abs": e.abs().max()}


def database_stats(runs, flashes):
    from scipy import stats
    v = runs[(runs.set == "database") & runs.included]
    s = {"n_runs_total": int((runs.set == "database").sum()), "n_runs_included": len(v),
         "n_runs_excluded": int(((runs.set == "database") & ~runs.included).sum()),
         "n_flashes_included": int(flashes.run_id.isin(v.run_id).sum()),
         "method": {"base_percentile": BASE_PERCENTILE, "half_window_s": BASE_HALF_WINDOW_S},
         "correction": summary_stats(v.offset_mean_ms),
         "correction_median_base": summary_stats(v.offset_medbase_mean_ms),
         "recorded_marker": summary_stats(v.delay_mean_ms),
         "within_run_sd_ms": float(np.sqrt(np.mean(v.offset_sd_ms ** 2))),
         "within_run_sd_detrended_ms": float(np.sqrt(np.mean(v.offset_sd_detrended_ms ** 2))),
         "within_run_sd_recorded_marker_ms": float(np.sqrt(np.mean(v.delay_sd_ms ** 2)))}
    c = s["correction"]["mean"]

    fv = flashes[flashes.run_id.isin(v.run_id)].copy()
    loo = {rid: v[v.run_id != rid].offset_mean_ms.mean() for rid in v.run_id}
    loo_med = {rid: v[v.run_id != rid].offset_medbase_mean_ms.mean() for rid in v.run_id}
    loo_rec = {rid: v[v.run_id != rid].delay_mean_ms.mean() for rid in v.run_id}
    fv["err_ms"] = fv.offset_ms - c
    fv["err_loo_ms"] = fv.offset_ms - fv.run_id.map(loo)
    fv["err_loo_median_base_ms"] = fv.offset_median_base_ms - fv.run_id.map(loo_med)
    fv["err_loo_recorded_ms"] = fv.delay_ms - fv.run_id.map(loo_rec)
    s["flash_error"] = error_stats(fv.err_ms)
    s["flash_error_loo"] = error_stats(fv.err_loo_ms)
    s["flash_error_loo_median_base"] = error_stats(fv.err_loo_median_base_ms)
    s["flash_error_loo_recorded_marker"] = error_stats(fv.err_loo_recorded_ms)
    run_loo = np.array([v.offset_mean_ms[v.run_id == rid].iloc[0] - loo[rid] for rid in v.run_id])
    s["run_error_loo"] = {"sd": run_loo.std(ddof=1), "max_abs": np.abs(run_loo).max()}

    days = sorted(v.date.unique())
    if len(days) == 2:
        a, b = (v[v.date == d].offset_mean_ms for d in days)
        tt = stats.ttest_ind(a, b, equal_var=False)
        s["day_effect"] = {"days": days, "n": [len(a), len(b)], "mean": [a.mean(), b.mean()],
                           "sd": [a.std(), b.std()], "diff_ms": b.mean() - a.mean(),
                           "welch_t": tt.statistic, "p": tt.pvalue}
    s["by_run_type"] = {k: {"n": len(g), "mean": g.offset_mean_ms.mean(), "sd": g.offset_mean_ms.std(),
                            "within_sd": float(np.sqrt(np.mean(g.offset_sd_ms ** 2)))}
                        for k, g in v.groupby("run_type")}
    sh, lg = v[v.run_type == "short"].offset_mean_ms, v[v.run_type != "short"].offset_mean_ms
    if len(sh) > 1 and len(lg) > 1:
        s["short_vs_long_welch_p"] = stats.ttest_ind(sh, lg, equal_var=False).pvalue
    lr = v[v.run_type != "short"].set_index("run_id")
    s["long_runs"] = {rid: {"duration_min": r.duration_min, "drift_ms_per_min": r.offset_drift_ms_per_min,
                            "last100_minus_first100_ms": r.offset_last100_ms - r.offset_first100_ms,
                            "drift_median_base_ms_per_min": r.offset_medbase_drift_ms_per_min,
                            "base_local_range_ms": r.base_local_range_ms}
                      for rid, r in lr.iterrows()}
    s["transit_ms"] = {"mean": v.transit_mean_ms.mean(), "min_run": v.transit_mean_ms.min(),
                       "max_run": v.transit_mean_ms.max(), "max_flash": v.transit_max_ms.max()}
    s["corr_with_transit"] = {k: float(np.corrcoef(v[k], v.transit_mean_ms)[0, 1])
                              for k in ("offset_mean_ms", "offset_medbase_mean_ms", "delay_mean_ms")}
    s["percentile_scan"] = {q: {"mean": v[f"scan_q{q}_ms"].mean(), "between_sd": v[f"scan_q{q}_ms"].std()}
                            for q in SCAN_PERCENTILES}
    s["stalls"] = {"runs_with_stall": int((v.stalls_over_100ms > 0).sum()),
                   "total": int(v.stalls_over_100ms.sum()), "largest_ms": v.largest_stall_ms.max(),
                   "kept_over_50ms": int(v.stalls_kept_over_50ms.sum())}
    s["dropped_frames_total"] = int(v.dropped_frames.sum())
    s["refresh_hz"] = {"min": v.measured_refresh_hz.min(), "max": v.measured_refresh_hz.max()}
    s["lsl_rate_sent_hz"] = {"min": v.lsl_rate_hz_sent.min(), "max": v.lsl_rate_hz_sent.max()}

    val = runs[(runs.set == "validation") & runs.included]
    if len(val):
        s["validation_corner"] = {
            "n": len(val), "offset": summary_stats(val.offset_mean_ms),
            "offset_median_base": summary_stats(val.offset_medbase_mean_ms),
            "by_frame_length": {int(k): {"n": len(g), "mean": g.offset_mean_ms.mean(), "sd": g.offset_mean_ms.std(),
                                         "median_base_sd": g.offset_medbase_mean_ms.std()}
                                for k, g in val.groupby("frame_length")},
            "corner_minus_centre_ms": val.offset_mean_ms.mean() - c,
            "corner_minus_centre_welch_p": stats.ttest_ind(val.offset_mean_ms, v.offset_mean_ms,
                                                           equal_var=False).pvalue}
    return s, fv


# =============================================================================
# Figures
# =============================================================================

def figures(runs, fv, lags, hists, s, fig_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 8.5, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titlesize": 9, "legend.fontsize": 7.5})
    BLUE, ORANGE, AQUA, GREY = "#2a6fdb", "#e8833a", "#1aa3a3", "#8a8f98"
    v = runs[(runs.set == "database") & runs.included].reset_index(drop=True)
    c = s["correction"]
    type_col = {"short": BLUE, "long": ORANGE, "full": AQUA}
    type_lab = {"short": "short run (100 flashes)", "long": "long run (400)", "full": "full-length run (1200)"}

    # Fig 1: per-run offset, both clock mappings
    fig, axs = plt.subplots(2, 1, figsize=(7.0, 4.6), sharex=True)
    for ax, col, title, st in ((axs[0], "offset_medbase_mean_ms", "A  Per-run median clock mapping",
                                s["correction_median_base"]),
                               (axs[1], "offset_mean_ms", "B  Local upper-envelope clock mapping (adopted)", c)):
        sdcol = "offset_sd_ms"
        for i, r in v.iterrows():
            ax.errorbar(i, r[col], yerr=r[sdcol], fmt="o", ms=4.5, capsize=2, lw=0.9, color=type_col[r.run_type])
        ax.axhline(st["mean"], color="k", lw=0.9)
        ax.axhspan(*st["ci95"], color=GREY, alpha=0.4, lw=0)
        ax.axhspan(*st["pi95"], color=GREY, alpha=0.13, lw=0)
        ax.axvline((v.date == v.date.iloc[0]).sum() - 0.5, color=GREY, ls=":", lw=1)
        ax.set_ylabel("offset (ms)")
        ax.set_title(f"{title}: {st['mean']:.1f} ms, between-run SD {st['sd']:.1f} ms", loc="left")
        ax.set_ylim(35, 80)
    axs[1].set_xticks(range(len(v)))
    axs[1].set_xticklabels([f"{r.run_type[0].upper()}{r.run_no}" for r in v.itertuples()], fontsize=7)
    axs[1].set_xlabel(f"run (S short, L long, F full length); dotted line separates "
                      f"{v.date.iloc[0][6:]} and {v.date.iloc[-1][6:]} October")
    for k in type_col:
        axs[1].plot([], [], "o", color=type_col[k], label=type_lab[k])
    axs[1].fill_between([], [], color=GREY, alpha=0.4, label="95 % CI of the mean")
    axs[1].fill_between([], [], color=GREY, alpha=0.13, label="95 % prediction interval")
    axs[1].legend(ncol=3, loc="lower center", frameon=False)          # panel B is empty below 55 ms
    fig.tight_layout(); fig.savefig(fig_dir / "fig1_offset_per_run.png", dpi=220); plt.close(fig)

    # Fig 2: mechanism. A: lag distributions; B: run offset vs transit for three methods
    fig, axs = plt.subplots(1, 2, figsize=(7.0, 2.9))
    edges = np.arange(-20, 30.5, 0.5)
    steady = v.sort_values("lag_iqr_ms").iloc[0].run_id
    bursty = v.sort_values("lag_iqr_ms").iloc[-1].run_id
    for rid, col, lab in ((steady, BLUE, "steady run"), (bursty, ORANGE, "bursty run")):
        h = np.array(hists[rid], float)
        axs[0].step(edges[:-1], h / h.sum(), where="post", color=col, label=f"{lab} ({rid})")
    axs[0].set_xlim(-10, 20)
    axs[0].set_xlabel("t_A − model time, relative to run median (ms)")
    axs[0].set_ylabel("share of model steps")
    axs[0].set_title("A  Model-step timing within a run", loc="left")
    axs[0].legend(frameon=False)
    for col, lab, colr in (("delay_mean_ms", "recorded marker", GREY),
                           ("offset_medbase_mean_ms", "timestamp, median mapping", ORANGE),
                           ("offset_mean_ms", "timestamp, upper envelope", BLUE)):
        axs[1].scatter(v.transit_mean_ms, v[col], s=14, color=colr, label=lab)
    axs[1].set_xlabel("mean LSL transit B → model step (ms)")
    axs[1].set_ylabel("run mean offset (ms)")
    axs[1].set_title("B  Dependence on the run's timing state", loc="left")
    axs[1].legend(frameon=False, loc="lower left")
    fig.tight_layout(); fig.savefig(fig_dir / "fig2_mechanism.png", dpi=220); plt.close(fig)

    # Fig 3: per-flash error after the constant (leave-one-run-out) + within-run jitter
    fig, axs = plt.subplots(1, 2, figsize=(7.0, 2.8))
    e = s["flash_error_loo"]
    axs[0].hist(fv.err_loo_ms, bins=np.arange(-25, 25.5, 1000 / 600), color=BLUE, edgecolor="white", lw=0.3)
    for q in (e["p2.5"], e["p97.5"]):
        axs[0].axvline(q, color="k", ls="--", lw=0.8)
    axs[0].set_xlabel("photodiode onset − corrected marker (ms)")
    axs[0].set_ylabel("flashes")
    axs[0].set_title(f"A  {e['n']} flashes: SD {e['sd']:.1f} ms, {e['within_10ms']:.0%} within ±10 ms", loc="left")
    for rid, g in fv.groupby("run_id"):
        axs[1].plot(np.sort(g.offset_detrended_ms), np.linspace(0, 1, len(g)), color=GREY, lw=0.5, alpha=0.6)
    axs[1].set_xlabel("deviation from the run's own trend (ms)")
    axs[1].set_ylabel("cumulative share")
    axs[1].set_xlim(-20, 20)
    axs[1].set_title(f"B  Within-run jitter, each run (SD {s['within_run_sd_detrended_ms']:.1f} ms)", loc="left")
    fig.tight_layout(); fig.savefig(fig_dir / "fig3_error_distribution.png", dpi=220); plt.close(fig)

    # Fig 4: long and full-length runs over time, both mappings
    lr = v[v.run_type != "short"]
    fig, axs = plt.subplots(len(lr), 1, figsize=(7.0, 1.45 * len(lr) + 0.5), sharey=True, squeeze=False)
    for ax, r in zip(axs[:, 0], lr.itertuples()):
        f = fv[fv.run_id == r.run_id]
        ax.plot(f.t_min, f.offset_median_base_ms.rolling(50, center=True).mean(), color=ORANGE, lw=1,
                label="median mapping (50-flash mean)")
        ax.plot(f.t_min, f.offset_ms, ".", ms=1.6, color=BLUE, alpha=0.5)
        ax.plot(f.t_min, f.offset_ms.rolling(50, center=True).mean(), color="k", lw=1,
                label="upper-envelope mapping (50-flash mean)")
        ax.axhline(c["mean"], color=GREY, lw=0.8, ls="--")
        ax.set_title(f"{r.run_id} ({r.duration_min:.0f} min): drift {r.offset_drift_ms_per_min:+.2f} ms/min "
                     f"(median mapping {r.offset_medbase_drift_ms_per_min:+.2f})", loc="left", fontsize=8)
        ax.set_ylabel("ms")
        ax.set_ylim(35, 85)
    axs[0, 0].legend(frameon=False, loc="upper right", ncol=2)
    axs[-1, 0].set_xlabel("time from first flash (min)")
    fig.tight_layout(); fig.savefig(fig_dir / "fig4_long_runs.png", dpi=220); plt.close(fig)

    # Fig 5: model time vs real time per run
    fig, ax = plt.subplots(figsize=(7.0, 2.4))
    slopes = []
    for rid, g in lags[lags.run_id.isin(v.run_id)].groupby("run_id"):
        rt = v.loc[v.run_id == rid, "run_type"].iloc[0]
        y = g.lag_rel_ms.rolling(50, center=True).median()
        y = y - y.iloc[25:125].median()                                 # relative to the run's first 10 s
        slopes.append(np.polyfit(g.sim_s / 60, g.lag_rel_ms, 1)[0])
        ax.plot(g.sim_s / 60, y, lw=0.7, color=type_col[rt], alpha=0.8)
    ax.set_xlabel("model time (min)")
    ax.set_ylabel("change in t_A − model time\n(ms, 5-s running median)")
    ax.set_title(f"No lasting backlog; median slope {np.median(slopes):.2f} ms/min "
                 f"(≈ {np.median(slopes) / 60 * 1000:.0f} ppm drift, amplifier vs PC clock)", loc="left")
    fig.tight_layout(); fig.savefig(fig_dir / "fig5_model_lag.png", dpi=220); plt.close(fig)

    # Fig 6: sensitivity to the percentile + validation set
    fig, axs = plt.subplots(1, 2, figsize=(7.0, 2.6))
    qs = list(s["percentile_scan"])
    axs[0].plot(qs, [s["percentile_scan"][q]["between_sd"] for q in qs], "o-", color=BLUE)
    axs[0].axvline(BASE_PERCENTILE, color=GREY, ls=":")
    axs[0].set_xlabel("percentile of t_A − model time used as base")
    axs[0].set_ylabel("between-run SD (ms)")
    axs[0].set_title("A  Choice of the envelope percentile", loc="left")
    val = runs[(runs.set == "validation") & runs.included]
    if len(val):
        for i, (col, lab, colr) in enumerate((("offset_medbase_mean_ms", "median mapping", ORANGE),
                                              ("offset_mean_ms", "upper envelope", BLUE))):
            for fl_, mk in ((4, "s"), (8, "o")):
                g = val[val.frame_length == fl_]
                axs[1].scatter(np.full(len(g), i) + (fl_ - 6) * 0.06, g[col], marker=mk, color=colr, s=16,
                               label=f"frame length {fl_}" if i == 1 else None)
        axs[1].set_xticks([0, 1]); axs[1].set_xticklabels(["median mapping", "upper envelope"])
        axs[1].set_xlim(-0.5, 1.5)
        axs[1].set_ylabel("run mean offset (ms)")
        axs[1].legend(frameon=False)
        axs[1].set_title("B  Independent runs, 13 Oct (corner)", loc="left")
    fig.tight_layout(); fig.savefig(fig_dir / "fig6_sensitivity_validation.png", dpi=220); plt.close(fig)


# =============================================================================

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db-dir", type=Path, default=DB_DIR)
    ap.add_argument("--val-dir", type=Path, default=VAL_DIR)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--extra-path", default=None, help="folder that contains h5py, if not in the .venv")
    args = ap.parse_args()
    if args.extra_path:
        sys.path.append(args.extra_path)

    paths = sorted(p for p in args.db_dir.glob("main_*.mat")
                   if not p.stem.endswith("_LSLtiming") and DB_RE.search(p.stem))
    paths += sorted(args.val_dir.glob(VAL_GLOB)) if args.val_dir.is_dir() else []
    csvs, seen = {}, set()
    for d in PSYCHOPY_DIRS:                       # Computer_B copy first; data/ for the validation runs
        for p in sorted(d.glob("*_photodiode_latency_latency_flashes.csv")):
            if p.name not in seen:
                seen.add(p.name)
                csvs[p] = pd.read_csv(p)
    rows, flashes, lags, hists = [], [], [], {}
    for p in paths:
        print(f"{p.name} ...", flush=True)
        row, fl, lag, hist = analyze_run(p, csvs)
        rows.append(row); flashes.append(fl); lags.append(lag); hists[row["run_id"]] = hist
    runs = pd.DataFrame(rows)
    dates = sorted(runs[runs.set == "database"].date.unique())
    runs["day"] = runs.date.map({d: i + 1 for i, d in enumerate(dates)})
    runs["exclusion"] = runs.apply(exclusion_reasons, axis=1)
    runs["included"] = runs.exclusion == ""
    flashes = pd.concat(flashes, ignore_index=True)
    lags = pd.concat(lags, ignore_index=True)
    s, fv = database_stats(runs, flashes)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    runs.to_csv(args.out_dir / "runs.csv", index=False)
    flashes.to_csv(args.out_dir / "flashes.csv", index=False)
    lags.to_csv(args.out_dir / "model_lag.csv", index=False)
    (args.out_dir / "summary.json").write_text(json.dumps(s, indent=2, default=float), encoding="utf-8")
    figures(runs, fv, lags, hists, s, args.out_dir / "figures")

    pd.set_option("display.width", 250)
    cols = ["run_id", "flash_markers", "paired", "offset_mean_ms", "offset_sd_ms", "offset_drift_ms_per_min",
            "offset_medbase_mean_ms", "delay_mean_ms", "transit_mean_ms", "lag_iqr_ms", "backlog_ms",
            "stalls_over_100ms", "lsl_resyncs", "dropped_frames", "exclusion"]
    print(runs[cols].round(2).to_string(index=False))
    print(json.dumps(s, indent=1, default=lambda o: round(float(o), 3)))


if __name__ == "__main__":
    main()
