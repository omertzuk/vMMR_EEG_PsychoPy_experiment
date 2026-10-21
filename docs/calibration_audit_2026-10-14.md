# Audit report: vMMR marker-timing calibration (2026-10-14)

Read-only audit of this checkout on the lab PC. Nothing was modified, staged or committed during the
audit, and no experiment script or Simulink model was run. Paths are relative to the repo root;
`file:N` means line N of that file at commit 5d7da35.

**Biggest finding:** the next-step list used for this audit is older than the repo. Step 1 and most of
step 2 were already done on 13 Oct. The decisions are written up in
`docs/collaborator_update_2026-10-13.docx`: v1, frame length 8, correction = LSL timestamp + about
**56 ms**. That's 56, not 53.

Next steps audited:

1. Repeat the fixed sender (v1) 3-5 times with the timestamp model.
2. Re-test Simulink frame length (1, 2, 4, 8) with v1.
3. Choose the correction method: recorded marker + constant, or LSL timestamp + ~53 ms.
4. Keep LSLMarkerTimestamps in the experiment model and save `*_LSLtiming.mat` each session.
5. Fix `run_vMMR_experiment_v1_trig_after_framerate_measurement.py` defaults:
   `lsl_keepalive_hz` / `lsl_nominal_srate` 1200 -> 600.
6. Optional: in `lsl_trigger.py` send missed samples after a pause (raise `_MAX_CATCHUP_S`);
   check `lsl_resyncs` in every `*_run_info.txt`.
7. Final test with the v1 experiment script, photodiode square on face-on frames, timestamp model.
8. Document the final configuration in `README.md` and `AGENTS.md`.

---

## 1. This computer

**It's computer B, the PsychoPy stimulus PC. Confidence: high.** Hostname is `edu303747-aberkovic`.

| Evidence | Points to |
|---|---|
| `.venv` (uv, CPython **3.10.22**): psychopy **2026.2.4** and pylsl **1.18.5** import fine | B |
| `data/` holds PsychoPy outputs written here (`*_run_info.txt`, `*_latency_flashes.csv`, `*.log`). `__pycache__` shows the latency scripts were compiled with cpython-310 on this PC | B |
| `lsl_api.cfg` (untracked) has `KnownPeers = {192.168.50.1}`. This PC is 192.168.50.2. The 13-Oct update doc calls `lsl_api.cfg` "network setting of computer B" | B |
| MATLAB **R2025a** is installed, but there's no g.HIsys/g.tec toolbox, no liblsl-Matlab, and `Documents/MATLAB` is empty. Every `.slx` was saved in **R2020a** | not A |
| The `.slx` To File paths point to `E:\ACADEMIA\PhD\WP5\...`. **This PC has no E: drive** | not A |
| `data/EEG/**/*.mat` are copies of A's recordings | copied over |

**Python environment:**

* `.venv` has psychopy, pylsl, scipy 1.15.3, pandas 2.3.3, matplotlib, numpy 2.2.6 and ipykernel.
* **`h5py` is not installed.** Both latency notebooks `import h5py` at the top, so they won't run in this venv.
* The notebooks declare a Jupyter kernel named `mne`, which doesn't exist on this PC. The only kernel is the venv's `python3`.
* `environment.yml` describes a conda env `vmmr-eeg`, but conda isn't installed here.

## 2. Git state

* Current branch is `photodiode-latency-calibration`, tracking `origin/photodiode-latency-calibration` (5d7da35, up to date as of the last fetch).
* `origin` = github.com/DanielAtad/vMMR_EEG_PsychoPy_experiment
* `upstream` = github.com/omertzuk/vMMR_EEG_PsychoPy_experiment
* `upstream/main` is still 0f8916e, so the calibration branch had **not been merged upstream** at the last fetch.
* Local `main` = 0f8916e.

