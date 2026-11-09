# Start Here

This repository contains a PsychoPy Coder implementation of a visual mismatch
response (vMMR) EEG experiment based on the Dor-Ziderman self-face/death-prime
paradigm.

The experiment is a 2 × 2 within-subject design:

| Prime | Identity |
|---|---|
| DEATH | SELF |
| DEATH | OTHER |
| NEGATIVE | SELF |
| NEGATIVE | OTHER |

## Repository structure

```text
conditions/       Trial-generation notebook and CSV input tables
stimuli/          Face images and Hebrew prime-word lists
run_vMMR_*.py     Experiment versions and timing/photodiode utilities
lsl_trigger.py    LSL marker-stream implementation
timing_utils.py   Refresh-rate and frame-count helpers
analysis/         EEG marker-timing correction and calibration analysis
notebooks/        EEG and photodiode analysis notebooks
matlab/           Simulink acquisition models and LSL timestamp support
tests/            Automated tests
docs/             Calibration, laboratory, and analysis documentation
data/             Experiment output and calibration data
```

## Main files

### `run_vMMR_experiment_v2.py`

This is the current experiment implementation. It:

1. Opens the PsychoPy window and measures the display refresh rate.
2. Converts task durations to whole frames.
3. Reads `practice_trials.csv` and `main_trials.csv`.
4. Preloads all face images before creating the LSL outlet.
5. Presents Hebrew primes, fixation, faces, blanks, and response intervals.
6. Sends optional LSL and parallel-port triggers.
7. Records SPACE responses to sunglasses targets.
8. Writes event, trial, frame-interval, run-information, and log files.

The older `run_vMMR_experiment_v0.py`, `v1`, and dated scripts are preserved
versions used for development and timing comparisons. Do not overwrite a
validated version; create a new version when changing timing-sensitive code.

### `lsl_trigger.py`

Provides the LSL marker outlet used by the Simulink EEG acquisition system.
Markers are latched for approximately 100 ms and automatically return to zero.
The default keepalive and nominal sampling rates are 600 Hz. Offline analysis
detects events from transitions into nonzero marker values.

### `timing_utils.py`

Provides refresh-rate validation, frame-count conversion, and refresh-rate
diagnostics. Supported nominal rates include 60, 120, 59.94, and 119.88 Hz.

### `analysis/marker_timing.py`

Maps PsychoPy LSL marker timestamps onto the EEG time axis using the calibrated
clock-mapping procedure. It uses the `<recording>_LSLtiming.mat` file and the
computer-B run-information file. This calibrated procedure should not be
replaced without new calibration data.

## Experiment timeline

Each trial contains:

1. Jittered fixation cross: 500–700 ms.
2. Hebrew prime alone: 600 ms.
3. Prime plus central fixation: 250 ms.
4. Face sequence.
5. Post-sequence response capture: 500 ms.

The face sequence contains 3–6 repeated standard faces followed by one 50%
self/other morph deviant. Each face is displayed for 250 ms followed by a
350 ms blank, giving a 600 ms stimulus-onset asynchrony.

The prime remains visible above the face throughout the face sequence.

Target trials replace one standard or the deviant with a sunglasses version.
Participants press SPACE when they detect the target. Target trials are used
for attention monitoring and are excluded from ordinary vMMR analysis.

Hebrew is rendered with PsychoPy `TextBox2`, right-to-left layout, and
pre-display cleaning of direction-control characters and combining marks.

## Trial-table CSV files

The experiment reads:

```text
conditions/practice_trials.csv
conditions/main_trials.csv
```

Required columns:

| Column | Meaning |
|---|---|
| `primeType` | `DEATH` or `NEGATIVE` |
| `identity` | `SELF` or `OTHER` |
| `word` | Hebrew prime word |
| `nStandards` | Number of standard faces |
| `isTarget` | `1` for target, `0` otherwise |
| `targetPosition` | One-based target position; `-1` for non-target trials |
| `standardImage` | Standard face image |
| `deviantImage` | 50% morph deviant image |
| `standardTargetImage` | Sunglasses standard image |
| `deviantTargetImage` | Sunglasses morph image |

Optional columns are `block`, `condCode`, and `trial_in_block`. The experiment
can synthesize compatible defaults when these columns are absent.

The condition codes are:

| Code | Meaning |
|---|---|
| `DS` | DEATH + SELF |
| `DO` | DEATH + OTHER |
| `NS` | NEGATIVE + SELF |
| `NO` | NEGATIVE + OTHER |

## Generating the CSV tables

Open `conditions/generate_trials.ipynb` in Jupyter or VS Code and run its cells
in order.

The notebook has three logical parts:

1. Main-trial generation.
2. Practice-trial generation.
3. Read-only diagnostics.

### Main trials

The main generator:

1. Finds the project root.
2. Loads words from `stimuli/words/death_words.csv` and
   `stimuli/words/negative_words.csv`.
3. Sets a participant-specific random seed:
   `seed = BASE_SEED + PARTICIPANT_ID`.
4. Creates three blocks of 120 trials.
5. Creates 90 target and 270 non-target trials.
6. Balances prime type and identity across the four conditions.
7. Assigns 3–6 standards using balanced per-condition pools.
8. Assigns random target positions from the standard slots and final deviant
   slot.
9. Assigns words matching the prime type.
10. Adds standard, deviant, and target image paths.
11. Runs sanity checks and writes `conditions/main_trials.csv`.

The expected main table contains 360 trials: 120 per block, 90 targets, and
270 non-targets. It contains 180 DEATH and 180 NEGATIVE trials, and 180 SELF
and 180 OTHER trials.

