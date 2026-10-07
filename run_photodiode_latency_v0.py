# run_photodiode_latency_v0.py
# =============================================================================
# Minimal PsychoPy-trigger -> photodiode latency/jitter test for the vMMR rig.
#
# One condition only: full-white square in the bottom-right corner (same place
# as the real task's photodiode square), LSL marker pushed on the onset flip via
# win.callOnFlip, repeated N times.
#
# DURATION CODING: every flash has its own duration. Flash i keeps the square
# on for ON_START + (i-1)*ON_STEP (rounded to whole frames), and its marker is
# held for the same time. In the recording, the WIDTH of a photodiode pulse
# therefore tells which flash it is, so each marker can be paired with its own
# photodiode pulse even if the two channels are offset or stretched in time.
# Offline:
#     delay_i  = t_photodiode_onset_i - t_marker_onset_i   (both from the .mat)
#     latency  = mean(delay)      jitter = SD(delay)
#
# Design choices (from the October 2026 repo audit):
#   * Rig (October 2026): 120 Hz stimulus display; Simulink on a second PC
#     records g.HIamp + LSL markers at 600 Hz and stops when the marker
#     reaches 255. All codes here are small except END_MARKER = 255, sent
#     once at the end (or on abort) to stop the recording.
#   * LSL keepalive and nominal rate default to 600 Hz to match the Simulink
#     inlet. The keepalive must not push faster than the inlet consumes, or
#     samples may queue up and delay the recorded markers.
#   * A dark/light calibration segment is recorded first, so the analysis can
#     determine the photodiode channel's polarity (it may idle HIGH) instead of
#     assuming that 0 -> 1 means "square on".
#   * The OFF interval is randomly jittered so flash onsets cannot phase-lock
#     with the LSL keepalive or the Simulink inlet cycle and hide real jitter.
#   * Per flash, the script logs the flip time, the local_clock() time at which
#     the flip callback started, and the LSL push timestamp, so lock waiting
#     inside LSLTrigger is visible (lock_wait_ms).
#   * Frame counts use the EXPECTED refresh rate; the run aborts if the
#     measured rate differs by more than 2 %.
#
# Requires the latched lsl_trigger.py in the same folder (set() latches the
# code and auto-expires it after hold_duration; no manual clear needed).
#
# OUTPUT (data/):
#   *_latency_flashes.csv   one row per flash
#   *_run_info.txt          parameters, marker map, measured refresh rate
#   *_frame_intervals.csv   PsychoPy frame intervals during the flash block
#   *.log                   PsychoPy log
# =============================================================================

import importlib

# PsychoPy is installed in the experiment runtime, but may not be installed
# in the editor's Python environment. Dynamic imports keep static analysis
# from flagging the runtime dependency while retaining the usual module names.
visual = importlib.import_module("psychopy.visual")
core = importlib.import_module("psychopy.core")
gui = importlib.import_module("psychopy.gui")
logging = importlib.import_module("psychopy.logging")
psychopy_event = importlib.import_module("psychopy.event")
keyboard = importlib.import_module("psychopy.hardware.keyboard")

from pathlib import Path
from datetime import datetime
import traceback
import random
import csv

from lsl_trigger import LSLTrigger

try:
    # pylsl is optional when LSL output is disabled. Import it dynamically so
    # environments without pylsl can still run the script.
    local_clock = importlib.import_module("pylsl").local_clock
except (ImportError, AttributeError):
    local_clock = None

# =============================================================================
# 1. CONSTANTS
# =============================================================================

N_FLASHES_DEFAULT = 100        # ~2.5 min of flashes with the defaults below
ON_START_MS       = 100.0      # duration of the first flash (ms)
ON_STEP_MS        = 16.7       # each flash is this much longer than the last
                               # (ms; rounded to whole frames, at least 1)
OFF_MIN           = 0.350      # black gap lower bound (s); task blank = 350 ms
OFF_MAX           = 0.650      # black gap upper bound (s); random jitter
BASELINE_DUR      = 2.000      # black before calibration and before flashes
CAL_SEGMENT_DUR   = 3.000      # each calibration segment (dark, light, dark)

# Square geometry: 45 px / 40 px margin = the real task geometry.
DIODE_SIZE_DEFAULT = 45
DIODE_MARGIN       = 40
DIODE_LUMINANCE    = 1.00      # full white only

# Sensor-check preview on the alignment screen (operator watches the LED)
PREVIEW_ON  = 0.500
PREVIEW_OFF = 0.500

REFRESH_TOLERANCE = 0.02       # abort if measured differs > 2 % from expected

