# vMMR EEG Experiment — PsychoPy Coder Version

This project implements a visual mismatch response (vMMR) EEG experiment based on the Dor-Ziderman death-denial/self-face paradigm.

The experiment is implemented directly in PsychoPy Coder rather than PsychoPy Builder.

Main script:

```text
run_vMMR_experiment_v0.py
````

## Project folder

Expected root folder:

```text
C:\Users\omer\Documents\vMMR_EEG\
```

Expected structure:

```text
vMMR_EEG/
    run_vMMR_experiment_v0.py

    conditions/
        generate_trials.ipynb
        main_trials.csv
        practice_trials.csv

    stimuli/
        faces/
            self.png
            other.png
            morph50.png
            self_target.png
            other_target.png
            morph50_target.png

        words/
            death_words.csv
            negative_words.csv
            neutral_words.csv

    data/
```

The `data/` folder is where the experiment writes output files.

## Experimental design

The task is a 2 × 2 within-subject design:

```text
PRIME:    DEATH / NEGATIVE
IDENTITY: SELF / OTHER
```

Each trial contains:

```text
1. Fixation cross, jittered 500–700 ms
2. Prime word alone, 600 ms
3. Prime word + central fixation cross, 250 ms
4. Face sequence:
       3–6 standard faces
       followed by one 50% self-other morph deviant