| Commit | Date | Author | Subject |
|---|---|---|---|
| 5d7da35 | 2026-10-13 | DanielAtad | Add experiment-start marker, calibration-database script, plan and update docs |
| 3617721 | 2026-10-08 | DanielAtad | Fix ~0.8 s marker lag: create LSL stream after window setup; add calibration analysis and report |
| 0f8916e | 2026-10-07 | omertzuk | Fixed the LSL sync issue |
| 105f6f9 | 2026-10-07 | omertzuk | Another update for the latency test |
| d629994 | 2026-10-07 | omertzuk | Adding changing duration for the pulses |
| a3621ff | 2026-10-06 | omertzuk | Small import error fixes of the new run_photodiode_latency_v0 |
| 037d035 | 2026-10-06 | omertzuk | Adding run_photodiode_latency_v0 Python script |
| ca07f9b | 2026-07-14 | Omer80 | Fixing triggers through LSL |
| 71a130e | 2026-07-09 | Omer80 | Correcting the generate trials notebook |
| 276ea47 | 2026-06-29 | Omer80 | Fixing the environment file |
| d84ce7d | 2026-06-23 | Omer80 | Added test to run timing decomposition file |
| 80a37e4 | 2026-06-23 | Omer Tzuk | Merge pull request #5 |
| c8d906b | 2026-06-23 | Omer80 | Updating notebooks |
| 3a661b1 | 2026-06-22 | DanielAtad | Working photodiode test |
| 7eb9df1 | 2026-06-22 | Omer Tzuk | Merge pull request #4 |

**No tracked files were modified at audit time.** There were four untracked files:

| File | What it is | Matters? |
|---|---|---|
| `docs/~$MR_marker_timing_calibration_2026-10-08.docx` | Word lock file (162 B) | No, it's junk |
| `lsl_api.cfg` | B's LSL peer config (A = 192.168.50.1). Left out of git on purpose | **Yes**: keep it, B needs it to find A |
| `matlab/LSLMarkerTimestampReceiver.m` (Oct 7) | Earlier draft of the System block: 4×1 output fed into the Mux, sample time 1/600, `LibPath` parameter | Not used by any model; replaced by `LSLMarkerTimestamps.m` |
| `matlab/align_markers_to_eeg.m` (Oct 7) | Places B markers on the EEG sample axis. It expects the **last 4 rows of `EEG_data`** to come from the draft block | Won't work with the current layout (timing in a separate `*_LSLtiming.mat`, 1×6). Could be a starting point for step 3's pipeline function |

The database script's dirty check uses `--untracked-files=no`, so untracked files don't count as
"dirty" (`run_photodiode_latency_database.py:172`).

## 3. Which file is which

There is **no `timestamped_LSL_model/` folder.** According to the compare notebook (cell 0), its
contents moved to `matlab/on_eeg_computer/` on 13 Oct.