# --- marker codes (all flip-aligned except START and END) -------------------
START_MARKER    = 9            # run start (not flip-aligned)
CAL_DARK_MARKER = 5            # onset of a calibration DARK segment
CAL_LIGHT_MARKER = 6           # onset of the calibration LIGHT segment
FLASH_BLOCK_MARKER = 7         # start of the flash block (not flip-aligned)
FLASH_MARKER    = 20           # every flash onset (the latency reference)
END_MARKER      = 255          # end/abort; stops the Simulink recording

QUIT_KEY = "escape"


# =============================================================================
# 2. HELPERS
# =============================================================================

def to_int(value, default=0):
    s = str(value).strip()
    if s == "" or s.lower() in ("nan", "none"):
        return default
    return int(float(s))


def to_float(value, default=0.0):
    s = str(value).strip()
    if s == "" or s.lower() in ("nan", "none"):
        return default
    return float(s)


def check_abort(kb):
    if psychopy_event.getKeys(keyList=[QUIT_KEY]):
        raise KeyboardInterrupt("Aborted with ESCAPE.")
    for k in kb.getKeys(keyList=[QUIT_KEY], waitRelease=False, clear=True):
        if k.name == QUIT_KEY:
            raise KeyboardInterrupt("Aborted with ESCAPE.")


def diode_xy(win, size, margin):
    """Centre of a bottom-right square, same convention as the task."""
    x = win.size[0] / 2.0 - margin - size / 2.0
    y = -win.size[1] / 2.0 + margin + size / 2.0
    return x, y


def luminance_to_scalar(frac):
    frac = max(0.0, min(1.0, float(frac)))
    return 2.0 * frac - 1.0


def black_frames(win, kb, n):
    for _ in range(n):
        win.flip()
        check_abort(kb)


def make_push(trigger, code, store):
    """Return a flip callback that pushes `code` and records timing.
    store['cb'] = local_clock() when the callback started
    store['lsl'] = LSL timestamp taken inside LSLTrigger (after the lock)"""
    def _push():
        store["cb"] = local_clock() if local_clock is not None else None
        store["lsl"] = trigger.set_with_timestamp(code)
    return _push


# =============================================================================
# 3. ALIGNMENT + SENSOR CHECK
# =============================================================================

def alignment_screen(win, kb, square, text_stim, preview_on_n, preview_off_n):
    """Blink the square until SPACE so the operator can place the sensor and
    confirm the g.TRIGbox LED follows every ON and OFF. No markers are sent."""
    text_stim.text = (
        "Place the optical sensor on the blinking square (bottom-right).\n\n"
        "Check that the g.TRIGbox LED turns ON with every white square\n"
        "and OFF with every black gap.\n\n"
        "SPACE = start      ESC = abort"
    )
    kb.clearEvents()
    psychopy_event.clearEvents()
    while True:
        for phase_on, n in ((True, preview_on_n), (False, preview_off_n)):
            for _ in range(n):
                if phase_on:
                    square.draw()
                text_stim.draw()
                win.flip()
                check_abort(kb)
                if any(k.name == "space" for k in
                       kb.getKeys(keyList=["space"], waitRelease=False,
                                  clear=True)):
                    return


# =============================================================================
# 4. POLARITY CALIBRATION
# =============================================================================

def calibration_segment(win, kb, trigger, square, frame_counts):
    """dark (code 5) -> light (code 6) -> dark (code 5), each CAL_SEGMENT_DUR.
    Markers are flip-aligned. Lets the analysis learn which photodiode level
    corresponds to 'square on'."""
    n = frame_counts["cal"]
    for draw_square, code in ((False, CAL_DARK_MARKER),
                              (True, CAL_LIGHT_MARKER),
                              (False, CAL_DARK_MARKER)):
        for frame_n in range(n):
            if draw_square:
                square.draw()
            if frame_n == 0:
                win.callOnFlip(trigger.set, code)
            win.flip()
            check_abort(kb)


# =============================================================================
# 5. ONE FLASH
# =============================================================================

def run_flash(win, kb, trigger, square, on_n, off_n, hold_s):
    """One flash: square on for on_n frames, marker latched for hold_s."""
    store = {"cb": None, "lsl": None}
    # LSLTrigger reads hold_duration when the marker is set, so this makes the
    # marker last as long as the square.
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

    lock_wait_ms = None
    if store["cb"] is not None and store["lsl"] is not None:
        lock_wait_ms = (store["lsl"] - store["cb"]) * 1000.0

    return {
        "psychopy_flip_time": flip_time,
        "callback_local_clock": store["cb"],
        "lsl_push_timestamp": store["lsl"],
        "lock_wait_ms": lock_wait_ms,
        "dropped_frames_delta": win.nDroppedFrames - dropped_before,
    }


# =============================================================================
# 6. MAIN
# =============================================================================

