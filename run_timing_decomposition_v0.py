# run_timing_decomposition_v0.py
# =============================================================================
# Standalone timing-decomposition diagnostic for the vMMR EEG rig.
#
# Purpose
# -------
# Characterise WHERE the PsychoPy-trigger-to-photodiode delay comes from along
# the chain:
#
#     PsychoPy flip  ->  monitor photons  ->  GTEC-0270 optical sensor  ->
#     GTEC-0274W g.TRIGbox  ->  g.HIamp  ->  Simulink LSL Receive  ->  saved file
#
# The photodiode is the only true ground truth for "light actually on screen".
# The LSL marker is what we would epoch on in the real task. Their per-flash
# difference, D_total = t_photodiode - t_marker (both read back from the saved
# recording), is the number that corrupts epoching. This script does not just
# measure D_total -- it runs a small factorial battery so the recorded data can
# attribute D_total's mean and variance to specific stages.
#
# Factors and what each one isolates
# ----------------------------------
#   SCHEDULING (within-block, 3 levels): when the marker is pushed relative to
#       the buffer swap.
#         PRE_FLIP   -> push immediately BEFORE win.flip()  (old parallel style)
#         ON_FLIP    -> win.callOnFlip(push)  (fires right after the swap)
#         POST_FLIP  -> push immediately AFTER win.flip() returns
#       Comparing D_total across these isolates the software-scheduling stage
#       (PsychoPy flip(). For ON_FLIP, push time should ~equal the flip time.
#
#   LUMINANCE (within-block, 3 levels): patch grey level. Probes LCD pixel-rise
#       time and the g.TRIGbox threshold crossing -- brighter light crosses the
#       trigger threshold earlier on the rising ramp.
#
#   POSITION (BETWEEN-block, requires moving the optical sensor): vertical
#       location of the patch. The slope of t_photodiode vs. vertical pixel is
#       the raster scan-out latency. The bottom_right block uses the SAME patch
#       geometry as run_vMMR_experiment_v0.py, so the offset measured there is
#       the offset between "diode truth" and the face at screen centre in the
#       real task.
#
#   CADENCE (separate block, NO display): markers pushed on a known software
#       schedule with no flips at all. Comparing recorded inter-marker intervals
#       to the logged software push intervals isolates the LSL -> Simulink
#       transport jitter with the display completely out of the loop. The
#       keepalive thread keeps running so the stream behaves exactly as in the
#       real task.
#
# Known limitation (single-reference)
# ------------------------------------
# With only photodiode + LSL marker (no spare zero-latency hardware TTL on a
# second g.HIamp input), a SINGLE flash's D_total still bundles display + sensor
# + amp + LSL together. The factorial manipulations attribute the VARIANCE; the
# cadence block gives the display-independent LSL/Simulink jitter as the best
# available proxy for that stage. A clean per-flash split of display vs. LSL
# would require that second reference and is out of scope here.
#
# Offline analysis recipe (done later in MNE/Python on the saved recording)
# -------------------------------------------------------------------------
#   1. Detect photodiode rising edges on the optical channel -> t_photodiode,
#      matched to each flash by its unique marker_code.
#   2. Detect non-zero marker samples on the marker channel -> t_marker.
#   3. D_total = t_photodiode - t_marker per flash.
#   4. Group by SCHEDULING            -> software-push offset (stage 1).
#      Regress t_photodiode on vertical pixel across POSITION blocks
#                                        -> scan-out slope (stage 2);
#      bottom_right vs mid_right offset -> correction for the real diode.
#      Group by LUMINANCE              -> pixel-rise + threshold (stages 2-3).
#      SD of D_total within a cell     -> irreducible epoching jitter.
#   5. CADENCE: recorded inter-marker intervals vs. logged software intervals;
#      residual after a linear (clock-rate) fit = LSL/Simulink jitter (stage 5).
#
# This script writes only diagnostics; it does not present the vMMR task.
#
# OUTPUT (written to data/):
#   *_timing_decomposition.csv  -> one row per flash (position blocks)
#   *_cadence.csv               -> one row per cadence marker
#   *_run_info.txt              -> rig + factor + marker-code metadata
#   *_frame_intervals.csv, *.log -> standard PsychoPy diagnostics
# =============================================================================