| File | Role | Version | Use now? | PC | Steps |
|---|---|---|---|---|---|
| `run_photodiode_latency_v0.py` | latency sender | v0: outlet created before the window | **Superseded** (has the stall) | B | – |
| `run_photodiode_latency_v1_trig_after_framerate_measurement.py` | latency sender | v1 | **Yes**, the chosen sender | B | 1, 2 |
| `run_photodiode_latency_v2_trig_after_space_input.py` | latency sender | v2 | Alternative, not chosen | B | – |
| `run_photodiode_latency_database.py` | database sender: centre square, short/long runs, run log, hashes | v1-based, "frozen" | **Yes**, for the database (the collaborator's next step) | B | 3 |
| `run_vMMR_experiment_v1_trig_after_framerate_measurement.py` | experiment | v1 | **Yes, after fixes** | B | 5, 7 |
| `run_vMMR_experiment_v0.py` | experiment | v0 | Superseded | B | – |
| `run_vMMR_experiment_20260526.py`, `_20260609.py` | old experiment, parallel port only | old | Superseded | B | – |
| `run_timing_decomposition_v0.py` | June factorial timing diagnostic | old | Superseded | B | – |
| `lsl_trigger.py` | LSL outlet (latched, count-based keepalive) | current | Yes | B | 5, 6 |
| `timing_utils.py` | frame helpers; accepts 59.94 / 119.88 | current | Yes | B | 5 |
| `tests/` (`test_lsl_trigger`, `test_timing_utils`, `test_trigger_backends_static`) | unit tests | current | Yes; rerun after changes | B | 5, 6 |
| `notebooks/photodiode_latency_test.ipynb` | single-recording analysis, no timestamps | old | **Superseded** by compare | analysis | – |
| `notebooks/photodiode_latency_compare.ipynb` | multi-recording + LSL-timestamp analysis | current | **Yes** | analysis | 1, 2, 3, 7 |
| `notebooks/open_EEG_recordings*.ipynb`, `photodiode_channels.csv` | June/July loaders and data | old | Not relevant | – | – |
| `matlab/on_eeg_computer/HIamp_record_LSL_DD_vMMR.slx` | recording model **with the timestamp block** | newest (10-13) | **Yes** | A | 1, 2, 4, 7 |
| `matlab/on_eeg_computer/LSLMarkerTimestamps.m` | System-block class | current | **Yes** | A | 1, 4 |
| `HIamp_record_LSL_DD_vMMR_new.slx` (root) | recording model of 10-07 | LSL Receive at **200 Hz**, no timestamp block | Superseded | A | – |
| `HIamp_record_LSL_DD_vMMR.slx` (root) | June experiment model | 1200 Hz, stop on **99** | Superseded. **Same file name as the on_eeg_computer model** | A | – |
| `HIamp_record_LSL_DD_photodiode_delay_test.slx` | June photodiode model | 1200 Hz, stop on 255 | Superseded | A | – |
| `matlab/LSLMarkerTimestampReceiver.m`, `matlab/align_markers_to_eeg.m` | untracked drafts | old | No (see §2) | A | (3) |
| `README.md` | docs | partly updated | Needs edits | – | 8 |
| `AGENTS.md` | docs | stale (see §10) | Needs edits | – | 8 |
| `docs/*.docx` | reports, database protocol, update | 10-13 | Reference | – | 3 |

## 4. Sender scripts

| | Latency v0 | Latency v1 | Latency v2 | Database | Experiment v0 | Experiment v1 |
|---|---|---|---|---|---|---|
| LSLTrigger created | **before** the window (`:351`) | after window `:387` and refresh measurement `:396`, at `:429` | after the alignment-screen SPACE `:439`, at `:443` | after window and refresh, `:369` | **before** the window (`:1003` vs `:1037`) | after window `:1019` and refresh `:1028`, at `:1097` |
| Simulink prompt | console `input()` | screen + SPACE | screen + SPACE | screen + SPACE (shows file names) | `wait_for_consumers(15)` | screen + `wait_for_consumers(15)` |
| expected_refresh_hz | 59.94 | 59.94 | 59.94 | 59.94 (fixed) | **"60"** (`:937`) | 59.94 (`:951`) |
| keepalive / nominal | 600/600 | 600/600 (`:345`) | 600/600 | 600 fixed (`:369`) | **1200/1200** | **1200/1200** (`:957-958`) |
| n_flashes | 100 | 100 | 100 | 100 short / 500 long | – | – |
| Screen | 1920×1080 | 1920×1080 | 1920×1080 | 1920×1080 | 1200×800 + fullscr | 1200×800 + fullscr |
| Square | 45 px bottom-right | 45 px bottom-right | 45 px bottom-right | 45 px **centre** | – | 45 px bottom-right |
| photodiode_square / test_mode | – | – | – | – | True / False | **True** / False |
| Markers | 9, 1, 5/6/5, 7, 20, **255** | same | same | same | 9 start, 11–44, **99** end | 9 start (`:1283`), 11–44, **99** end (`:1364`) |
| run_info LSL stats | rate/resyncs (`:493-494`) | `:528-531` | `:539-542` | + `database_run_log.csv` | none | `:1352-1356` |

Defaults that don't match 600 Hz / 59.94 Hz:

* Experiment v0: 60 Hz and 1200 Hz.
* **Experiment v1: 1200 Hz.**
* README dry-run settings: 1200 (lines 197-198, 211-212, 342-343).

## 5. `lsl_trigger.py`

* Current values: `_KEEPALIVE_HZ = 600.0`, `_NOMINAL_SRATE = 600.0` (`:54-55`), `_END_CODE = 255` (`:56`), `_HOLD_DURATION = 0.100` (`:57`), `_MAX_CATCHUP_S = 0.100` (`:58`).
* **What happens after a pause longer than `_MAX_CATCHUP_S`** (`_push_due`, `:142-151`):
  1. The code computes `due` samples. Any count above `max_due = 0.1 × 600 = 60` triggers the reset.
  2. On reset, `_t0` is set to now, `_pushed` to 0, `due` to 1 (or 0), and `_resyncs` is incremented.
  3. **The missed samples are never sent.** The stream has a permanent gap, and Simulink (one sample per step) is shifted by the pause for the rest of the run.
* `stats()` (`:209-221`) returns `samples_sent`, `seconds`, `rate_hz` and `resyncs`, all counted since the keepalive started.
* **What step 6 would need:**
  * Raise `_MAX_CATCHUP_S` (e.g. to 2 s), or make it a constructor argument and log it in run_info.
  * Update `tests/test_lsl_trigger.py:210` (`test_stall_longer_than_max_catchup_resyncs_without_burst`), which tests the current behaviour.
  * Decide whether a catch-up burst of up to ~1200 samples is acceptable for the Simulink inlet.

## 6. Simulink models

All four models were saved in R2020a and stop at `StopTime` 10000 s.

| | `on_eeg_computer/HIamp_record_LSL_DD_vMMR.slx` | root `..._vMMR_new.slx` | root `..._vMMR.slx` | root `..._photodiode_delay_test.slx` |
|---|---|---|---|---|
| LSL Receive (g.HIsys) | `experiment_markers`, **600 Hz** | **200 Hz** | 1200 Hz | 1200 Hz |
| LSLMarkerTimestamps block | **Yes** (StreamName `experiment_markers`, ResolveTimeout 5, CorrectionInterval 1, interpreted) | No | No | No |
| g.HIamp sample rate (from UserData blob) | 600 (device "HA-2024.03.02") | 600 | 1200 | 1200 |
| Solver | FixedStepDiscrete 1/600 | FixedStepDiscrete 1/600 | VariableStepAuto | VariableStepAuto |
| Stop constant | **255** | 255 | **99** | 255 |
| To File | `EEG_data` → `E:\...\Photodiode_Calib_vMMR\photodiode_test_20261013_8_slx_frame_length_4_..._expstart.mat`; `LSL_timing` (Timeseries) → `..._LSLtiming.mat` | `EEG_data` → `E:\...\photodiode_test_changing_lenght_20261007_2.mat` | `EEG_data` → `C:\Users\AvivaLab\...\EEG_DDvMMR_photodiode_test_20260622.mat` | **same path** as the root vMMR model |

* **Timestamp model = experiment model:** `matlab/on_eeg_computer/HIamp_record_LSL_DD_vMMR.slx` is the only current model, and it already has the timestamp block. So step 4 is structurally done if this model is used for the experiment. There is no separate, up-to-date experiment model.
* **Frame length can't be read from the XML.** The `BufferSize` values are generic config parameters, not the g.HIamp frame length. It's set in the configuration dialog of the "g.HIamp g.Nautilus g.USBamp" block on A. It's only recorded in file names, and the last saved run used **4** (the plan says set 8).
* **To File paths are hard-coded** to the last run. They must be renamed before every run or the file is overwritten. The two June models share one output path.
* **`LSLMarkerTimestamps.m` summary:**
  * Opens a second inlet with `lsl_resolve_byprop` and pulls everything queued with `pull_chunk` on each step.
  * Outputs 1×6 per step: `[marker, edge_code, edge_ts_B, offset (time_correction), t_A (lsl_local_clock), n_pulled]`.
  * Needs **liblsl-Matlab on A's MATLAB path** (`lsl_loadlib`), and the sender must be started before the model.
  * It counts any change to a different nonzero value as an edge, not just 0→code.

## 7. Analysis notebooks

| | `photodiode_latency_test.ipynb` | `photodiode_latency_compare.ipynb` |
|---|---|---|
| Input | **one hard-coded file**: `MAT_NAME = "photodiode_test_changing_lenght_20261007_2.mat"`, searched under `data/EEG` | every `data/EEG/**` file matching `MAT_GLOB = "*slx_frame*length_*.mat"`, skipping `unknown config slx` and files ending `_LSLtiming` |
| Companion files | none | `<stem>_LSLtiming.mat` (read with h5py from `#refs#`); `data/*_photodiode_latency_latency_flashes.csv` matched on identical `lsl_push_timestamp`; then the matching `*_run_info.txt` for `script` and `lsl_resyncs` |
| Settings at the top | `MARKER_CH=-1`, `PHOTO_CH=-2`, codes 20/5/6/7, `ON_START_MS=100`, `ON_STEP_MS=1000/60`, `MAX_GAP`, `MIN_PULSE` | the same, plus `MAT_NAMES` (empty = all), `CONFIG_PATTERNS`/`FLAG_PATTERNS` (settings parsed from file names), `COMPARE_BY`, `EXP_START_CODE=1`, `RAMP_CYCLE=100`, `OUTLIER_MS=150`, `STALL_MS=100` |
| Output | printed latency/drift/jitter and plots (nothing saved) | printed side-by-side tables (latency, jitter, drift, time base, backlog, residual) and plots (nothing saved); START marker 9 is used as the time reference |

* **To add a recording to the comparison:** put the `.mat` and its `_LSLtiming.mat` anywhere under `data/EEG` (not in `unknown config slx`), name it with `slx_frame_length_N` plus the flag tags, and put the PsychoPy CSV and run_info in `data/`.
* **Before analysing new runs:**
  * Install h5py.
  * Use a kernel that exists.
  * In the test notebook, edit `MAT_NAME`.
  * Database recordings (`photodiode_db_..._slx_frame_length_8_...`) already match `MAT_GLOB`. The database's PsychoPy files (`db_..._latency_flashes.csv`) also match `PSYCHOPY_GLOB`.

## 8. Recordings on this computer

* `data/EEG/final database/` is **empty**.
* There are no `db_*` files and no `database_run_log.csv`, so the **database has not started**.
* Mapping method: each EEG file's MAT-header "Created on" time (A's clock) sits a consistent **~80 s before** a PsychoPy run stamp (B's clock) on every day. That suggests A's wall clock runs ~80 s behind B's. This is an inference, but the mapping is unambiguous.

| EEG file (date_run + tags) | Created (A) | PsychoPy run (B) | Sender | rate_hz | resyncs | LSLtiming | run_info / flashes csv | Collaborator label |
|---|---|---|---|---|---|---|---|---|
| `tst_1` (unknown config) | 10-07 12:34 | 123519 | v0, 300 flashes, exp 60 | – | – | ✗ | ✓/✓ | early test |
| `20261007_1` (unknown) | 13:42 | 134326 | v0 | – | – | ✗ | ✓/✓ | – |
| `20261007_2` (unknown) | 14:44 | 144534 | v0, **keepalive 200** | – | – | ✗ | ✓/✓ | the `_new.slx` (200 Hz) run |
| `20261007_3` fl8 | 15:05 | 150711 | v0 | 597.46 | 1 | ✗ | ✓/✓ | frame 8 |
| `20261008_1` fl4 | 13:00 | 130117 | v0 | 597.25 | 1 | ✗ | ✓/✓ | frame 4 |
| `20261008_2` fl6 | 13:04 | 130537 | v0 | 597.21 | 1 | ✗ | ✓/✓ | frame 6 |
| `20261008_3` fl8 | 13:15 | 131644 | v0 | 597.23 | 1 | ✗ | ✓/✓ | frame 8 |
| `20261008_4` fl8 TS start_0 | 13:48 | 134939 | v0 | 597.26 | 1 | ✓ | ✓/✓ | TS baseline |
| `…_4` start_1mindelay | 14:01 | 140226 | v0 | 597.92 | 1 | ✓ | ✓/✓ | 1-min delay |
| `…_4` workspacelogging_off | 14:06 | 140813 | v0 | 597.16 | 1 | ✓ | ✓/✓ | logging off |
| `…_4` multithread_off | 14:17 | 141855 | v0 | 597.17 | 1 | ✓ | ✓/✓ | multithread off |
| `…_4` trig_after_framerate | 15:00 | 150117 | **v1** | 600.003 | **0** | ✓ | ✓/✓ | v1 |
| `…_4` trig_after_allignment_screen | 15:04 | 150539 | **v2** | 599.993 | **0** | ✓ | ✓/✓ | v2 |
| `20261013_1…8`, frame 8/4 alternating, `expstart` | 11:12 → 11:40 | 111344, 111818, 112213, 112620, 113017, 113412, 113802, 114205 | **v1** + marker 1 | 599.995–599.999 | **0** (all) | ✓ | ✓/✓ | 13-Oct v1 series |

**PsychoPy runs with no EEG file here:**

* 10-07 112032, 114300, 120510, 121115, 122154: `.log` only.
* 10-07 122918, 123239, 133412, 133731: `.log` and frame intervals only (aborted).
* 10-07 140726: complete run, but no EEG file.
* 10-13 104556 and 105022: complete v1 runs without marker 1, no EEG file.
* 10-13 111741: aborted after 11.9 s.

Every EEG file has a matching PsychoPy run.

## 9. Readiness per next step

| Step | Files | What's ready | Missing / needs change | A vs B |
|---|---|---|---|---|
| 1. Repeat v1 3–5× with the timestamp model | latency v1, on_eeg model, compare nb | **Already done**: 8 runs on 10-13, all resync 0 | Nothing, unless more runs are wanted | – |
| 2. Frame length 1/2/4/8 with v1 | same | 4 and 8 done with v1 (no difference); 6 only with v0 | 1 and 2 never tested. Doc decision is **8** | A: set in the g.HIamp dialog + file name. B: run v1 |
| 3. Correction method | compare nb, docs | Decision in the 13-Oct doc: timestamp + constant (~56 ms, between-run SD 4.8) | Database not started. No EEG-pipeline function (only the incompatible draft `align_markers_to_eeg.m`) | A: model at fl8, `database` folder on E:. B: `run_photodiode_latency_database.py` |
| 4. Keep the timestamp block | on_eeg model, `LSLMarkerTimestamps.m` | Block is already in the model | Experiment ends with 99 but the model stops on 255. Rename To File every session. liblsl-Matlab must be on A's path | A |
| 5. Experiment defaults → 600 | experiment v1 `:957-958` | 59.94 already set | 1200 → 600. Same change in README examples | B |
| 6. Catch-up in `lsl_trigger.py` | `:58`, `:145-151`; test `:210` | `lsl_resyncs` logged by all v1 senders | Code + test change (not made) | B |
| 7. Final experiment test | experiment v1, on_eeg model, compare nb | Square drawn only on face-on frames (`:586-590`); per-event `onsetTime` | Square is **bottom-right**, but the correction will be measured at the **centre**. LSL timestamp is captured (`:552`) but **not written** to `*_events.csv` (`:387-390`). Compare nb only reads latency-flash CSVs, so a new analysis is needed for face events (11–44) | A: model at fl8, stop code. B: run v1 with `photodiode_square` on |
| 8. Document final config | README, AGENTS | README has v1, marker 1 and database sections | See §10 | B (repo) |

## 10. Inconsistencies and open questions

1. **End code mismatch.** Both experiment scripts send **99** at the end (`v1:1364`). The current model stops only on **255**, so a real session won't auto-stop and will run until 10000 s or a manual stop. `photodiode_test_mode` also uses 99 as its flash code (`:110`), which would stop the old root model at the first flash.
2. **AGENTS.md trigger map doesn't match the code.** It lists 1 = experiment start, 51–62 prime, 70–76, 80, 90. The experiment sends only **9** (start), 11–44 and 99. The update doc raises the same question (9 vs 1).
3. **Stale README and AGENTS.md:**
   * README "Running the experiment" still points to `run_vMMR_experiment_v0.py`, uses 1200 Hz, and says "`expected_refresh_hz` accepts only 60 or 120" (contradicted by `timing_utils.py:8`).
   * AGENTS.md doesn't mention v1, the database, the timestamp model or 600 Hz.
4. **The correction constant isn't settled.** The step list says ~53 ms; the 13-Oct doc says ~56 ms (52.4–64.5 across runs). It is to be fixed by the database.
5. **`timestamped_LSL_model/` doesn't exist.** It's now `matlab/on_eeg_computer/`, and the notebook says "until 13 Oct in timestamped_LSL_model/".
6. **Two different models share the name `HIamp_record_LSL_DD_vMMR.slx`** (root June version vs on_eeg_computer). They're easy to mix up on A.
7. **The saved model's file names still say frame length 4.** The plan requires 8 before database day 1.
8. **Possible new stall in experiment v1.** Image preloading and reading the trial CSVs happen *after* the outlet is live (`:1236-1256` vs `:1097`). If texture upload stalls the process, the stall can come back. The `lsl_resyncs` value in run_info will show it.
9. **Experiment v1 defaults to `photodiode_square: True`.** The photodiode can't be used in real sessions, so the default should probably be False outside step 7.
10. **This PC can't run the notebooks as-is** (no h5py, no `mne` kernel). The two untracked MATLAB drafts use an output layout the current model doesn't produce.
11. **Run history isn't in the run_info files.** The 10-07 early runs lack `lsl_rate_hz`/`lsl_resyncs`, and v0 run_info has no `script:` line. Mapping runs to EEG files depends on file names and the ~80 s clock offset.
