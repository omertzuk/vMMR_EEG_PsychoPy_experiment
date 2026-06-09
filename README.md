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
send_LSL_triggers
photodiode_square
photodiode_test_mode
```

For the first dry run, use:

```text
participant: test001
session: 001
fullscreen: unchecked
send_LSL_triggers: unchecked
photodiode_square: unchecked
photodiode_test_mode: unchecked
```

For EEG testing, use:

```text
fullscreen: checked
send_LSL_triggers: checked
photodiode_square: checked if using photodiode validation
photodiode_test_mode: checked only for optical calibration runs
```

Do not enable LSL triggers until the lab acquisition setup has been confirmed.

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

The trigger is cleared one frame later.

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
size: 100 x 100 px
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
frame counts for each task period
LSL trigger setting
photodiode_square_enabled
photodiode_square_size_px
photodiode_square_corner
photodiode_square_margin_px
photodiode_test_mode
photodiode_hardware_chain
```

## Recommended dry-run checks

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