from psychopy import visual, core, gui, logging, sound
from psychopy import event as psychopy_event
from psychopy.hardware import keyboard

from pathlib import Path
from datetime import datetime
import traceback
import itertools
import random
import csv

from lsl_trigger import LSLTrigger

# =============================================================================
# 1. CONSTANTS
# =============================================================================

# --- flash timing (seconds; converted to whole frames at run time) -----------
# Mirrors the real face SOA (250 ms on + 350 ms blank = 600 ms) so the pipeline
# is exercised under representative cadence.
ON_DUR            = 0.250
OFF_DUR           = 0.350
INITIAL_BLACK_DUR = 2.000   # stable baseline before the first pulse of a block

# --- factor levels ------------------------------------------------------------
REPS_PER_CELL = 20          # flashes per (scheduling x luminance) cell, per block
SCHEDULING_LEVELS = ["PRE_FLIP", "ON_FLIP", "POST_FLIP"]
LUMINANCE_LEVELS  = [0.25, 0.50, 1.00]   # fraction of full white (0..1)

# POSITION is a between-block factor: the optical sensor is physically moved and
# re-placed on the patch before each block. Vertical varies at a fixed right
# margin so the scan-out slope is clean. bottom_right matches the real task.
POSITIONS = [
    {"label": "top_right",    "h": "right", "v": "top"},
    {"label": "mid_right",    "h": "right", "v": "middle"},
    {"label": "bottom_right", "h": "right", "v": "bottom"},
]

# --- patch geometry (pixels) -- matches run_vMMR_experiment_v0.py so the -------
# bottom_right block transfers directly to the real experiment.
DIODE_SIZE   = 45
DIODE_MARGIN = 40

# --- cadence (display-independent LSL/Simulink jitter) block ------------------
CADENCE_N        = 120
CADENCE_INTERVAL = 0.500    # nominal software interval between markers (s)

# --- marker code map (all values ≤ 255 to fit the 8-bit g.TRIGbox/HIamp limit)
# Flash codes encode the scheduling × luminance condition (9 combinations).
# Timing-based matching is used for 1:1 flash ↔ marker alignment offline;
# the condition code tells the analysis which cell each flash belongs to.
START_MARKER          = 9      # matches the real task's startup marker
END_MARKER            = 99     # matches the real task's end/abort marker
BLOCK_MARKER_BASE     = 200    # position-block start = 200 + block_index
CADENCE_START_MARKER  = 250
# Flash condition code = FLASH_CODE_OFFSET + sched_idx*3 + lum_idx  (10–18)
FLASH_CODE_OFFSET     = 10
# Cadence marker = CADENCE_MARKER_BASE + cadence_index  (101–220 for N=120)
# Base 100 keeps codes above END_MARKER=99 and above flash codes 10–18.
# Codes 200–202 overlap with BLOCK markers but only appear during the cadence
# block (after CADENCE_START_MARKER=250), so timing disambiguates them.
CADENCE_MARKER_BASE   = 100

# --- reproducibility ----------------------------------------------------------
DEFAULT_RNG_SEED = 20260622

QUIT_KEY = "escape"


# =============================================================================
# 2. SMALL HELPERS
# =============================================================================

def to_float(value, default=0.0):
    s = str(value).strip()
    if s == "" or s.lower() in ("nan", "none"):
        return default
    return float(s)


def to_int(value, default=0):
    s = str(value).strip()
    if s == "" or s.lower() in ("nan", "none"):
        return default
    return int(float(s))