5. Post-sequence response-capture interval, 500 ms
```

Each face event is:

```text
250 ms face on screen
350 ms blank screen
600 ms stimulus onset asynchrony
```

The prime word stays visible above the face area throughout the trial.

Target trials contain one sunglasses face. Participants press SPACE when they detect a sunglasses target.

## Trial tables

The script reads:

```text
conditions/practice_trials.csv
conditions/main_trials.csv
```

Both files must contain the following required columns:

```text
primeType
identity
word
nStandards
isTarget
targetPosition
standardImage
deviantImage
standardTargetImage
deviantTargetImage
```

Recommended additional columns:

```text
block
condCode
trial_in_block
```

Column meanings:

| Column                | Meaning                                                              |
| --------------------- | -------------------------------------------------------------------- |
| `primeType`           | `DEATH` or `NEGATIVE`                                                |
| `identity`            | `SELF` or `OTHER`                                                    |
| `word`                | Hebrew prime word                                                    |
| `nStandards`          | Number of repeated standard faces, usually 3–6                       |
| `isTarget`            | `1` for target trial, `0` for non-target trial                       |
| `targetPosition`      | Target location in the face sequence; use `-1` for non-target trials |
| `standardImage`       | Path to standard face image                                          |
| `deviantImage`        | Path to morph deviant image                                          |
| `standardTargetImage` | Path to sunglasses standard image                                    |
| `deviantTargetImage`  | Path to sunglasses morph image                                       |
| `block`               | Block number                                                         |
| `condCode`            | Condition label, e.g. `DS`, `DO`, `NS`, `NO`                         |
| `trial_in_block`      | Trial number within block                                            |

## Stimuli

Face images should be grayscale, aligned, and standardized.

Expected face image size:

```text
425 × 405 px
```

The current project may use dummy images during development. Before real data collection, replace them with participant-specific stimuli:

```text
self.png
other.png
morph50.png
self_target.png
other_target.png
morph50_target.png
```

The target images should be identical to the non-target versions except for black sunglasses.

## Running the experiment

Open PsychoPy.

Use:

```text
PsychoPy → Coder → Open → run_vMMR_experiment_v0.py
```

Run the script.

A startup dialog will appear with these fields:

```text
participant
session
fullscreen
expected_refresh_hz
send_LSL_triggers
parallel_port_address
photodiode_square
photodiode_test_mode
lsl_buffer_test_mode
lsl_keepalive_hz
lsl_nominal_srate
```

For the first dry run, use:

```text
participant: test001
session: 001
fullscreen: unchecked
expected_refresh_hz: 60
send_LSL_triggers: unchecked
parallel_port_address: 0x0378
photodiode_square: unchecked
photodiode_test_mode: unchecked
lsl_buffer_test_mode: unchecked
lsl_keepalive_hz: 1200
lsl_nominal_srate: 1200
```

For EEG testing, use:

```text
fullscreen: checked
expected_refresh_hz: 60 or 120, matching the monitor mode
send_LSL_triggers: checked
parallel_port_address: 0x0378
photodiode_square: checked if using photodiode validation
photodiode_test_mode: checked only for optical calibration runs
lsl_buffer_test_mode: checked only for LSL/Simulink buffering diagnostics
lsl_keepalive_hz: 1200
lsl_nominal_srate: 1200
```

Do not enable LSL triggers until the lab acquisition setup has been confirmed.

`expected_refresh_hz` accepts only `60` or `120`. PsychoPy measures the display
after opening the window and aborts before practice if the measured rate differs
from the expected rate by more than 2%. Common fractional rates such as 59.94 Hz
and 119.88 Hz are accepted. If PsychoPy cannot measure the display, the run log
contains a prominent warning and the configured expected rate is used; it is not
reported as a successful measurement.

All stimulus frame counts use the configured expected rate. The measured rate,
when available and valid, is used only to set the dropped-frame threshold.

| Task duration | 60 Hz | 120 Hz |
| --- | ---: | ---: |
| Fixation minimum, 500 ms | 30 frames | 60 frames |
| Fixation maximum, 700 ms | 42 frames | 84 frames |
| Prime / face SOA, 600 ms | 36 frames | 72 frames |
| Pre-face fixation / face on, 250 ms | 15 frames | 30 frames |
| Face blank, 350 ms | 21 frames | 42 frames |
| Post-sequence response capture, 500 ms | 30 frames | 60 frames |

## Response key

The current response key is:

```text
SPACE
```

If using an EEG response box, check which key name PsychoPy receives and update:

```python
RESPONSE_KEYS = ["space"]
```

inside `run_vMMR_experiment_v0.py`.

## EEG triggers

The script sends trigger codes for each face event.

Trigger codes:

| Condition        | Standard | Deviant | Target standard | Target deviant |
| ---------------- | -------: | ------: | --------------: | -------------: |
| Death / Self     |       11 |      12 |              13 |             14 |
| Death / Other    |       21 |      22 |              23 |             24 |
| Negative / Self  |       31 |      32 |              33 |             34 |
| Negative / Other |       41 |      42 |              43 |             44 |

Triggers are sent using `win.callOnFlip(...)`, so they are aligned with the screen flip on which the face appears.

The LSL stream is a continuous latched state channel for the current Simulink
receiver, not an irregular event stream. A nonzero marker is repeated for the
configured `hold_duration` (100 ms by default) and then automatically returns
to zero. Detect events offline from transitions into a nonzero value. The
parallel-port backend still clears its pulse one display frame later; the LSL
backend does not.

The marker code supplies the intended event/condition identity. The photodiode
channel remains the measurement of physical visual onset. LSL keepalive and
nominal sampling rates are independent of monitor refresh rate.

When supported by the installed `pylsl`, startup waits up to 15 seconds for the
Simulink inlet and aborts safely if none connects. Older `pylsl` versions retain
the manual “start Simulink, then press Enter” workflow.

## Photodiode / optical timing validation

The `photodiode_square` checkbox controls only whether PsychoPy draws a visible
white square on the monitor. PsychoPy does not control the g.TRIGbox directly.

Hardware chain:

```text
PsychoPy screen output
    -> GTEC-0270 optical sensor
    -> GTEC-0274W g.TRIGbox
    -> GTEC-0274TR adapter
    -> g.HIamp DIGITAL IN
