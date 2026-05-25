# run_vmmr.py
# =============================================================================
# PsychoPy Coder implementation of the Dor-Ziderman et al. (2019) vMMR EEG task.
#
# Paradigm (Experiment 1): a 2 x 2 design, PRIME (DEATH / NEGATIVE) x IDENTITY
# (SELF / OTHER). Each trial = a Hebrew prime word, then a sequence of 3-6
# identical "standard" faces followed by one "deviant" (50% morph) face.
# On 90/360 trials one face is replaced by a "target" (sunglasses) version;
# the participant presses SPACE whenever a target is detected.
#
# This script reads the pre-generated trial tables in conditions/ and presents
# the experiment with frame-based timing and optional parallel-port EEG triggers.
#
# OUTPUT (two files, written to data/):
#   *_events.csv  -> one row per FACE EVENT  (used to epoch the EEG)
#   *_trials.csv  -> one row per TRIAL       (used for behavioural QC)
#   *_frame_intervals.csv, *_run_info.txt, *.log -> diagnostics
# =============================================================================

from psychopy import visual, core, gui, logging
from psychopy.hardware import keyboard

# psychopy.parallel may be unavailable on machines with no parallel port
# (e.g. when developing on a laptop). Import defensively so dry runs still work.
try:
    from psychopy import parallel
except Exception:
    parallel = None

from pathlib import Path
from datetime import datetime
import traceback
import csv
import random


# =============================================================================
# 1. CONSTANTS  -- all timings come straight from the paper's Methods section
# =============================================================================

# --- Stimulus timing (seconds). Converted to whole frames at run time. --------
FIX_MIN          = 0.500   # trial-start fixation cross, jittered lower bound
FIX_MAX          = 0.700   # trial-start fixation cross, jittered upper bound
PRIME_DUR        = 0.600   # prime word shown alone
PRE_FACE_FIX_DUR = 0.250   # prime word + central cross, just before the faces
FACE_ON_DUR      = 0.250   # each face visible
FACE_BLANK_DUR   = 0.350   # blank after each face  -> SOA = 250 + 350 = 600 ms
POST_SEQUENCE_DUR = 0.500  # extra blank after the last face, see RESPONSE MODEL

# --- Response model -----------------------------------------------------------
# Responses are scored at the TRIAL level (matching the paper). A keypress
# counts as a hit if it lands within RESPONSE_WINDOW after the target's onset.
# POST_SEQUENCE_DUR exists so that a late hit to a target in the LAST sequence
# position is still captured: target-on-deviant gives 600 ms inside the event
# plus 500 ms after = 1100 ms >= RESPONSE_WINDOW.
RESPONSE_WINDOW  = 1.000   # seconds after target onset that still counts as a hit
RESPONSE_KEYS    = ["space"]
QUIT_KEY         = "escape"

# --- Layout (pixels; window units are 'pix') ---------------------------------
FACE_SIZE   = (425, 405)   # matches the paper's face images
PRIME_Y     = 260          # prime word sits above the face
TEXT_HEIGHT = 34
FIX_HEIGHT  = 42
TEXT_FONT   = "Arial"      # must contain Hebrew glyphs incl. niqqud (Arial does on Windows)


# =============================================================================
# 2. EEG TRIGGER CODES
# =============================================================================
# One code per (PRIME, IDENTITY, ROLE). ROLE is the face's job in the sequence:
#   STD/DEV          -> ordinary standard / deviant face
#   TARGET_STD/_DEV  -> a target (sunglasses) face placed at a standard / deviant slot
TRIGGER_MAP = {
    ("DEATH",    "SELF",  "STD"):        11,
    ("DEATH",    "SELF",  "DEV"):        12,
    ("DEATH",    "SELF",  "TARGET_STD"): 13,
    ("DEATH",    "SELF",  "TARGET_DEV"): 14,

    ("DEATH",    "OTHER", "STD"):        21,
    ("DEATH",    "OTHER", "DEV"):        22,
    ("DEATH",    "OTHER", "TARGET_STD"): 23,
    ("DEATH",    "OTHER", "TARGET_DEV"): 24,

    ("NEGATIVE", "SELF",  "STD"):        31,
    ("NEGATIVE", "SELF",  "DEV"):        32,
    ("NEGATIVE", "SELF",  "TARGET_STD"): 33,
    ("NEGATIVE", "SELF",  "TARGET_DEV"): 34,

    ("NEGATIVE", "OTHER", "STD"):        41,
    ("NEGATIVE", "OTHER", "DEV"):        42,
    ("NEGATIVE", "OTHER", "TARGET_STD"): 43,
    ("NEGATIVE", "OTHER", "TARGET_DEV"): 44,
}