def check_escape():
    if psychopy_event.getKeys(keyList=[QUIT_KEY]):
        raise KeyboardInterrupt("Diagnostic aborted with ESCAPE.")


def check_abort(kb):
    check_escape()
    keys = kb.getKeys(keyList=[QUIT_KEY], waitRelease=False, clear=True)
    for k in keys:
        if k.name == QUIT_KEY:
            raise KeyboardInterrupt("Diagnostic aborted with ESCAPE.")


def play_notification_beeps(n=4, freq=880, dur=0.45, gap=0.20):
    """Play n short beeps to signal experiment end, audible from another room."""
    snd = sound.Sound(value=freq, secs=dur, stereo=True, hamming=True)
    for _ in range(n):
        snd.play()
        core.wait(dur + gap)


def diode_xy(win, size, margin, h="right", v="bottom"):
    """Return (x, y) in pixels for the patch centre at the requested location."""
    half_w = win.size[0] / 2.0
    half_h = win.size[1] / 2.0

    if h == "right":
        x = half_w - margin - size / 2.0
    elif h == "left":
        x = -half_w + margin + size / 2.0
    elif h == "center":
        x = 0.0
    else:
        raise ValueError(f"Unsupported horizontal position: {h!r}")

    if v == "top":
        y = half_h - margin - size / 2.0
    elif v == "bottom":
        y = -half_h + margin + size / 2.0
    elif v == "middle":
        y = 0.0
    else:
        raise ValueError(f"Unsupported vertical position: {v!r}")

    return (x, y)


def luminance_to_scalar(frac):
    """Map a luminance fraction in [0, 1] to PsychoPy's [-1, 1] grey scalar."""
    frac = max(0.0, min(1.0, float(frac)))
    return 2.0 * frac - 1.0


def black_frames(win, kb, n_frames):
    for _ in range(n_frames):
        win.flip()
        check_abort(kb)


def show_alignment_screen(win, kb, text_stim, diode_stim, position_label):
    """Hold the patch steady (white) at the block position so the experimenter
    can place the optical sensor on it, then wait for SPACE."""
    diode_stim.fillColor = luminance_to_scalar(1.0)
    diode_stim.lineColor = luminance_to_scalar(1.0)
    text_stim.text = (
        f"Position block: {position_label}\n\n"
        "Place the optical sensor on the white square.\n\n"
        "Press SPACE to start this block.   Press ESC to abort."
    )
    kb.clearEvents()
    psychopy_event.clearEvents()
    while True:
        diode_stim.draw()
        text_stim.draw()
        win.flip()
        check_escape()
        keys = kb.getKeys(keyList=["space", QUIT_KEY], waitRelease=False,
                          clear=True)
        for k in keys:
            if k.name == QUIT_KEY:
                raise KeyboardInterrupt("Diagnostic aborted with ESCAPE.")
            if k.name == "space":
                return


# =============================================================================
# 3. ONE FLASH  (the factorial unit)
# =============================================================================

