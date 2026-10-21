# run_photodiode_latency_database.py
# =============================================================================
# Calibration DATABASE runs for the vMMR rig: PsychoPy LSL marker -> photodiode.
#
# Based on run_photodiode_latency_v1_trig_after_framerate_measurement.py (the
# final configuration, October 2026). Same marker codes, frame timing, LSL
# start-up order (outlet created after the window and refresh measurement) and
# experiment-start marker. Additions for the database:
#
#   * Square and optical sensor at the SCREEN CENTRE for every database run
#     (SQUARE_POSITION). Faces and primes are shown at the centre, so the
#     correction refers to the centre. All runs before the database used the
#     bottom-right corner; LCDs draw top to bottom, so the centre lights up
#     about half a frame earlier than that corner. The sensor is not moved
#     during the database.
#   * run_type: "short" = 100 flashes (~2.5 min of flashes), "long" = 500 flashes
#     (~12 min) to check stability over a longer session. The flash-duration
#     ramp repeats every RAMP_CYCLE flashes: flash i lasts
#     ON_START + ((i-1) mod RAMP_CYCLE) * ON_STEP, so pulse widths stay in the
#     100 ms - 1.75 s range and can still be paired with their markers.
#   * Run number per day (auto), operator, cold-start flag and notes in the
#     dialog; the expected EEG file names for both Simulink To File blocks are
#     shown on the "start Simulink" screen and printed to the console.
#   * run_info records software versions, the git commit and SHA-256 hashes of
#     this script and lsl_trigger.py (evidence that the configuration was
#     frozen), and one row per run is appended to data/database_run_log.csv.
#
# Sequence: dialog -> window -> refresh-rate measurement -> LSL outlet ->
# "start Simulink" screen (SPACE) -> START 9 -> sensor alignment (SPACE) ->
# experiment-start screen (SPACE, marker 1 on the next flip) -> 2 s black ->
# calibration dark/light/dark (5/6/5, 3 s each) -> marker 7 -> 2 s black ->
# flashes (marker 20 on each onset flip) -> 2 s black -> END 255.
#
# OUTPUT (data/):
#   db_<date>_run<NN>_<position>_<type>_<stamp>_photodiode_latency_latency_flashes.csv
#   ..._run_info.txt, ..._frame_intervals.csv, ....log
#   database_run_log.csv   one row per run (appended)
# =============================================================================

import importlib

visual = importlib.import_module("psychopy.visual")
core = importlib.import_module("psychopy.core")
gui = importlib.import_module("psychopy.gui")
logging = importlib.import_module("psychopy.logging")
psychopy_event = importlib.import_module("psychopy.event")
keyboard = importlib.import_module("psychopy.hardware.keyboard")

from pathlib import Path
from datetime import datetime
import csv
import hashlib
import platform
import random
import re
import subprocess
import sys
import traceback

from lsl_trigger import LSLTrigger

try:
    local_clock = importlib.import_module("pylsl").local_clock
except (ImportError, AttributeError):
    local_clock = None

# =============================================================================
# 1. CONSTANTS (final configuration - do not change during the database)
# =============================================================================

N_FLASHES = {"short": 100, "long": 500}
RAMP_CYCLE        = 100        # flash-duration ramp repeats every 100 flashes
ON_START_MS       = 100.0      # duration of the first flash in a ramp (ms)
ON_STEP_MS        = 16.7       # each flash is one frame longer than the last
OFF_MIN           = 0.350      # black gap lower bound (s)
OFF_MAX           = 0.650      # black gap upper bound (s); random jitter
BASELINE_DUR      = 2.000      # black before calibration and before flashes
CAL_SEGMENT_DUR   = 3.000      # each calibration segment (dark, light, dark)

DIODE_SIZE        = 45         # square size (px), same as the task square
DIODE_MARGIN      = 40         # corner position: margin from the screen edges
DIODE_LUMINANCE   = 1.00       # full white
TEXT_Y_CENTER_SQ  = 320        # text position when the square is at the centre