# =============================================================================
# 3. SMALL PARSING HELPERS
# =============================================================================

def to_int(value, default=0):
    """Parse a CSV cell to int. Empty / blank / NaN cells fall back to `default`
    instead of crashing -- this is the fix for the targetPosition crash."""
    s = str(value).strip()
    if s == "" or s.lower() in ("nan", "none"):
        return default
    return int(float(s))


def normalize_prime(value):
    """Map the CSV primeType to a canonical 'DEATH' / 'NEGATIVE'."""
    v = str(value).strip().upper()
    if v.startswith("DEATH"):
        return "DEATH"
    if v.startswith("NEG"):
        return "NEGATIVE"
    raise ValueError(f"Unknown primeType: {value!r}")


def normalize_identity(value):
    """Map the CSV identity to a canonical 'SELF' / 'OTHER'."""
    v = str(value).strip().upper()
    if v.startswith("SELF"):
        return "SELF"
    if v.startswith("OTHER"):
        return "OTHER"
    raise ValueError(f"Unknown identity: {value!r}")


def resolve_path(root, path_string):
    """Return an absolute Path. Absolute strings (your CSV uses full Windows
    paths) are used as-is; relative strings are resolved against the project
    root, so the script keeps working if you switch to relative paths later."""
    p = Path(str(path_string))
    return p if p.is_absolute() else (root / p)


def sort_block_value(x):
    """Sort key for block labels: numeric where possible, else alphabetical."""
    try:
        return (0, int(x))
    except (ValueError, TypeError):
        return (1, str(x))


# =============================================================================
# 4. TRIAL-TABLE READER
# =============================================================================

def read_trials(path):
    """Read a conditions CSV into a list of dict rows, validating the schema."""
    if not path.exists():
        raise FileNotFoundError(f"Could not find trial file: {path}")

    # utf-8-sig strips a BOM if Excel added one; the Hebrew words need utf-8.
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        raise ValueError(f"{path.name} contains no data rows.")

    # These columns must exist for the script to build sequences and triggers.
    required = [
        "primeType", "identity", "word", "nStandards", "isTarget",
        "targetPosition", "standardImage", "deviantImage",
        "standardTargetImage", "deviantTargetImage",
    ]
    missing = [c for c in required if c not in rows[0]]
    if missing:
        raise ValueError(f"{path.name} is missing required columns: {missing}")

    # 'block' and 'condCode' are optional: synthesize them if absent.
    for r in rows:
        if not r.get("block"):
            r["block"] = "practice"
        if not r.get("condCode"):
            r["condCode"] = normalize_prime(r["primeType"])[0] + \
                            normalize_identity(r["identity"])[0]
    return rows


# =============================================================================
# 5. BUILD THE PER-TRIAL FACE SEQUENCE
# =============================================================================

def build_face_sequence(trial_row):
    """Turn one trial row into an ordered list of face events:
    nStandards 'STD' events, then one 'DEV' event. On target trials, the face
    at targetPosition is swapped for its target (sunglasses) version and its
    role becomes TARGET_STD / TARGET_DEV. Returns a list of {role, image} dicts.
    """
    n_standards     = to_int(trial_row["nStandards"])
    is_target       = to_int(trial_row["isTarget"])
    target_position = to_int(trial_row["targetPosition"])  # -1 on non-target trials

    # Standards first, deviant last.
    sequence = [{"role": "STD", "image": trial_row["standardImage"]}
                for _ in range(n_standards)]
    sequence.append({"role": "DEV", "image": trial_row["deviantImage"]})

    # Insert the target only on target trials (so targetPosition == -1 is ignored).
    if is_target == 1:
        if not (1 <= target_position <= len(sequence)):
            raise ValueError(
                f"targetPosition {target_position} is out of range for a "
                f"sequence of length {len(sequence)}.")
        idx = target_position - 1            # CSV is 1-based, list is 0-based
        if sequence[idx]["role"] == "STD":
            sequence[idx] = {"role": "TARGET_STD",
                             "image": trial_row["standardTargetImage"]}
        else:  # the target landed on the deviant slot
            sequence[idx] = {"role": "TARGET_DEV",
                             "image": trial_row["deviantTargetImage"]}
    return sequence