def run_flash(win, kb, trigger, diode_stim, frame_counts,
              scheduling, luminance_frac, marker_code):
    """Present one diode flash under the given scheduling + luminance and return
    a log dict. The patch is drawn for the whole ON period; the marker is pushed
    on the onset flip with timing determined by `scheduling`; the marker channel
    is cleared on the following flip to mirror the real task's 1-frame pulse.

    The keepalive thread keeps running throughout (representative of the task).
    """
    scalar = luminance_to_scalar(luminance_frac)
    diode_stim.fillColor = scalar
    diode_stim.lineColor = scalar

    onset = {"lsl": None, "psy": None}

    def _push():
        onset["psy"] = logging.defaultClock.getTime()
        onset["lsl"] = trigger.set_with_timestamp(marker_code)

    dropped_before = win.nDroppedFrames
    requested_flip_time = None
    actual_flip_time = None

    # ----- ON period (patch visible) -----------------------------------------
    for frame_n in range(frame_counts["on"]):
        diode_stim.draw()
        if frame_n == 0:
            requested_flip_time = logging.defaultClock.getTime()
            if scheduling == "ON_FLIP":
                win.callOnFlip(_push)          # fires inside flip(), post-swap
            elif scheduling == "PRE_FLIP":
                _push()                        # pushed before the swap
            actual_flip_time = win.flip()
            if scheduling == "POST_FLIP":
                _push()                        # pushed after the swap returns
            win.callOnFlip(trigger.clear)      # clear on the NEXT flip
        else:
            win.flip()
        check_abort(kb)

    # ----- OFF period (black) -------------------------------------------------
    black_frames(win, kb, frame_counts["off"])
    dropped_after = win.nDroppedFrames

    push_minus_flip = None
    if onset["psy"] is not None and actual_flip_time is not None:
        push_minus_flip = onset["psy"] - actual_flip_time

    return {
        "scheduling": scheduling,
        "luminance_frac": luminance_frac,
        "fill_color_scalar": scalar,
        "marker_code": marker_code,
        "requested_flip_time": requested_flip_time,
        "actual_flip_time": actual_flip_time,
        "lsl_push_timestamp": onset["lsl"],
        "psychopy_push_time": onset["psy"],
        "push_minus_flip": push_minus_flip,
        "dropped_frames_delta": dropped_after - dropped_before,
        "frame_rate": frame_counts["rate"],
        "on_frames": frame_counts["on"],
        "off_frames": frame_counts["off"],
        "intended_on_duration": ON_DUR,
        "intended_off_duration": OFF_DUR,
    }


# =============================================================================
# 4. POSITION BLOCK  (scheduling x luminance, fully crossed, randomised)
# =============================================================================

def run_position_block(win, kb, trigger, text_stim, frame_counts, writer, f,
                       position, block_index, rng, reps_per_cell,
                       common_row):
    """Run one between-block POSITION level: an alignment screen, a black
    baseline, then reps_per_cell flashes of every (scheduling x luminance) cell
    in randomised order. Returns the running global flash index."""
    x, y = diode_xy(win, DIODE_SIZE, DIODE_MARGIN,
                    h=position["h"], v=position["v"])
    diode_stim = visual.Rect(win, width=DIODE_SIZE, height=DIODE_SIZE,
                             pos=(x, y), units="pix")

    show_alignment_screen(win, kb, text_stim, diode_stim, position["label"])

    # mark the block boundary in the stream
    if trigger is not None:
        trigger.set(BLOCK_MARKER_BASE + block_index)
        trigger.clear()

    win.recordFrameIntervals = True
    black_frames(win, kb, frame_counts["initial_black"])

    # build and shuffle the (scheduling, luminance) x reps schedule
    cells = list(itertools.product(SCHEDULING_LEVELS, LUMINANCE_LEVELS))
    schedule = []
    for rep in range(reps_per_cell):
        block = list(cells)
        rng.shuffle(block)
        for (sched, lum) in block:
            schedule.append((rep + 1, sched, lum))

    flash_index = common_row["_flash_index_global"]
    for (rep_index, sched, lum) in schedule:
        flash_index += 1
        sched_idx = SCHEDULING_LEVELS.index(sched)
        lum_idx   = LUMINANCE_LEVELS.index(lum)
        marker_code = FLASH_CODE_OFFSET + sched_idx * len(LUMINANCE_LEVELS) + lum_idx
        row = run_flash(win, kb, trigger, diode_stim, frame_counts,
                        sched, lum, marker_code)
        row.update({
            "block_type": "POSITION",
            "position_label": position["label"],
            "patch_x": x,
            "patch_y": y,
            "rep_index": rep_index,
            "flash_index_global": flash_index,
            "notes": "",
        })
        row.update(common_row["_meta"])
        writer.writerow(row)
        f.flush()

    win.recordFrameIntervals = False
    common_row["_flash_index_global"] = flash_index
    return flash_index


