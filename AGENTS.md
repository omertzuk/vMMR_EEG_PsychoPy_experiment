# AGENTS.md

## Project overview

This repository implements a PsychoPy Coder version of a visual mismatch response
EEG experiment based on the Dor-Ziderman self-face / death-prime paradigm.

This is not a generic PsychoPy demo. It is a timing-sensitive EEG experiment, so
future changes must preserve:

* frame-based stimulus timing;
* EEG/LSL trigger timing;
* trial and event logging;
* Hebrew text rendering;
* compatibility with the existing trial CSV structure;
* the scientific logic of the vMMR design.

## Main files

* `run_vMMR_experiment_v0.py`

  * main PsychoPy Coder experiment;
  * reads trial tables from `conditions/`;
  * presents fixation, prime words, face sequences, targets, and block breaks;
  * writes events, trials, frame-interval diagnostics, run-info, and PsychoPy
    logs;
  * sends optional LSL triggers.

* `lsl_trigger.py`

  * provides `LSLTrigger`;
  * creates an LSL stream named `experiment_markers`;
  * sends integer marker codes;
  * keeps the stream alive at 600 Hz by pushing zero markers;
  * exposes the same basic interface expected by the experiment: `.set(code)`,
    `.clear()`, `.stop()`.

* `README.md`

  * documents the project structure, running instructions, trial-table schema,
    stimuli, output files, and trigger logic.

## Experimental design

The core task is a 2 x 2 within-subject design:

* `PRIME`: `DEATH` / `NEGATIVE`
* `IDENTITY`: `SELF` / `OTHER`

Each trial contains:

1. jittered fixation cross, 500-700 ms;
2. Hebrew prime word alone, 600 ms;
3. prime word + central fixation cross, 250 ms;
4. face sequence:
   * 3-6 standard faces;
   * followed by one 50% self-other morph deviant;
5. post-sequence response-capture interval, 500 ms.

Each face event is:

* 250 ms face visible;
* 350 ms blank;
* 600 ms SOA.

The prime word stays visible above the face area during the face sequence.

Target trials contain one sunglasses face. Participants press SPACE when
detecting sunglasses. Targets are for attention monitoring and should not be
used as ordinary vMMR analysis events.

## vMMR analysis logic

Preserve this analysis logic in the event output:

* Standard events have role `STD`.
* Deviant events have role `DEV`.
* Target events have role `TARGET_STD` or `TARGET_DEV`.
* The third standard is the preferred standard comparator for vMMR analysis.
* The final morph face is the deviant event.
* Target trials/events should be marked clearly so they can be excluded from
  vMMR analysis.

Do not change this scientific logic unless the user explicitly asks for a design
change.

## Trial tables

The experiment reads:

```text
conditions/practice_trials.csv
conditions/main_trials.csv
```

Required columns:

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

Keep compatibility with these columns. If new columns are added, they should be
backward-compatible and documented.

## Stimuli

Face stimuli are expected to be grayscale, aligned, and standardized.

Expected face size:

```text
425 x 405 px
```

The experiment uses:

```text
self.png
other.png
morph50.png
self_target.png
other_target.png
morph50_target.png
```

Target images should match the non-target image except for black sunglasses.

## Timing rules

This is an EEG experiment. Timing changes must be handled carefully.

Do:

* use frame-based presentation;
* preserve `win.waitBlanking=True`;
* use `win.callOnFlip(...)` for event triggers that should align with visual
  onset;
* keep image stimuli preloaded;
* keep frame-interval diagnostics;
* preserve output of run-info and timing metadata.

Do not:

* replace frame-based timing with arbitrary `core.wait()` calls during stimulus
  presentation;
* load images inside a trial or face-event loop;
* send onset triggers before the relevant `win.flip()`;
* draw extra stimuli during face-on frames unless intentionally required.

## Hebrew text rendering

The prime words are Hebrew.

The current code uses `visual.TextBox2` with:

* `languageStyle="RTL"`;
* centered alignment;
* `clean_hebrew_for_display(...)` to remove problematic direction/control
  characters.

Do not replace Hebrew rendering with plain `TextStim` unless it is explicitly
tested on the lab computer and Hebrew words display correctly.

## Trigger logic

The experiment uses LSL markers via `LSLTrigger`.

Current event trigger map:

* `11`: DEATH SELF STD
* `12`: DEATH SELF DEV
* `13`: DEATH SELF TARGET_STD
* `14`: DEATH SELF TARGET_DEV
* `21`: DEATH OTHER STD
* `22`: DEATH OTHER DEV
* `23`: DEATH OTHER TARGET_STD
* `24`: DEATH OTHER TARGET_DEV
* `31`: NEGATIVE SELF STD
* `32`: NEGATIVE SELF DEV
* `33`: NEGATIVE SELF TARGET_STD
* `34`: NEGATIVE SELF TARGET_DEV
* `41`: NEGATIVE OTHER STD
* `42`: NEGATIVE OTHER DEV
* `43`: NEGATIVE OTHER TARGET_STD
* `44`: NEGATIVE OTHER TARGET_DEV

Prime-onset triggers:

* `51`: DEATH SELF
* `52`: DEATH OTHER
* `61`: NEGATIVE SELF
* `62`: NEGATIVE OTHER

Other existing markers:

* `1`: experiment start
* `70`: practice phase start
* `71`: practice phase end
* `72`: main experiment start
* `73`: block start
* `74`: block end
* `75`: rest start
* `76`: rest end
* `80`: fixation onset
* `90`: participant button press
* `99`: experiment end

Do not reuse existing trigger values for new meanings.

## Photodiode / g.tec optical sensor integration context

The lab has the following g.tec equipment:

* `GTEC-0274W`: g.TRIGbox
* `GTEC-0270`: Optical sensor, two units
* `GTEC-0274TR`: Adapter for trigger cable for g.USBamp/g.HIamp/g.Nautilus
* g.tec g.HIamp amplifier

Intended hardware chain:

```text
PsychoPy visual output
    -> white photodiode square on monitor
    -> GTEC-0270 optical sensor attached to that screen location
    -> g.TRIGbox
    -> GTEC-0274TR adapter
    -> g.HIamp DIGITAL IN
    -> optical trigger recorded with EEG
```

Important distinction:

* PsychoPy/LSL trigger = condition identity and intended event label.
* Optical sensor / g.TRIGbox trigger = physical visual onset detected from the
  screen.

The photodiode square should be optional. It should be enabled for
calibration/timing-validation sessions and disabled once the lab decides it is
no longer needed during actual experiment runs.

Future photodiode code should preserve this policy:

* startup dialog option: `photodiode_square`;
* if `photodiode_square` is `False`, do not draw the white square during the
  experiment;
* if `photodiode_square` is `True`, draw the white square only during face-on
  frames;
* do not draw the square during blank, fixation, prime-only, instructions, or
  rest screens;
* optional photodiode test mode may force the square on for calibration, but
  should be clearly separate from real experiment mode.

The square is only a visual timing marker. PsychoPy does not control the
g.TRIGbox directly.

## Output files

Preserve the existing outputs:

* `*_events.csv`
* `*_trials.csv`
* `*_frame_intervals.csv`
* `*_run_info.txt`
* PsychoPy `.log`

When adding new features, update the run-info file with enough metadata to
reproduce the session.

For photodiode-related work, log:

* whether the photodiode square was enabled;
* square size in pixels;
* square position/corner;
* whether photodiode test mode was used;
* intended hardware chain.

## Coding style

Use simple, readable Python.

Prefer small helper functions over large inline blocks.

Keep existing naming conventions where possible.

Avoid broad rewrites unless necessary.

Any change to timing, triggers, trial structure, or output schema should be
documented in comments and in `README.md` when relevant.

## Validation checklist for future code changes

After modifying the experiment, future agents should check:

1. The script starts and shows the startup dialog.
2. Practice trials run without crashing.
3. Main trials can run when `all_rows` includes `main_rows`.
4. ESC abort works.
5. Hebrew words display correctly.
6. Face stimuli are preloaded before trials.
7. The frame-count conversion is still based on measured refresh rate.
8. Event CSV still contains one row per face event.
9. Trial CSV still contains one row per trial.
10. LSL triggers still use `win.callOnFlip(...)` for face-event onset.
11. Target trials are still logged separately from ordinary STD/DEV events.
12. Photodiode square, if enabled, is drawn only during face-on frames.
13. If photodiode square is disabled, the experiment display is unchanged.

## Development instructions for agents

When asked to implement a feature:

1. First inspect the relevant files.
2. Make the smallest safe change.
3. Do not silently alter the experimental design.
4. Preserve backward compatibility with existing trial CSVs.
5. Update `README.md` or `AGENTS.md` if the feature changes usage or
   assumptions.
6. Prefer adding diagnostics over removing them.
7. Explain any timing-sensitive change in the final response.

Create only `AGENTS.md` for this task. Do not implement photodiode integration
unless the user explicitly requests it.