PREVIEW_ON  = 0.500            # alignment-screen blink
PREVIEW_OFF = 0.500

REFRESH_TOLERANCE   = 0.02
EXPECTED_REFRESH_HZ = 59.94    # measured rate of the stimulus display
SCREEN_WIDTH_PX  = 1920
SCREEN_HEIGHT_PX = 1080

LSL_RATE_HZ        = 600.0     # keepalive and nominal rate = Simulink inlet rate
SLX_FRAME_LENGTH   = 8         # Simulink g.HIamp frame length (recorded only)
RNG_SEED_BASE      = 20261006  # per-run seed = base + date + run number

# --- marker codes -------------------------------------------------------------
EXP_START_MARKER   = 1         # experiment start (flip after SPACE)
CAL_DARK_MARKER    = 5
CAL_LIGHT_MARKER   = 6
FLASH_BLOCK_MARKER = 7         # not flip-aligned
START_MARKER       = 9         # run start, not flip-aligned
FLASH_MARKER       = 20        # every flash onset (latency reference)
END_MARKER         = 255       # end/abort; stops the Simulink recording

QUIT_KEY = "escape"
RUN_LOG_NAME = "database_run_log.csv"
SQUARE_POSITION = "center"     # fixed for the whole database (sensor never moved)
EEG_DIR_ON_A = r"E:\ACADEMIA\PhD\WP5\EEG_Recordings\Photodiode_Calib_vMMR\database"


# =============================================================================
# 2. HELPERS
# =============================================================================

def check_abort(kb):
    if psychopy_event.getKeys(keyList=[QUIT_KEY]):
        raise KeyboardInterrupt("Aborted with ESCAPE.")
    for k in kb.getKeys(keyList=[QUIT_KEY], waitRelease=False, clear=True):
        if k.name == QUIT_KEY:
            raise KeyboardInterrupt("Aborted with ESCAPE.")


def wait_space(win, kb, text_stim, text, min_wait=0.0):
    """Static text until SPACE (after min_wait seconds). ESC aborts."""
    text_stim.text = text
    kb.clearEvents()
    psychopy_event.clearEvents()
    clock = core.Clock()
    while True:
        text_stim.draw()
        win.flip()
        check_abort(kb)
        keys = kb.getKeys(keyList=["space"], waitRelease=False, clear=True)
        if clock.getTime() >= min_wait and any(k.name == "space" for k in keys):
            return


def square_xy(win, position):
    if position == "center":
        return 0.0, 0.0
    x = win.size[0] / 2.0 - DIODE_MARGIN - DIODE_SIZE / 2.0
    y = -win.size[1] / 2.0 + DIODE_MARGIN + DIODE_SIZE / 2.0
    return x, y


def black_frames(win, kb, n):
    for _ in range(n):
        win.flip()
        check_abort(kb)


def make_push(trigger, code, store):
    def _push():
        store["cb"] = local_clock() if local_clock is not None else None
        store["lsl"] = trigger.set_with_timestamp(code)
    return _push


def sha256(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return "unavailable"


def git_state(root):
    """Commit hash and whether tracked files differ from it."""
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                                text=True, timeout=5).stdout.strip() or "unknown"
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                               cwd=root, capture_output=True, text=True, timeout=5).stdout.strip()
        return commit, ("yes" if dirty else "no")
    except Exception:
        return "unknown", "unknown"


def versions():
    out = {"python": sys.version.split()[0], "platform": platform.platform()}
    try:
        out["psychopy"] = importlib.import_module("psychopy").__version__
    except Exception:
        out["psychopy"] = "unknown"
    try:
        pylsl = importlib.import_module("pylsl")
        out["pylsl"] = getattr(pylsl, "__version__", "unknown")
        out["liblsl"] = str(pylsl.library_version())
    except Exception:
        out["pylsl"] = out["liblsl"] = "unknown"
    return out