# =============================================================================
# 5. CADENCE BLOCK  (no display -> isolates the LSL/Simulink path)
# =============================================================================

def run_cadence_block(win, kb, trigger, base_path, meta):
    """Push CADENCE_N markers at a fixed nominal software interval with NO
    flips. The window holds a black screen; the keepalive thread keeps running.
    Logs the precise software push time of each marker so the offline step can
    compare recorded inter-marker intervals against the true software schedule.
    """
    out_path = Path(str(base_path) + "_cadence.csv")
    fields = ["cadence_index", "marker_code", "intended_interval",
              "scheduled_time", "psychopy_push_time", "lsl_push_timestamp",
              "measured_software_interval", "notes"]

    if trigger is not None:
        trigger.set(CADENCE_START_MARKER)
        trigger.clear()

    # settle on a black screen first
    win.flip()
    check_abort(kb)

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()

        clock = core.Clock()
        t0 = clock.getTime()
        prev_push = None

        for k in range(1, CADENCE_N + 1):
            target = t0 + (k - 1) * CADENCE_INTERVAL
            # poll until the scheduled time, staying responsive to ESC
            while clock.getTime() < target:
                check_abort(kb)
                core.wait(0.0005, hogCPUperiod=0.0005)

            marker_code = CADENCE_MARKER_BASE + k
            psy = logging.defaultClock.getTime()
            lsl = trigger.set_with_timestamp(marker_code) \
                if trigger is not None else None
            if trigger is not None:
                trigger.clear()

            measured = None if prev_push is None else (psy - prev_push)
            prev_push = psy

            row = {
                "cadence_index": k,
                "marker_code": marker_code,
                "intended_interval": CADENCE_INTERVAL,
                "scheduled_time": target,
                "psychopy_push_time": psy,
                "lsl_push_timestamp": lsl,
                "measured_software_interval": measured,
                "notes": "no display; keepalive running",
            }
            row.update(meta)
            writer.writerow(row)
            f.flush()


# =============================================================================
# 6. OUTPUT WRITER (position-block flashes)
# =============================================================================

def make_flash_writer(path, meta_keys):
    fields = (["block_type", "position_label", "patch_x", "patch_y",
               "scheduling", "luminance_frac", "fill_color_scalar",
               "rep_index", "flash_index_global", "marker_code",
               "requested_flip_time", "actual_flip_time", "lsl_push_timestamp",
               "psychopy_push_time", "push_minus_flip", "dropped_frames_delta",
               "frame_rate", "on_frames", "off_frames",
               "intended_on_duration", "intended_off_duration", "notes"]
              + list(meta_keys))
    f = open(path, "w", encoding="utf-8", newline="")
    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    f.flush()
    return w, f


def write_frame_intervals(win, path):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame_index", "interval_seconds"])
        for i, interval in enumerate(win.frameIntervals):
            w.writerow([i, interval])


# =============================================================================
# 7. MAIN
# =============================================================================