```

The ordinary PsychoPy/LSL trigger marks event identity and condition. The optical
trigger marks the physical screen onset detected by the sensor. In analysis, use
the condition trigger for labels and the g.TRIGbox optical channel to estimate or
correct visual-onset delay/jitter.

The square defaults to:

```text
size: 45 x 45 px
corner: bottom_right
margin: 40 px
color: white
```

When `photodiode_square` is checked during the experiment, the square is drawn
only during face-on frames. It is not drawn during fixation, prime-only,
prime-plus-fixation, blank, instruction, or rest screens.

For calibration, check `photodiode_test_mode`. This flashes the square 100 times
before the real experiment and then quits. It writes:

```text
<participant>_ses-<session>_<timestamp>_photodiode_test.csv
```

Each flash is 250 ms on and 350 ms black, using the same frame-count conversion
as the face events. If `send_LSL_triggers` is checked, marker `99` is sent on the
same flip as each flash onset during this test mode.

### LSL buffering diagnostic

Use `lsl_buffer_test_mode` to test whether a long delay between PsychoPy markers
and the optical g.TRIGbox channel is caused by the LSL/Simulink acquisition path
rather than true display latency. This mode is separate from the vMMR task: it
opens the LSL outlet and PsychoPy window, runs the diagnostic, writes a CSV file,
and quits before loading or running the real experiment.

Recommended settings:

```text
send_LSL_triggers: checked
photodiode_square: either checked or unchecked
photodiode_test_mode: unchecked
lsl_buffer_test_mode: checked
expected_refresh_hz: 60 or 120, matching the monitor mode
lsl_keepalive_hz: 1200
lsl_nominal_srate: 1200
```

The diagnostic starts with a 2 s black baseline, then repeats 100 flashes:

```text
experiment-start marker: 9, sent before the black baseline
white square on: 250 ms
black screen off: 750 ms
marker codes: 101, 102, ..., 200
square: 45 x 45 px, bottom_right, 40 px margin
```

Each LSL marker is sent on the same `win.flip()` that draws the square. The
diagnostic writes:

```text
<participant>_ses-<session>_<timestamp>_lsl_buffer_test.csv
```

Important columns:

```text
flash_index
marker_code
psychopy_global_onset_time
lsl_push_timestamp
psychopy_flip_timestamp
lsl_event_timestamp
expected_refresh_hz
measured_refresh_hz
frame_rate
on_frames
off_frames
```

`psychopy_flip_timestamp` is recorded before the LSL push callback runs, and
`lsl_event_timestamp` is the exact `pylsl.local_clock()` timestamp attached to
the event sample. These clocks may have different origins; do not subtract the
two columns directly unless they have first been mapped to a common clock.

Compare the PsychoPy CSV, Simulink LSL markers `101`-`200`, and the g.HIamp
photodiode channel. If PsychoPy reports that the LSL marker was pushed on the
same flip as the square but Simulink shows a large lag to the optical edge, the
likely cause is LSL/Simulink buffering or timestamp handling. If this diagnostic
has a small stable lag but the real task does not, check whether the real-task
comparison is matching the photodiode pulse to the corresponding face-event
trigger rather than to a trial-start or prime event.

You can repeat the diagnostic with lower `lsl_keepalive_hz` and
`lsl_nominal_srate` values, such as 100 or 10, to see whether the apparent lag
changes with LSL stream rate.

## Output files

Each run writes files to `data/`.

Example:

```text
test001_ses-001_20260525_143500_events.csv
test001_ses-001_20260525_143500_trials.csv
test001_ses-001_20260525_143500_frame_intervals.csv
test001_ses-001_20260525_143500_run_info.txt
test001_ses-001_20260525_143500.log
```

### Events file

The `_events.csv` file contains one row per face event.

Use this file for EEG epoching.

Important columns:

```text
phase
block
trial_global
trial_in_block
primeType
identity
condCode
word
eventIndex
eventRole
eventImage
isAnalysisStandard
isAnalysisDeviant
triggerCode
onsetTime
```

Analysis flags:

```text
isAnalysisStandard == 1
```

means the third standard face of a non-target trial.

```text
isAnalysisDeviant == 1
```

means the deviant morph face of a non-target trial.

Target trials are excluded from these analysis flags.

### Trials file

The `_trials.csv` file contains one row per trial.

Use this file for behavioral QC.

Important columns:

```text
phase
block
trial_global
trial_in_block
primeType
identity
isTargetTrial
targetPosition
targetOnset
responseType
rt
nPresses
correct
```

Possible response types:

```text
hit
miss
false_alarm
correct_rejection
```

A response counts as a hit if it occurs within 1 second after the target onset.

### Frame intervals file

The `_frame_intervals.csv` file contains frame timing diagnostics.

Use this file to check whether frames were dropped during actual trial presentation.

Instruction and rest screens are not included in the frame interval log.

### Run info file

The `_run_info.txt` file records:

```text
participant
session
timestamp
measured frame rate
expected refresh rate
refresh measurement success and expected/measured difference
dropped-frame threshold
frame counts for each task period
intended and realized duration for each frame count
LSL trigger setting
LSL keepalive, nominal sampling rate, hold duration, and manual-clear setting
photodiode_square_enabled
photodiode_square_size_px
photodiode_square_corner
photodiode_square_margin_px
photodiode_test_mode
lsl_buffer_test_mode
lsl_buffer_test marker range and flash settings
photodiode_hardware_chain
```

## Recommended dry-run checks

### 60 Hz dry run

1. Set the operating-system display mode to 60 Hz.
2. Run `run_vMMR_experiment_v0.py` with `expected_refresh_hz: 60`.
3. For a software-only run, uncheck `send_LSL_triggers`,
   `photodiode_square`, `photodiode_test_mode`, and `lsl_buffer_test_mode`.
4. Confirm the run-info file reports 15 face-on frames, 21 blank frames, and a
   36-frame face SOA.

### 120 Hz dry run

1. Set the operating-system display mode to 120 Hz.
2. Run `run_vMMR_experiment_v0.py` with `expected_refresh_hz: 120`.
3. Use the same software-only settings as the 60 Hz dry run.
4. Confirm the run-info file reports 30 face-on frames, 42 blank frames, and a
   72-frame face SOA.

### Photodiode test

Run `run_vMMR_experiment_v0.py` with the correct `expected_refresh_hz`, check
`photodiode_test_mode`, and check `send_LSL_triggers` when comparing the
software marker with the optical channel. Place the GTEC-0270 sensor on the
bottom-right square before the flashes begin. The mode writes
`*_photodiode_test.csv` and exits before practice.

### LSL buffering test

Start the Simulink model, then run `run_vMMR_experiment_v0.py` with the correct
`expected_refresh_hz`, `send_LSL_triggers`, and `lsl_buffer_test_mode` checked;
leave `photodiode_test_mode` unchecked. Place the optical sensor on the
bottom-right square. The mode writes `*_lsl_buffer_test.csv` and exits before
loading the trial tables.

For both monitor modes, inspect `*_frame_intervals.csv` for dropped frames and
confirm in the acquired data that each LSL code remains nonzero for about
100 ms, returns to zero before the next 600 ms face onset, and final marker `99`
is recorded before the stream shuts down.

After the first full dummy run, check:

```text
1. Did the script run without crashing?
2. Were all expected files created in data/?
3. Does _events.csv contain one row per face event?
4. Does _trials.csv contain one row per trial?
5. Are there 360 main trials?
6. Are there 90 target trials in the main experiment?
7. Are target trials excluded from isAnalysisStandard/isAnalysisDeviant?
8. Is eventIndex == 3 marked as the standard comparator only on non-target trials?
9. Is the final non-target deviant marked as isAnalysisDeviant == 1?
10. Do Hebrew words display correctly?
11. Does SPACE register as the response key?
12. Are frame intervals stable?
13. Are EEG triggers detected correctly by the acquisition system?
14. If using a photodiode, does the photodiode timing match the trigger timing?
```

## EEG analysis notes

For the vMMR analysis, use only non-target trials.

Use:

```text
isAnalysisStandard == 1
```

as the standard event.

Use:

```text
isAnalysisDeviant == 1
```

as the deviant event.

Exclude:

```text
eventRole == TARGET_STD
eventRole == TARGET_DEV
isTargetTrial == 1
```

Suggested EEG epochs:

```text
-100 ms to +500 ms around face onset
```

Suggested baseline:

```text
-100 ms to 0 ms
```

## Known implementation notes

1. The script uses frame-based timing.
2. The prime word remains visible throughout the trial.
3. A 500 ms post-sequence interval was added to capture late responses to targets appearing in the final face position.
4. The current response key is SPACE.
5. Hebrew rendering uses `languageStyle="RTL"` in the PsychoPy `TextBox2`.
6. EEG triggers are optional and disabled by default.
7. The script is currently version `v0`; preserve this file unchanged once dry-run testing starts.

## Versioning recommendation

Do not overwrite `run_vMMR_experiment_v0.py` after the first successful dry run.

For changes, create new versions:

```text
run_vMMR_experiment_v1.py
run_vMMR_experiment_v2.py
```

Keep notes in this README or in a separate changelog:

```text
CHANGELOG.md
```

### v1: LSL outlet after the refresh-rate measurement (2026-10-08)

```text
run_vMMR_experiment_v1_trig_after_framerate_measurement.py
run_photodiode_latency_v1_trig_after_framerate_measurement.py
```

Photodiode latency runs with LSL timestamps (`notebooks/photodiode_latency_compare.ipynb`)
showed that the first flips of the new fullscreen window (start of `getActualFrameRate`)
pause PsychoPy for about 0.8 s. In v0 the LSL outlet already existed at that point, so
the marker stream paused too. The Simulink model takes one LSL sample per step, so it
stalled and never caught up (`lsl_trigger.py` resyncs after pauses > 0.1 s instead of
sending the missed samples): all EEG data lagged the markers by about 0.8 s for the whole
run, and every v0 `*_run_info.txt` shows `lsl_resyncs: 1`.

Changes in v1:

* The window is opened and the refresh rate measured **before** the LSL outlet is created.
* The "start the Simulink model" prompt is shown on the stimulus screen instead of the
  console (the fullscreen window covers the console). The latency test waits for SPACE;
  the experiment waits for the Simulink inlet to connect, as before.
* `expected_refresh_hz` defaults to `59.94`, the measured rate of the stimulus display
  (`timing_utils.py` now also accepts 59.94 and 119.88). Frame counts are the same as at
  60 Hz; logged durations are now exact.
* The experiment's `*_run_info.txt` ends with `lsl_samples_sent`, `lsl_seconds`,
  `lsl_rate_hz` and `lsl_resyncs`. `lsl_resyncs` should be `0`.

Trial structure, frame timing, trigger codes and output schema are unchanged.

`run_photodiode_latency_v2_trig_after_space_input.py` goes one step further for the
latency test: the LSL outlet is created only after SPACE on the sensor-alignment screen
(order: window → refresh measurement → alignment screen → LSL outlet → "start Simulink"
screen → START marker 9 → baseline → calibration → flashes).

From 2026-10-13 all three latency scripts (v0, v1, v2) show an **experiment-start screen**
after the sensor-alignment screen. SPACE there sends marker **1** (experiment start) on the
next flip; the baseline, calibration (5/6/5) and flashes follow, so the calibration
timeline is counted from marker 1. `notebooks/photodiode_latency_compare.ipynb` ignores
everything before marker 1 when it is present (file-name tag `expstart`).

### Calibration database (`run_photodiode_latency_database.py`)

The final configuration for building the marker-timing correction database: v1 start-up
order, experiment-start marker 1, LSL 600 Hz, `expected_refresh_hz` 59.94, Simulink frame
length 8, square and optical sensor always at the **screen centre** (where faces and primes
appear; the sensor is not moved during the database). Dialog choices: `run_type` (`short` =
100 flashes, `long` = 500 flashes with the width ramp repeating every 100), operator, cold
start, notes. The run number increments per day and the
"start Simulink" screen shows the exact EEG file names to enter in both `To File` blocks
(`photodiode_db_<date>_<run>_slx_frame_length_8_timestamped_LSL_trig_after_framerate_expstart_sq<position>_<type>.mat`
and `..._LSLtiming.mat`). `run_info` records software versions, the git commit and SHA-256
hashes of the script and `lsl_trigger.py`; every run is appended to `data/database_run_log.csv`.
Commit all changes before database runs so `git_tracked_changes: no` is recorded.

The Simulink model used on the recording computer (with the `LSLMarkerTimestamps` block)
is in `matlab/on_eeg_computer/` (`HIamp_record_LSL_DD_vMMR.slx`, `LSLMarkerTimestamps.m`;
R2020a, liblsl-Matlab required). The protocol for the two database days is in
`docs/calibration_database_plan_2026-10.docx`.

In the end the database (14–15 October 2026) was recorded with
`run_photodiode_latency_v1_trig_after_framerate_measurement.py` (centre square since commit
`0cc537d`; `on_cycle` 100 for long runs), not with the database script; see below.

## Marker timing correction (calibrated 2026-10-15)

Every event time used in EEG analysis must be corrected:

```text
event onset (EEG model time) = t_B + offset_BA − B + 62.4 ms
```

`t_B` is the LSL send timestamp (computer B), `offset_BA` LSL's clock offset, and `B` the
90th percentile of `t_A − model time` within ±10 s of the event (computer A's LSL clock
against the amplifier sample clock). All three come from the `LSLMarkerTimestamps` block,
saved by the recording model as `<recording>_LSLtiming.mat`. **Do not use the marker channel
of `EEG_data` (g.HIsys LSL Receive) for event timing**: it varies by ~9 ms between sessions.

* Correction: **62.4 ms** (95 % CI 61.7–63.0; between-session SD 1.4 ms; a new session is
  expected within 59.4–65.3 ms). Per event: SD 5.7 ms, all within one display frame.
  Valid for stimuli at the screen centre (bottom-right corner: +2.0 ms).
* Code: `analysis/marker_timing.py`

  ```python
  import sys; sys.path.insert(0, "analysis")
  from marker_timing import correct_events, to_mne_events
  events, qc = correct_events("recording.mat", run_info="..._run_info.txt")
  assert qc["passed"], qc["problems"]          # lsl_resyncs 0, no lasting backlog
  mne_events = to_mne_events(events, codes=[11, 12, 21, 22, 31, 32, 41, 42])
  ```

  or `.venv/Scripts/python analysis/marker_timing.py recording.mat --run-info ..._run_info.txt`
  (writes `recording_events_corrected.csv`). Reading the `.mat` files needs `h5py`.
* Calibration analysis: `analysis/calibration_database_analysis.py` (reproduces every number
  and figure of the supplement from `data/EEG/final database/`: `EEG_Computer_A/`,
  `Computer_B/`, `run_manifest.csv`; outputs in `data/analysis/calibration_database/`).
* Methods: `docs/supplement_marker_timing_calibration_2026-10-15.docx`; lab guide (settings and
  scripts on both computers): `docs/lab_guide_marker_timing_2026-10.docx`; open work:
  `docs/todo_experiment_and_analysis_2026-10.docx`.
* The constant is tied to the locked configuration (display 59.94 Hz, LSL 600 Hz, g.HIamp
  600 Hz frame length 8, v1 sender, model in `matlab/on_eeg_computer/`). After any change to
  hardware, drivers, display settings, PsychoPy, `lsl_trigger.py` or the model, record at
  least 3 calibration sessions and compare them with the database.

## Minimal pre-data-collection checklist

Before collecting real EEG data:

```text
[ ] main_trials.csv validated
[ ] practice_trials.csv validated
[ ] real participant-specific face stimuli created
[ ] Hebrew words display correctly
[ ] response box key name confirmed
[ ] monitor refresh rate confirmed
[ ] no systematic dropped frames
[ ] EEG triggers received correctly
[ ] trigger values match condition/event role
[ ] photodiode timing checked if available
[ ] full dummy run completed
[ ] one pilot participant completed
[ ] analysis pipeline can read the output files
```