def next_run_number(data_dir, date):
    nums = [int(m.group(1)) for p in data_dir.glob(f"db_{date}_run*_run_info.txt")
            if (m := re.search(r"_run(\d+)_", p.name))]
    return max(nums, default=0) + 1


def eeg_names(date, run_n, position, run_type):
    stem = (f"photodiode_db_{date}_{run_n}_slx_frame_length_{SLX_FRAME_LENGTH}_timestamped_LSL_"
            f"trig_after_framerate_expstart_sq{position}_{run_type}")
    return stem + ".mat", stem + "_LSLtiming.mat"


def append_run_log(path, row):
    new = not path.exists()
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)


# =============================================================================
# 3. SCREENS
# =============================================================================

def alignment_screen(win, kb, square, text_stim, position, on_n, off_n):
    """Blink the square until SPACE; no markers."""
    where = "centre of the screen" if position == "center" else "bottom-right corner"
    text_stim.text = (
        f"Place the optical sensor on the blinking square ({where}).\n\n"
        "Check that the g.TRIGbox LED turns ON with every white square\n"
        "and OFF with every black gap.\n\n"
        "SPACE = continue      ESC = abort")
    kb.clearEvents()
    psychopy_event.clearEvents()
    while True:
        for phase_on, n in ((True, on_n), (False, off_n)):
            for _ in range(n):
                if phase_on:
                    square.draw()
                text_stim.draw()
                win.flip()
                check_abort(kb)
                if any(k.name == "space" for k in
                       kb.getKeys(keyList=["space"], waitRelease=False, clear=True)):
                    return


def experiment_start_screen(win, kb, trigger, text_stim):
    """SPACE starts the experiment: marker 1 on the next (black) flip."""
    wait_space(win, kb, text_stim,
               "Sensor aligned.\n\nPress SPACE to start the experiment\n"
               "(sends the experiment-start trigger).\n\nESC = abort", min_wait=0.5)
    win.callOnFlip(trigger.set, EXP_START_MARKER)
    win.flip()


def calibration_segment(win, kb, trigger, square, n):
    """dark (5) -> light (6) -> dark (5), flip-aligned markers."""
    for draw_square, code in ((False, CAL_DARK_MARKER), (True, CAL_LIGHT_MARKER),
                              (False, CAL_DARK_MARKER)):
        for frame_n in range(n):
            if draw_square:
                square.draw()
            if frame_n == 0:
                win.callOnFlip(trigger.set, code)
            win.flip()
            check_abort(kb)


def run_flash(win, kb, trigger, square, on_n, off_n, hold_s):
    """One flash: square on for on_n frames, marker latched for hold_s."""
    store = {"cb": None, "lsl": None}
    trigger.hold_duration = hold_s
    dropped_before = win.nDroppedFrames
    flip_time = None
    for frame_n in range(on_n):
        square.draw()
        if frame_n == 0:
            win.callOnFlip(make_push(trigger, FLASH_MARKER, store))
            flip_time = win.flip()
        else:
            win.flip()
        check_abort(kb)
    black_frames(win, kb, off_n)
    lock_ms = None
    if store["cb"] is not None and store["lsl"] is not None:
        lock_ms = (store["lsl"] - store["cb"]) * 1000.0
    return {"psychopy_flip_time": flip_time, "callback_local_clock": store["cb"],
            "lsl_push_timestamp": store["lsl"], "lock_wait_ms": lock_ms,
            "dropped_frames_delta": win.nDroppedFrames - dropped_before}


# =============================================================================
# 4. MAIN
# =============================================================================