def main():
    root     = Path(__file__).resolve().parent
    data_dir = root / "data"
    data_dir.mkdir(exist_ok=True)

    exp_info = {
        "participant": "timing",
        "session": "001",
        "fullscreen": True,
        "send_LSL_triggers": True,
        "run_position_blocks": True,
        "run_cadence_block": True,
        "reps_per_cell": REPS_PER_CELL,
        "rng_seed": DEFAULT_RNG_SEED,
        "lsl_keepalive_hz": 1200,
        "lsl_nominal_srate": 1200,
    }
    dlg = gui.DlgFromDict(
        exp_info, title="vMMR timing decomposition",
        order=["participant", "session", "fullscreen", "send_LSL_triggers",
               "run_position_blocks", "run_cadence_block", "reps_per_cell",
               "rng_seed", "lsl_keepalive_hz", "lsl_nominal_srate"])
    if not dlg.OK:
        core.quit()

    participant         = exp_info["participant"]
    session             = exp_info["session"]
    fullscreen          = bool(exp_info["fullscreen"])
    send_lsl_triggers   = bool(exp_info["send_LSL_triggers"])
    do_position_blocks  = bool(exp_info["run_position_blocks"])
    do_cadence_block    = bool(exp_info["run_cadence_block"])
    reps_per_cell       = to_int(exp_info["reps_per_cell"], default=REPS_PER_CELL)
    rng_seed            = to_int(exp_info["rng_seed"], default=DEFAULT_RNG_SEED)
    lsl_keepalive_hz    = to_float(exp_info["lsl_keepalive_hz"], default=1200.0)
    lsl_nominal_srate   = to_float(exp_info["lsl_nominal_srate"], default=1200.0)

    if reps_per_cell <= 0:
        raise ValueError("reps_per_cell must be positive.")
    if lsl_keepalive_hz <= 0:
        raise ValueError("lsl_keepalive_hz must be positive.")
    if lsl_nominal_srate <= 0:
        raise ValueError("lsl_nominal_srate must be positive.")

    rng = random.Random(rng_seed)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base  = data_dir / f"{participant}_ses-{session}_{stamp}_timing"

    logging.LogFile(str(base) + ".log", level=logging.EXP)
    logging.console.setLevel(logging.WARNING)

    # metadata stamped onto every output row
    meta = {"participant": participant, "session": session,
            "timestamp": stamp, "rng_seed": rng_seed}

    win = None
    trigger = None
    flash_f = None
    try:
        # --- hardware: bring up the outlet, wait for Simulink ----------------
        if send_lsl_triggers:
            trigger = LSLTrigger(enabled=True,
                                 keepalive_hz=lsl_keepalive_hz,
                                 nominal_srate=lsl_nominal_srate)
            print("LSL marker stream 'experiment_markers' created.", flush=True)
            print("\nOutlet live. Start the Simulink model, "
                  "then press Enter when ready...", flush=True)
            input()
        else:
            trigger = LSLTrigger(enabled=False)

        # --- window ----------------------------------------------------------
        win = visual.Window(size=(1200, 800), fullscr=fullscreen, units="pix",
                             color="black", allowGUI=not fullscreen,
                             waitBlanking=True)
        win.mouseVisible = False
        win.recordFrameIntervals = False

        kb = keyboard.Keyboard()

        # --- refresh rate -> frame counts ------------------------------------
        frame_rate = win.getActualFrameRate(nIdentical=60, nMaxFrames=180,
                                             nWarmUpFrames=10, threshold=1)
        if frame_rate is None:
            frame_rate = 60.0
            logging.warning("Could not measure refresh rate; assuming 60 Hz.")
        win.refreshThreshold = (1.0 / frame_rate) * 1.2

        def n_frames(seconds):
            return max(1, int(round(seconds * frame_rate)))

        frame_counts = {
            "rate": frame_rate,
            "on": n_frames(ON_DUR),
            "off": n_frames(OFF_DUR),
            "initial_black": n_frames(INITIAL_BLACK_DUR),
        }

        text_stim = visual.TextStim(win, text="", pos=(0, 0), height=30,
                                    color="white", units="pix", wrapWidth=1000)

        # --- run-info metadata file ------------------------------------------
        with open(str(base) + "_run_info.txt", "w", encoding="utf-8") as f:
            f.write(f"participant: {participant}\nsession: {session}\n")
            f.write(f"timestamp: {stamp}\n")
            f.write(f"frame_rate_measured: {frame_rate}\n")
            for k, v in frame_counts.items():
                f.write(f"frames[{k}]: {v}\n")
            f.write(f"send_LSL_triggers: {send_lsl_triggers}\n")
            f.write(f"run_position_blocks: {do_position_blocks}\n")
            f.write(f"run_cadence_block: {do_cadence_block}\n")
            f.write(f"reps_per_cell: {reps_per_cell}\n")
            f.write(f"rng_seed: {rng_seed}\n")
            f.write(f"scheduling_levels: {SCHEDULING_LEVELS}\n")
            f.write(f"luminance_levels: {LUMINANCE_LEVELS}\n")
            f.write(f"positions: {[p['label'] for p in POSITIONS]}\n")
            f.write(f"patch_size_px: {DIODE_SIZE}\n")
            f.write(f"patch_margin_px: {DIODE_MARGIN}\n")
            f.write(f"on_duration: {ON_DUR}\noff_duration: {OFF_DUR}\n")
            f.write(f"cadence_n: {CADENCE_N}\n")
            f.write(f"cadence_interval: {CADENCE_INTERVAL}\n")
            f.write(f"start_marker: {START_MARKER}\n")
            f.write(f"end_marker: {END_MARKER}\n")
            f.write(f"block_marker_base: {BLOCK_MARKER_BASE} "
                    f"(position block start = base + block_index)\n")
            f.write(f"cadence_start_marker: {CADENCE_START_MARKER}\n")
            f.write(f"flash_code_offset: {FLASH_CODE_OFFSET} "
                    f"(flash code = offset + sched_idx*3 + lum_idx; range {FLASH_CODE_OFFSET}–"
                    f"{FLASH_CODE_OFFSET + len(SCHEDULING_LEVELS)*len(LUMINANCE_LEVELS) - 1})\n")
            f.write(f"cadence_marker_base: {CADENCE_MARKER_BASE} "
                    f"(cadence marker = base + cadence_index; range "
                    f"{CADENCE_MARKER_BASE + 1}–{CADENCE_MARKER_BASE + CADENCE_N})\n")
            f.write(f"lsl_keepalive_hz: {lsl_keepalive_hz}\n")
            f.write(f"lsl_nominal_srate: {lsl_nominal_srate}\n")

        # --- start marker ----------------------------------------------------
        if trigger is not None:
            trigger.set(START_MARKER)
            trigger.clear()

        # --- position blocks -------------------------------------------------
        if do_position_blocks:
            flash_writer, flash_f = make_flash_writer(
                str(base) + "_timing_decomposition.csv", meta.keys())
            common_row = {"_flash_index_global": 0, "_meta": meta}
            for block_index, position in enumerate(POSITIONS):
                run_position_block(win, kb, trigger, text_stim, frame_counts,
                                   flash_writer, flash_f, position, block_index,
                                   rng, reps_per_cell, common_row)

        # --- cadence block ---------------------------------------------------
        if do_cadence_block:
            run_cadence_block(win, kb, trigger, base, meta)

        # --- end marker ------------------------------------------------------
        if trigger is not None:
            trigger.set(END_MARKER)
            trigger.clear()

        play_notification_beeps()
        text_stim.text = "Timing diagnostic complete.\n\nPress SPACE to exit."
        kb.clearEvents()
        psychopy_event.clearEvents()
        while True:
            text_stim.draw()
            win.flip()
            check_escape()
            keys = kb.getKeys(keyList=["space", QUIT_KEY], waitRelease=False,
                              clear=True)
            if any(k.name in ("space", QUIT_KEY) for k in keys):
                break

    except KeyboardInterrupt as e:
        logging.warning(f"Run ended early: {e}")
        if trigger is not None:
            trigger.set(END_MARKER)
    except Exception as e:
        logging.error(f"Unexpected error: {e}\n{traceback.format_exc()}")
        if trigger is not None:
            trigger.set(END_MARKER)
        play_notification_beeps(n=6, freq=440)  # lower-pitched alarm for errors
    finally:
        if trigger is not None:
            trigger.clear()
            if hasattr(trigger, "stop"):
                trigger.stop()
        if win is not None:
            write_frame_intervals(win, str(base) + "_frame_intervals.csv")
            win.close()
        if flash_f is not None:
            flash_f.close()
        logging.flush()
        core.quit()


if __name__ == "__main__":
    main()