### Practice trials

The practice generator uses a fixed seed and creates 16 trials: four for each
condition, including one target per condition. It randomizes sequence lengths
and target positions, assigns appropriate Hebrew words and image paths, and
writes `conditions/practice_trials.csv`.

### Diagnostics

Run the diagnostic cell after generation. It checks:

- total, block, target, and non-target counts;
- prime and identity balance;
- standard-sequence length distribution;
- target-position distribution;
- standard/deviant ratios;
- word integrity and coverage;
- per-block condition counts.

Do not use a generated table for data collection if these checks fail.

### Command-line generator (`conditions/generate_trials.py`)

A standard-library port of the notebook that also runs on the Windows lab PC
(no Jupyter or pandas needed). For the same participant it produces the same
trials as the notebook, but writes **relative** image paths
(`stimuli/faces/GenAI_faces/self.png`), so the tables work on any computer.

```bash
# Windows
.venv\Scripts\python conditions\generate_trials.py --participant 1
# macOS
python conditions/generate_trials.py --participant 1
# options: --faces-dir stimuli/faces/<folder>  --base-seed 42  --overwrite
# diagnostics only, on the existing CSVs:
python conditions/generate_trials.py --check-only
```

- Seed = `base_seed + participant` (default 42 + participant), as in the
  notebook. Practice uses the fixed seed 99.
- Writes `conditions/main_trials.csv` and `conditions/practice_trials.csv`
  (the files v2 reads), plus archive copies
  `conditions/generated/main_trials_sub-NNN_seed-S.csv` and
  `practice_trials_sub-NNN.csv`. It will not overwrite an existing archive
  copy unless `--overwrite` is given, and it prints the SHA-256 of every file
  it writes.
- Extra columns at the end of each row: `participant`, `seed`, `facesDir`.
  v2 ignores them.
- Before writing, it checks that all six face images exist and warns if they
  are not 425 × 405 greyscale (needs Pillow). Then it runs the diagnostics.
  If a hard rule fails (counts, balance, nStandards 3–6, target positions,
  word lists, image paths), it exits with code 1 and writes nothing.
- The diagnostics print numbers only, never the Hebrew words.

### Path portability

The notebook currently writes image paths based on the project directory found
when it runs. The experiment accepts absolute paths and resolves relative paths
against the project root. Relative paths are preferable when sharing tables
between computers.

## Stimuli

Face images are expected under `stimuli/faces/GenAI_faces/`:

```text
self.png
other.png
morph50.png
self_target.png
other_target.png
morph50_target.png
```

Faces should be aligned, grayscale, and approximately 425 × 405 pixels.
Target images should differ from their corresponding non-target images only by
the black sunglasses.

Hebrew word lists are under `stimuli/words/`. The neutral list is retained for
stimulus preparation but is not used by the current death/negative generator.

## EEG triggers

Face-event trigger codes identify prime, identity, and event role:

| Condition | STD | DEV | TARGET_STD | TARGET_DEV |
|---|---:|---:|---:|---:|
| DEATH + SELF | 11 | 12 | 13 | 14 |
| DEATH + OTHER | 21 | 22 | 23 | 24 |
| NEGATIVE + SELF | 31 | 32 | 33 | 34 |
| NEGATIVE + OTHER | 41 | 42 | 43 | 44 |

Face-onset markers are scheduled with `win.callOnFlip(...)`. Do not reuse
existing trigger values for new meanings.

## Analysis event logic

The events file contains one row per face event.

- `STD`: ordinary standard face.
- `DEV`: final morph deviant.
- `TARGET_STD`: sunglasses standard.
- `TARGET_DEV`: sunglasses deviant.

For vMMR analysis, use only non-target trials:

```text
isAnalysisStandard == 1
isAnalysisDeviant == 1
```

The analysis standard is the third standard face. The analysis deviant is the
final morph face. Exclude target trials and both target event roles.

## Photodiode and acquisition hardware

The optional photodiode square is a visual timing marker. It is not controlled
by PsychoPy hardware commands.

```text
PsychoPy display
    -> GTEC-0270 optical sensor
    -> GTEC-0274W g.TRIGbox
    -> GTEC-0274TR adapter
    -> g.HIamp DIGITAL IN
```

During normal experiment mode, the square is drawn only during face-on frames.
Photodiode test mode and LSL buffering test mode are calibration/diagnostic
modes, not ordinary experiment conditions.

## Output files

Each run writes files under `data/`:

```text
*_events.csv
*_trials.csv
*_frame_intervals.csv
*_run_info.txt
*.log
```

`*_events.csv` contains one row per face event and is used for EEG epoching.
`*_trials.csv` contains one row per trial and is used for behavioral quality
control. `*_frame_intervals.csv` is used to inspect dropped frames.
`*_run_info.txt` records participant/session metadata, display settings,
frame counts, trigger settings, LSL statistics, and photodiode configuration.

## Validation and tests

Before data collection:

1. Regenerate and diagnose both trial tables.
2. Confirm all image paths exist.
3. Run a software-only dry run.
4. Confirm one event row per face and one trial row per trial.
5. Confirm target trials are excluded from vMMR analysis flags.
6. Confirm Hebrew words render correctly.
7. Inspect frame intervals and run information.
8. Validate LSL and photodiode timing separately.

Run the automated tests from the project root:

```bash
pytest
```

The tests cover LSL behavior, marker timing, refresh/frame helpers, and trigger
backend definitions.