# =============================================================================
# 6. EEG TRIGGER HARDWARE WRAPPER
# =============================================================================

class EEGTrigger:
    """Thin wrapper around the parallel port. When disabled, every call is a
    no-op, so the exact same code runs during a no-hardware dry run."""

    def __init__(self, enabled=False, address="0x0378"):
        self.enabled = enabled
        self.port = None
        if not self.enabled:
            return
        if parallel is None:
            raise RuntimeError("EEG triggers requested but psychopy.parallel "
                               "is unavailable on this machine.")
        addr = str(address).strip()
        addr_int = int(addr, 16) if addr.lower().startswith("0x") else int(addr)
        self.port = parallel.ParallelPort(address=addr_int)
        self.port.setData(0)                 # ensure all lines start low

    def set(self, code):
        if self.port is not None:
            self.port.setData(int(code))

    def clear(self):
        if self.port is not None:
            self.port.setData(0)


# =============================================================================
# 7. PRE-LOAD ALL IMAGES (created once -> reused -> reliable timing)
# =============================================================================

def preload_images(win, root, trial_rows):
    """Create one ImageStim per unique image file. The dict is keyed by the raw
    CSV path string, which is exactly what build_face_sequence stores."""
    image_columns = ["standardImage", "deviantImage",
                     "standardTargetImage", "deviantTargetImage"]
    paths = sorted({row[col] for row in trial_rows for col in image_columns
                    if str(row.get(col, "")).strip() != ""})

    stims = {}
    for raw in paths:
        full = resolve_path(root, raw)
        if not full.exists():
            raise FileNotFoundError(f"Image not found: {full}")
        stims[raw] = visual.ImageStim(win, image=str(full), pos=(0, 0),
                                      size=FACE_SIZE, units="pix",
                                      interpolate=True)
    return stims


# =============================================================================
# 8. OUTPUT WRITERS  -- two separate files (events vs trials)
# =============================================================================

def make_event_writer(path):
    """Per-FACE-EVENT file: stimulus identity + EEG trigger. This is the file
    you align to the EEG. No response columns -- responses are trial-level."""
    fields = ["participant", "session", "phase", "block",
              "trial_global", "trial_in_block",
              "primeType", "identity", "condCode", "word", "nStandards",
              "isTargetTrial", "targetPosition",
              "eventIndex", "eventRole", "eventImage",
              "isAnalysisStandard", "isAnalysisDeviant",
              "triggerCode", "onsetTime"]
    f = open(path, "w", encoding="utf-8", newline="")
    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    f.flush()
    return w, f


def make_trial_writer(path):
    """Per-TRIAL file: one behavioural outcome per trial. This is the file you
    use for the hit-rate QC."""
    fields = ["participant", "session", "phase", "block",
              "trial_global", "trial_in_block",
              "primeType", "identity", "condCode", "word", "nStandards",
              "isTargetTrial", "targetPosition", "targetOnset",
              "responseType", "rt", "nPresses", "correct"]
    f = open(path, "w", encoding="utf-8", newline="")
    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    f.flush()
    return w, f