def main():
    root = Path(__file__).resolve().parent
    data_dir = root / "data"
    data_dir.mkdir(exist_ok=True)
    date = datetime.now().strftime("%Y%m%d")

    info = {
        "operator": "",
        "database_day": "1",
        "run_number": next_run_number(data_dir, date),
        "run_type": ["short", "long"],
        "cold_start": False,          # first run after restarting BOTH computers
        "notes": "",
        "fullscreen": True,
        "screen_index": 0,
    }
    dlg = gui.DlgFromDict(info, title="Photodiode latency DATABASE run",
                          order=list(info.keys()),
                          tip={"cold_start": "Tick for the first run after restarting both PCs",
                               "run_number": "Increments automatically per day"})
    if not dlg.OK:
        core.quit()

    run_n      = int(float(str(info["run_number"]).strip()))
    position   = SQUARE_POSITION
    run_type   = info["run_type"]
    n_flashes  = N_FLASHES[run_type]
    expected_hz = EXPECTED_REFRESH_HZ
    rng = random.Random(RNG_SEED_BASE + int(date) * 100 + run_n)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = data_dir / f"db_{date}_run{run_n:02d}_{position}_{run_type}_{stamp}_photodiode_latency"
    eeg_mat, eeg_timing = eeg_names(date, run_n, position, run_type)

    logging.LogFile(str(base) + ".log", level=logging.EXP)
    logging.console.setLevel(logging.WARNING)

    win = trigger = csv_f = None
    completed = False
    measured_hz = None
    n_done = 0
    stats = {"resyncs": None, "rate_hz": None, "samples_sent": None, "seconds": None}
    dropped_total = 0
    try:
        # --- window and refresh measurement BEFORE the LSL outlet ------------
        win = visual.Window(size=(SCREEN_WIDTH_PX, SCREEN_HEIGHT_PX),
                            fullscr=bool(info["fullscreen"]),
                            screen=int(info["screen_index"]), units="pix", color="black",
                            allowGUI=not bool(info["fullscreen"]), waitBlanking=True)
        win.mouseVisible = False
        win.recordFrameIntervals = False
        kb = keyboard.Keyboard()

        measured_hz = win.getActualFrameRate(nIdentical=60, nMaxFrames=180,
                                             nWarmUpFrames=10, threshold=1)
        if measured_hz is None:
            logging.warning("Could not measure refresh rate; using expected.")
        elif abs(measured_hz - expected_hz) / expected_hz > REFRESH_TOLERANCE:
            raise RuntimeError(f"Measured refresh {measured_hz:.2f} Hz differs >2 % from "
                               f"expected {expected_hz:.2f} Hz. Fix display settings.")
        win.refreshThreshold = 1.2 / (measured_hz or expected_hz)

        def n_frames(seconds):
            return max(1, int(round(seconds * expected_hz)))

        fc = {"on_start": n_frames(ON_START_MS / 1000.0), "on_step": n_frames(ON_STEP_MS / 1000.0),
              "off_min": n_frames(OFF_MIN), "off_max": n_frames(OFF_MAX),
              "baseline": n_frames(BASELINE_DUR), "cal": n_frames(CAL_SEGMENT_DUR),
              "preview_on": n_frames(PREVIEW_ON), "preview_off": n_frames(PREVIEW_OFF)}

        x, y = square_xy(win, position)
        lum = 2.0 * DIODE_LUMINANCE - 1.0
        square = visual.Rect(win, width=DIODE_SIZE, height=DIODE_SIZE, pos=(x, y), units="pix",
                             fillColor=lum, lineColor=lum)
        text_y = TEXT_Y_CENTER_SQ if position == "center" else 0
        text_stim = visual.TextStim(win, text="", pos=(0, text_y), height=26,
                                    color="white", units="pix", wrapWidth=1500)

        # --- LSL outlet, then the operator starts Simulink -------------------
        trigger = LSLTrigger(enabled=True, keepalive_hz=LSL_RATE_HZ, nominal_srate=LSL_RATE_HZ)
        print(f"\nDATABASE run {run_n} ({position}, {run_type}, {n_flashes} flashes)\n"
              f"Simulink To File (EEG):    {EEG_DIR_ON_A}\\{eeg_mat}\n"
              f"Simulink To File (timing): {EEG_DIR_ON_A}\\{eeg_timing}\n"
              "Start the Simulink model, then press SPACE on the stimulus screen.", flush=True)
        wait_space(win, kb, text_stim,
                   f"DATABASE run {run_n}   |   square: {position}   |   {run_type} "
                   f"({n_flashes} flashes)\n\n"
                   f"Set the Simulink To File names (folder {EEG_DIR_ON_A}):\n"
                   f"EEG:  {eeg_mat}\n"
                   f"timing:  {eeg_timing}\n\n"
                   f"Check: frame length {SLX_FRAME_LENGTH}, 600 Hz, stop constant 255.\n"
                   "Start the Simulink model, then press SPACE.        ESC = abort")

        # --- run info ----------------------------------------------------------
        commit, dirty = git_state(root)
        with open(str(base) + "_run_info.txt", "w", encoding="utf-8") as f:
            for k, v in info.items():
                f.write(f"{k}: {v}\n")
            f.write(f"timestamp: {stamp}\n")
            f.write(f"script: {Path(__file__).name}\n")
            f.write("lsl_outlet_created: after window opening and refresh-rate measurement (v1)\n")
            f.write(f"database_run: {date}_{run_n}\n")
            f.write(f"n_flashes: {n_flashes}\n")
            f.write(f"ramp_cycle: {RAMP_CYCLE}\n")
            f.write(f"eeg_file_expected: {eeg_mat}\n")
            f.write(f"eeg_timing_file_expected: {eeg_timing}\n")
            f.write(f"slx_frame_length: {SLX_FRAME_LENGTH}\n")
            f.write(f"expected_refresh_hz: {expected_hz}\n")
            f.write(f"measured_refresh_hz: {measured_hz}\n")
            f.write(f"lsl_keepalive_hz: {LSL_RATE_HZ}\nlsl_nominal_srate: {LSL_RATE_HZ}\n")
            f.write(f"screen_width_px: {SCREEN_WIDTH_PX}\nscreen_height_px: {SCREEN_HEIGHT_PX}\n")
            f.write(f"window_size_px: {list(win.size)}\n")
            f.write(f"square_position: {position}\nsquare_center_px: ({x:.1f}, {y:.1f})\n")
            f.write(f"square_size_px: {DIODE_SIZE}\n")
            for k, v in fc.items():
                f.write(f"frames[{k}]: {v}\n")
            f.write("flash i: on_frames = frames[on_start] + ((i-1) mod ramp_cycle)*frames[on_step]; "
                    "marker held for the same duration\n")
            f.write(f"off_range_s: [{OFF_MIN}, {OFF_MAX}]\n")
            f.write(f"rng_seed: {RNG_SEED_BASE + int(date) * 100 + run_n}\n")
            f.write("markers: experiment_start=1 (flip-aligned, after SPACE), cal_dark=5, "
                    "cal_light=6, flash_block=7 (not flip-aligned), start=9 (not flip-aligned), "
                    "flash=20 (flip-aligned latency reference), end=255\n")
            for k, v in versions().items():
                f.write(f"version_{k}: {v}\n")
            f.write(f"git_commit: {commit}\ngit_tracked_changes: {dirty}\n")
            f.write(f"sha256_script: {sha256(Path(__file__))}\n")
            f.write(f"sha256_lsl_trigger: {sha256(root / 'lsl_trigger.py')}\n")

        # --- sequence ----------------------------------------------------------
        trigger.set(START_MARKER)
        alignment_screen(win, kb, square, text_stim, position, fc["preview_on"], fc["preview_off"])
        experiment_start_screen(win, kb, trigger, text_stim)      # marker 1

        black_frames(win, kb, fc["baseline"])
        calibration_segment(win, kb, trigger, square, fc["cal"])
        default_hold = trigger.hold_duration
        trigger.set(FLASH_BLOCK_MARKER)
        black_frames(win, kb, fc["baseline"])

        fields = ["flash_index", "ramp_index", "marker_code", "on_frames", "on_duration_ms",
                  "off_frames", "psychopy_flip_time", "callback_local_clock",
                  "lsl_push_timestamp", "lock_wait_ms", "dropped_frames_delta",
                  "expected_refresh_hz", "square_size_px", "square_position"]
        csv_f = open(str(base) + "_latency_flashes.csv", "w", encoding="utf-8", newline="")
        writer = csv.DictWriter(csv_f, fieldnames=fields)
        writer.writeheader()

        win.recordFrameIntervals = True
        for i in range(1, n_flashes + 1):
            ramp_i = (i - 1) % RAMP_CYCLE + 1
            off_n = rng.randint(fc["off_min"], fc["off_max"])
            on_n = fc["on_start"] + (ramp_i - 1) * fc["on_step"]
            on_s = on_n / expected_hz
            row = run_flash(win, kb, trigger, square, on_n, off_n, on_s)
            dropped_total += row["dropped_frames_delta"]
            row.update({"flash_index": i, "ramp_index": ramp_i, "marker_code": FLASH_MARKER,
                        "on_frames": on_n, "on_duration_ms": on_s * 1000.0, "off_frames": off_n,
                        "expected_refresh_hz": expected_hz, "square_size_px": DIODE_SIZE,
                        "square_position": position})
            writer.writerow(row)
            csv_f.flush()
            n_done = i
        win.recordFrameIntervals = False
        trigger.hold_duration = default_hold

        black_frames(win, kb, fc["baseline"])
        completed = True
        stats = trigger.stats()
        text_stim.text = (f"Run {run_n} complete.\n\nlsl_resyncs: {stats['resyncs']} "
                          f"(must be 0)\ndropped frames: {dropped_total}")
        for _ in range(int(round(2 * expected_hz))):
            text_stim.draw()
            win.flip()

    except KeyboardInterrupt as e:
        logging.warning(f"Run ended early: {e}")
    except Exception as e:
        logging.error(f"Unexpected error: {e}\n{traceback.format_exc()}")
    finally:
        if trigger is not None:
            try:
                stats = trigger.stats()
                run_info_path = Path(str(base) + "_run_info.txt")
                if run_info_path.exists():
                    with open(run_info_path, "a", encoding="utf-8") as f:
                        f.write(f"lsl_samples_sent: {stats['samples_sent']}\n")
                        f.write(f"lsl_seconds: {stats['seconds']}\n")
                        f.write(f"lsl_rate_hz: {stats['rate_hz']}\n")
                        f.write(f"lsl_resyncs: {stats['resyncs']}\n")
                        f.write(f"flashes_completed: {n_done}\n")
                        f.write(f"dropped_frames_total: {dropped_total}\n")
                        f.write(f"run_completed: {completed}\n")
            except Exception as e:
                logging.error(f"LSL rate report problem: {e}")
            trigger.hold_duration = 0.100
            try:
                trigger.finish(final_code=END_MARKER)
            except Exception as e:
                logging.error(f"LSL shutdown problem: {e}")
        if win is not None:
            with open(str(base) + "_frame_intervals.csv", "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["frame_index", "interval_seconds"])
                for j, iv in enumerate(win.frameIntervals):
                    w.writerow([j, iv])
            win.close()
        if csv_f is not None:
            csv_f.close()
        try:
            append_run_log(data_dir / RUN_LOG_NAME, {
                "date": date, "run_number": run_n, "database_day": info["database_day"],
                "start_stamp": stamp, "end_time": datetime.now().strftime("%H:%M:%S"),
                "operator": info["operator"], "square_position": position, "run_type": run_type,
                "n_flashes_planned": n_flashes, "flashes_completed": n_done,
                "completed": completed, "cold_start": info["cold_start"],
                "slx_frame_length": SLX_FRAME_LENGTH, "measured_refresh_hz": measured_hz,
                "lsl_resyncs": stats.get("resyncs"), "lsl_rate_hz": stats.get("rate_hz"),
                "dropped_frames_total": dropped_total, "eeg_file": eeg_mat,
                "eeg_timing_file": eeg_timing, "psychopy_base": base.name, "notes": info["notes"]})
        except Exception as e:
            logging.error(f"Run log problem: {e}")
        logging.flush()
        core.quit()


if __name__ == "__main__":
    main()