def main():
    root = Path(__file__).resolve().parent
    data_dir = root / "data"
    data_dir.mkdir(exist_ok=True)

    info = {
        "run_label": "latency",
        "session": "001",
        "fullscreen": True,
        "screen_index": 0,
        "expected_refresh_hz": 120,
        "send_LSL_triggers": True,
        "n_flashes": N_FLASHES_DEFAULT,
        "on_start_ms": ON_START_MS,
        "on_step_ms": ON_STEP_MS,
        "square_size_px": DIODE_SIZE_DEFAULT,
        "rng_seed": 20261006,
        "lsl_keepalive_hz": 600,
        "lsl_nominal_srate": 600,
    }
    order = list(info.keys())
    dlg = gui.DlgFromDict(info, title="Photodiode latency test", order=order)
    if not dlg.OK:
        core.quit()

    run_label   = info["run_label"]
    session     = info["session"]
    fullscreen  = bool(info["fullscreen"])
    screen_idx  = to_int(info["screen_index"], 0)
    expected_hz = to_float(info["expected_refresh_hz"], 120.0)
    send_lsl    = bool(info["send_LSL_triggers"])
    n_flashes   = to_int(info["n_flashes"], N_FLASHES_DEFAULT)
    on_start_ms = to_float(info["on_start_ms"], ON_START_MS)
    on_step_ms  = to_float(info["on_step_ms"], ON_STEP_MS)
    square_size = to_int(info["square_size_px"], DIODE_SIZE_DEFAULT)
    rng_seed    = to_int(info["rng_seed"], 20261006)
    keepalive   = to_float(info["lsl_keepalive_hz"], 600.0)
    nominal     = to_float(info["lsl_nominal_srate"], 600.0)

    if n_flashes <= 0 or square_size <= 0 or expected_hz <= 0:
        raise ValueError("n_flashes, square_size_px, expected_refresh_hz must be > 0.")
    if on_start_ms <= 0 or on_step_ms <= 0:
        raise ValueError("on_start_ms and on_step_ms must be > 0.")

    rng = random.Random(rng_seed)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = data_dir / f"{run_label}_ses-{session}_{stamp}_photodiode_latency"

    logging.LogFile(str(base) + ".log", level=logging.EXP)
    logging.console.setLevel(logging.WARNING)

    win = None
    trigger = None
    csv_f = None
    try:
        # --- LSL outlet; start Simulink AFTER the outlet exists -------------
        trigger = LSLTrigger(enabled=send_lsl, keepalive_hz=keepalive,
                             nominal_srate=nominal)
        if send_lsl:
            print("LSL stream 'experiment_markers' is live.", flush=True)
            print("Start the Simulink model on the recording PC (check its "
                  "output .mat filename, 600 Hz rate and stop constant 255), "
                  "then press Enter...", flush=True)
            input()

        # --- window -----------------------------------------------------------
        win = visual.Window(size=(1200, 800), fullscr=fullscreen,
                            screen=screen_idx, units="pix", color="black",
                            allowGUI=not fullscreen, waitBlanking=True)
        win.mouseVisible = False
        win.recordFrameIntervals = False
        kb = keyboard.Keyboard()

        # --- refresh-rate gate ----------------------------------------------
        measured_hz = win.getActualFrameRate(nIdentical=60, nMaxFrames=180,
                                             nWarmUpFrames=10, threshold=1)
        if measured_hz is None:
            logging.warning("Could not measure refresh rate; using expected.")
        elif abs(measured_hz - expected_hz) / expected_hz > REFRESH_TOLERANCE:
            raise RuntimeError(
                f"Measured refresh {measured_hz:.2f} Hz differs >2 % from "
                f"expected {expected_hz:.2f} Hz. Fix display settings.")
        win.refreshThreshold = 1.2 / (measured_hz or expected_hz)

        def n_frames(seconds):
            return max(1, int(round(seconds * expected_hz)))

        frame_counts = {
            "on_start": n_frames(on_start_ms / 1000.0),
            "on_step": n_frames(on_step_ms / 1000.0),
            "off_min": n_frames(OFF_MIN),
            "off_max": n_frames(OFF_MAX),
            "baseline": n_frames(BASELINE_DUR),
            "cal": n_frames(CAL_SEGMENT_DUR),
            "preview_on": n_frames(PREVIEW_ON),
            "preview_off": n_frames(PREVIEW_OFF),
        }

        x, y = diode_xy(win, square_size, DIODE_MARGIN)
        scalar = luminance_to_scalar(DIODE_LUMINANCE)
        square = visual.Rect(win, width=square_size, height=square_size,
                             pos=(x, y), units="pix",
                             fillColor=scalar, lineColor=scalar)
        text_stim = visual.TextStim(win, text="", pos=(0, 0), height=28,
                                    color="white", units="pix", wrapWidth=1000)

        # --- run info ---------------------------------------------------------
        with open(str(base) + "_run_info.txt", "w", encoding="utf-8") as f:
            for k, v in info.items():
                f.write(f"{k}: {v}\n")
            f.write(f"timestamp: {stamp}\n")
            f.write(f"window_size_px: {list(win.size)}\n")
            f.write(f"measured_refresh_hz: {measured_hz}\n")
            for k, v in frame_counts.items():
                f.write(f"frames[{k}]: {v}\n")
            f.write(f"square_center_px: ({x:.1f}, {y:.1f})\n")
            f.write(f"square_margin_px: {DIODE_MARGIN}\n")
            f.write("flash i: on_frames = frames[on_start] + (i-1)*frames[on_step]; "
                    "marker held for the same duration\n")
            f.write(f"on_duration_first_ms: "
                    f"{frame_counts['on_start'] / expected_hz * 1000:.2f}\n")
            f.write(f"on_duration_step_ms: "
                    f"{frame_counts['on_step'] / expected_hz * 1000:.2f}\n")
            f.write(f"on_duration_last_ms: "
                    f"{(frame_counts['on_start'] + (n_flashes - 1) * frame_counts['on_step']) / expected_hz * 1000:.2f}\n")
            f.write(f"off_range_s: [{OFF_MIN}, {OFF_MAX}]\n")
            f.write(f"lsl_hold_duration_s: {getattr(trigger, 'hold_duration', None)}\n")
            f.write("markers: start=9 (not flip-aligned), cal_dark=5, "
                    "cal_light=6, flash_block=7 (not flip-aligned), "
                    "flash=20 (flip-aligned latency reference), end=255\n")

        # --- sequence ---------------------------------------------------------
        trigger.set(START_MARKER)
        alignment_screen(win, kb, square, text_stim,
                         frame_counts["preview_on"], frame_counts["preview_off"])

        black_frames(win, kb, frame_counts["baseline"])
        calibration_segment(win, kb, trigger, square, frame_counts)

        default_hold = trigger.hold_duration
        trigger.set(FLASH_BLOCK_MARKER)
        black_frames(win, kb, frame_counts["baseline"])

        fields = ["flash_index", "marker_code", "on_frames", "on_duration_ms",
                  "off_frames",
                  "psychopy_flip_time", "callback_local_clock",
                  "lsl_push_timestamp", "lock_wait_ms",
                  "dropped_frames_delta", "expected_refresh_hz",
                  "square_size_px"]
        csv_f = open(str(base) + "_latency_flashes.csv", "w",
                     encoding="utf-8", newline="")
        writer = csv.DictWriter(csv_f, fieldnames=fields)
        writer.writeheader()

        win.recordFrameIntervals = True
        for i in range(1, n_flashes + 1):
            off_n = rng.randint(frame_counts["off_min"], frame_counts["off_max"])
            on_n = frame_counts["on_start"] + (i - 1) * frame_counts["on_step"]
            on_s = on_n / expected_hz
            row = run_flash(win, kb, trigger, square, on_n, off_n, on_s)
            row.update({"flash_index": i, "marker_code": FLASH_MARKER,
                        "on_frames": on_n, "on_duration_ms": on_s * 1000.0,
                        "off_frames": off_n,
                        "expected_refresh_hz": expected_hz,
                        "square_size_px": square_size})
            writer.writerow(row)
            csv_f.flush()
        win.recordFrameIntervals = False
        trigger.hold_duration = default_hold      # back to the normal latch

        black_frames(win, kb, frame_counts["baseline"])
        text_stim.text = "Latency test complete."
        text_stim.draw()
        win.flip()

    except KeyboardInterrupt as e:
        logging.warning(f"Run ended early: {e}")
    except Exception as e:
        logging.error(f"Unexpected error: {e}\n{traceback.format_exc()}")
    finally:
        if trigger is not None:
            trigger.hold_duration = 0.100         # short latch for END_MARKER
            # Latch END_MARKER for hold_duration, return to 0, stop once.
            # Guarded so a stuck keepalive thread cannot skip the file saves.
            try:
                trigger.finish(final_code=END_MARKER)
            except Exception as e:
                logging.error(f"LSL shutdown problem: {e}")
        if win is not None:
            with open(str(base) + "_frame_intervals.csv", "w",
                      encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["frame_index", "interval_seconds"])
                for j, iv in enumerate(win.frameIntervals):
                    w.writerow([j, iv])
            win.close()
        if csv_f is not None:
            csv_f.close()
        logging.flush()
        core.quit()


if __name__ == "__main__":
    main()