def write_frame_intervals(win, path):
    """Dump recorded frame intervals so you can verify timing afterwards."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["frame_index", "interval_seconds"])
        for i, interval in enumerate(win.frameIntervals):
            w.writerow([i, interval])


# =============================================================================
# 9. KEYPRESS COLLECTION  -- continuous, trial-level
# =============================================================================

def collect_presses(kb, presses):
    """Drain the keyboard buffer once. Each response key is appended to
    `presses` as (name, rt), where rt is on the keyboard clock that was reset
    at the start of the current trial. ESC raises to abort the experiment."""
    keys = kb.getKeys(keyList=RESPONSE_KEYS + [QUIT_KEY],
                      waitRelease=False, clear=True)
    for k in keys:
        if k.name == QUIT_KEY:
            raise KeyboardInterrupt("Experiment aborted with ESCAPE.")
        if k.name in RESPONSE_KEYS:
            presses.append((k.name, k.rt))   # k.rt is relative to trial start


# =============================================================================
# 10. DISPLAY HELPERS
# =============================================================================

def show_text_and_wait(win, kb, text_stim, message,
                        allowed_keys=("space",), min_wait=0.20):
    """Show a static message until an allowed key is pressed. Used for
    instructions / rest screens. `min_wait` blocks an accidental instant skip."""
    text_stim.text = message                 # set once (not every frame)
    kb.clearEvents()
    wait_clock = core.Clock()
    while True:
        text_stim.draw()
        win.flip()
        keys = kb.getKeys(keyList=list(allowed_keys) + [QUIT_KEY],
                          waitRelease=False, clear=True)
        for k in keys:
            if k.name == QUIT_KEY:
                raise KeyboardInterrupt("Experiment aborted with ESCAPE.")
        if wait_clock.getTime() >= min_wait:
            for k in keys:
                if k.name in allowed_keys:
                    return


def present_static(win, kb, draw_list, n_frames, presses):
    """Draw a fixed set of stimuli for n_frames, collecting keypresses every
    frame. Covers the fixation, prime, pre-face-fix and post-sequence periods."""
    for _ in range(n_frames):
        for stim in draw_list:
            stim.draw()
        win.flip()
        collect_presses(kb, presses)


# =============================================================================
# 11. PRESENT ONE FACE EVENT
# =============================================================================

def present_face_event(win, kb, prime_stim, image_stim, diode_stim,
                        role, trigger_code, trigger,
                        face_on_frames, blank_frames, presses):
    """Present one face: prime + face for 250 ms, then prime alone for 350 ms.
    The EEG trigger is sent on the face-onset flip and cleared one frame later.
    Keypresses are collected throughout (continuous response model).

    Returns (onset_global, onset_trialclock):
      onset_global     -- event onset on the global clock, for the events file
      onset_trialclock -- target onset on the trial clock, or None if not a target
    """
    is_target_event = role.startswith("TARGET")
    onset = {"global": None, "trial": None}

    # callOnFlip runs this the instant the face appears, so the recorded
    # target onset shares the same clock as every keypress rt.
    def _capture_onset():
        onset["global"] = logging.defaultClock.getTime()
        if is_target_event:
            onset["trial"] = kb.clock.getTime()

    # ----- face ON (prime + face) --------------------------------------------
    for frame_n in range(face_on_frames):
        prime_stim.draw()
        image_stim.draw()
        if diode_stim is not None:
            diode_stim.draw()              # photodiode square only while face is on
        if frame_n == 0:                   # first frame: arm onset actions
            win.callOnFlip(trigger.set, trigger_code)
            win.callOnFlip(_capture_onset)
        if frame_n == 1:                   # second frame: clear the 1-frame pulse
            win.callOnFlip(trigger.clear)
        win.flip()
        collect_presses(kb, presses)

    # ----- face OFF (prime alone) --------------------------------------------
    for _ in range(blank_frames):
        prime_stim.draw()
        win.flip()
        collect_presses(kb, presses)

    return onset["global"], onset["trial"]


# =============================================================================
# 12. SCORE ONE TRIAL  -- trial-level continuous-response attribution
# =============================================================================

def attribute_responses(is_target_trial, target_onset, presses):
    """Decide the behavioural outcome of a trial from its keypresses.

    target trial : first press within [target_onset, target_onset+WINDOW] = hit;
                   otherwise = miss. Extra presses are not penalised.
    non-target   : any press = false_alarm; none = correct_rejection.
    Returns (response_type, rt, n_presses, correct).
    """
    n_presses = len(presses)

    if is_target_trial and target_onset is not None:
        hit_rt = None
        for _, rt in sorted(presses, key=lambda p: p[1]):       # earliest first
            if target_onset <= rt <= target_onset + RESPONSE_WINDOW:
                hit_rt = rt
                break
        if hit_rt is not None:
            return "hit", hit_rt - target_onset, n_presses, 1
        return "miss", None, n_presses, 0

    # non-target trial
    if n_presses > 0:
        return "false_alarm", None, n_presses, 0
    return "correct_rejection", None, n_presses, 1


# =============================================================================
# 13. RUN ONE TRIAL
# =============================================================================

def run_trial(row, phase, participant, session, trial_global,
              win, kb, event_writer, event_f, trial_writer, trial_f,
              image_stims, trigger, fix_stim, prime_stim,
              frame_counts, diode_stim=None):
    """Fixation -> prime -> pre-face cross -> face sequence -> post-sequence
    window. Writes one events-file row per face and one trials-file row total."""
    prime_type = normalize_prime(row["primeType"])
    identity   = normalize_identity(row["identity"])
    cond_code  = row["condCode"]
    word       = row["word"]
    is_target  = to_int(row["isTarget"])
    n_standards     = to_int(row["nStandards"])
    target_position = to_int(row["targetPosition"])
    trial_in_block  = row.get("trial_in_block", "")

    sequence = build_face_sequence(row)

    # --- start the trial clock -----------------------------------------------
    # Reset the keyboard clock so every keypress rt is measured from trial start;
    # clear any stale presses left over from the previous trial.
    kb.clearEvents()
    kb.clock.reset()
    presses = []                              # (name, rt) collected all trial

    # Record frame intervals only during trials (keeps instruction-screen waits
    # out of the timing log).
    win.recordFrameIntervals = True

    # Persistent prime word: set the text once; it stays visible from the prime
    # period until the end of the trial.
    prime_stim.text = word

    # --- 1) trial-start fixation: cross only, jittered 500-700 ms ------------
    fix_frames = max(1, int(round(random.uniform(FIX_MIN, FIX_MAX)
                                  * frame_counts["rate"])))
    present_static(win, kb, [fix_stim], fix_frames, presses)

    # --- 2) prime word alone, 600 ms ----------------------------------------
    present_static(win, kb, [prime_stim], frame_counts["prime"], presses)

    # --- 3) prime word + central cross, 250 ms ------------------------------
    present_static(win, kb, [prime_stim, fix_stim],
                   frame_counts["pre_face"], presses)

    # --- 4) the face sequence ------------------------------------------------
    target_onset = None
    for event_index, event in enumerate(sequence, start=1):
        role        = event["role"]
        image_path  = event["image"]
        trig_code   = TRIGGER_MAP[(prime_type, identity, role)]
        image_stim  = image_stims[image_path]

        onset_global, onset_trial = present_face_event(
            win, kb, prime_stim, image_stim, diode_stim,
            role, trig_code, trigger,
            frame_counts["face_on"], frame_counts["blank"], presses)

        if onset_trial is not None:           # this event was the target
            target_onset = onset_trial

        # Analysis flags. The paper uses the 3rd face as the standard comparator
        # (this equalises standard/deviant counts) and EXCLUDES whole target
        # trials from the ERP analysis -- hence the `is_target == 0` term.
        is_analysis_standard = int(role == "STD" and event_index == 3
                                   and is_target == 0)
        is_analysis_deviant  = int(role == "DEV" and is_target == 0)

        event_writer.writerow({
            "participant": participant, "session": session, "phase": phase,
            "block": row["block"], "trial_global": trial_global,
            "trial_in_block": trial_in_block,
            "primeType": prime_type, "identity": identity,
            "condCode": cond_code, "word": word, "nStandards": n_standards,
            "isTargetTrial": is_target, "targetPosition": target_position,
            "eventIndex": event_index, "eventRole": role,
            "eventImage": image_path,
            "isAnalysisStandard": is_analysis_standard,
            "isAnalysisDeviant": is_analysis_deviant,
            "triggerCode": trig_code, "onsetTime": onset_global,
        })
        event_f.flush()

    # --- 5) post-sequence window: prime word stays, catches late hits --------
    present_static(win, kb, [prime_stim], frame_counts["post_seq"], presses)

    win.recordFrameIntervals = False

    # --- score the trial and write the behavioural row ----------------------
    response_type, rt, n_presses, correct = attribute_responses(
        is_target == 1, target_onset, presses)

    trial_writer.writerow({
        "participant": participant, "session": session, "phase": phase,
        "block": row["block"], "trial_global": trial_global,
        "trial_in_block": trial_in_block,
        "primeType": prime_type, "identity": identity, "condCode": cond_code,
        "word": word, "nStandards": n_standards,
        "isTargetTrial": is_target, "targetPosition": target_position,
        "targetOnset": target_onset, "responseType": response_type,
        "rt": rt, "nPresses": n_presses, "correct": correct,
    })
    trial_f.flush()


# =============================================================================
# 14. MAIN
# =============================================================================

def main():
    root            = Path(__file__).resolve().parent
    conditions_dir  = root / "conditions"
    data_dir        = root / "data"
    data_dir.mkdir(exist_ok=True)

    # --- startup dialog ------------------------------------------------------
    # Boolean values render as checkboxes in the dialog.
    exp_info = {
        "participant": "test001",
        "session": "001",
        "fullscreen": False,
        "send_EEG_triggers": False,
        "parallel_port_address": "0x0378",
        "photodiode_square": False,
    }
    dlg = gui.DlgFromDict(exp_info, title="vMMR EEG experiment",
                          order=["participant", "session", "fullscreen",
                                 "send_EEG_triggers", "parallel_port_address",
                                 "photodiode_square"])
    if not dlg.OK:
        core.quit()

    participant       = exp_info["participant"]
    session           = exp_info["session"]
    fullscreen        = bool(exp_info["fullscreen"])
    send_eeg_triggers = bool(exp_info["send_EEG_triggers"])
    use_photodiode    = bool(exp_info["photodiode_square"])

    # --- output file names ---------------------------------------------------
    stamp     = datetime.now().strftime("%Y%m%d_%H%M%S")
    base      = data_dir / f"{participant}_ses-{session}_{stamp}"

    log_file = logging.LogFile(str(base) + ".log", level=logging.EXP)
    logging.console.setLevel(logging.WARNING)

    # --- load trial tables (before opening the window, so errors show early) -
    practice_rows = read_trials(conditions_dir / "practice_trials.csv")
    main_rows     = read_trials(conditions_dir / "main_trials.csv")
    all_rows      = practice_rows + main_rows

    event_writer, event_f = make_event_writer(str(base) + "_events.csv")
    trial_writer, trial_f = make_trial_writer(str(base) + "_trials.csv")

    win = None
    trigger = None
    try:
        # --- window ----------------------------------------------------------
        win = visual.Window(size=(1200, 800), fullscr=fullscreen, units="pix",
                             color="black", allowGUI=not fullscreen,
                             waitBlanking=True)
        win.mouseVisible = False
        win.recordFrameIntervals = False      # toggled on per-trial in run_trial

        kb = keyboard.Keyboard()

        # --- measure the refresh rate and convert durations to frames --------
        frame_rate = win.getActualFrameRate(nIdentical=60, nMaxFrames=180,
                                            nWarmUpFrames=10, threshold=1)
        if frame_rate is None:
            frame_rate = 60.0
            logging.warning("Could not measure refresh rate; assuming 60 Hz.")
        win.refreshThreshold = (1.0 / frame_rate) * 1.2   # dropped-frame flag

        def n_frames(seconds):
            return max(1, int(round(seconds * frame_rate)))

        frame_counts = {
            "rate":     frame_rate,
            "prime":    n_frames(PRIME_DUR),
            "pre_face": n_frames(PRE_FACE_FIX_DUR),
            "face_on":  n_frames(FACE_ON_DUR),
            "blank":    n_frames(FACE_BLANK_DUR),
            "post_seq": n_frames(POST_SEQUENCE_DUR),
        }

        # --- run-info diagnostics file --------------------------------------
        with open(str(base) + "_run_info.txt", "w", encoding="utf-8") as f:
            f.write(f"participant: {participant}\nsession: {session}\n")
            f.write(f"timestamp: {stamp}\n")
            f.write(f"frame_rate_measured: {frame_rate}\n")
            for k, v in frame_counts.items():
                f.write(f"frames[{k}]: {v}\n")
            f.write(f"send_EEG_triggers: {send_eeg_triggers}\n")
            f.write(f"parallel_port_address: {exp_info['parallel_port_address']}\n")
            f.write(f"photodiode_square: {use_photodiode}\n")

        # --- hardware + stimuli ---------------------------------------------
        trigger = EEGTrigger(enabled=send_eeg_triggers,
                             address=exp_info["parallel_port_address"])
        image_stims = preload_images(win, root, all_rows)

        instruction_text = visual.TextStim(win, text="", pos=(0, 0),
                                           height=TEXT_HEIGHT, color="white",
                                           font=TEXT_FONT, wrapWidth=1000,
                                           units="pix")
        # Hebrew prime word. The legacy TextStim renderer on Windows crashes on
        # Hebrew letters that carry niqqud (base letter + combining vowel mark).
        # TextBox2 has a proper Unicode/RTL renderer and handles this correctly.
        # Note the API differences: letterHeight (not height), and an explicit
        # box size + anchor/alignment to keep the word centred at PRIME_Y.
        prime_stim = visual.TextBox2(win, text="", font=TEXT_FONT,
                                     pos=(0, PRIME_Y), letterHeight=TEXT_HEIGHT,
                                     color="white", units="pix",
                                     size=(1000, 100),
                                     alignment="center", anchor="center",
                                     borderColor=None, fillColor=None,
                                     languageStyle="RTL", editable=False)
        fix_stim = visual.TextStim(win, text="+", pos=(0, 0), height=FIX_HEIGHT,
                                   color="white", font=TEXT_FONT, units="pix")

        diode_stim = None
        if use_photodiode:
            diode_stim = visual.Rect(win, width=40, height=40,
                                     pos=(win.size[0] / 2 - 40,
                                          win.size[1] / 2 - 40),
                                     fillColor="white", lineColor="white",
                                     units="pix")

        # --- instructions ----------------------------------------------------
        show_text_and_wait(win, kb, instruction_text,
            "In this task you will see words and faces.\n\n"
            "Keep your eyes on the centre of the screen.\n\n"
            "Most faces appear normally. Occasionally a face wears sunglasses.\n"
            "Press SPACE as fast as you can whenever you see sunglasses.\n\n"
            "Try not to blink during the face sequences.\n\n"
            "Press SPACE to begin the practice.")

        # --- practice block --------------------------------------------------
        trial_global = 0
        for row in practice_rows:
            trial_global += 1
            run_trial(row, "practice", participant, session, trial_global,
                      win, kb, event_writer, event_f, trial_writer, trial_f,
                      image_stims, trigger, fix_stim, prime_stim,
                      frame_counts, diode_stim)

        show_text_and_wait(win, kb, instruction_text,
            "Practice complete.\n\nThe main experiment will now begin.\n\n"
            "Remember: press SPACE whenever you see sunglasses.\n\n"
            "Press SPACE to start Block 1.")

        # --- main blocks -----------------------------------------------------
        blocks = sorted({r["block"] for r in main_rows}, key=sort_block_value)
        for block_i, block in enumerate(blocks, start=1):
            block_rows = [r for r in main_rows if r["block"] == block]

            show_text_and_wait(win, kb, instruction_text,
                f"Block {block_i} of {len(blocks)}\n\n"
                "Please sit still and keep your eyes on the centre.\n"
                "Try not to blink during the face sequences.\n\n"
                "Press SPACE when you are ready.")

            for row in block_rows:
                trial_global += 1
                run_trial(row, "main", participant, session, trial_global,
                          win, kb, event_writer, event_f, trial_writer, trial_f,
                          image_stims, trigger, fix_stim, prime_stim,
                          frame_counts, diode_stim)

            if block_i < len(blocks):         # eyes-closed rest between blocks
                show_text_and_wait(win, kb, instruction_text,
                    "Rest period.\n\nYou may close your eyes and rest.\n\n"
                    "Press SPACE when you are ready to continue.")

        # --- end screen ------------------------------------------------------
        show_text_and_wait(win, kb, instruction_text,
            "The experiment is complete.\n\nThank you.\n\n"
            "Press SPACE to exit.")

    except KeyboardInterrupt as e:
        logging.warning(f"Run ended early: {e}")
    except Exception as e:
        # Log the full traceback so an unexpected crash is diagnosable.
        logging.error(f"Unexpected error: {e}\n{traceback.format_exc()}")
    finally:
        if trigger is not None:
            trigger.clear()
        if win is not None:
            write_frame_intervals(win, str(base) + "_frame_intervals.csv")
            win.close()
        event_f.close()
        trial_f.close()
        logging.flush()
        core.quit()


if __name__ == "__main__":
    main()