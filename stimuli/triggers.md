# EEG Trigger Codes — vMMR Experiment

## Hardware / software setup

Triggers are sent from **Computer B** (PsychoPy, this script) to **Computer A**
(Simulink + EEG recorder) over a LAN cable using **Lab Streaming Layer (LSL)**.

- Computer B creates an LSL outlet (`StreamInfo`) named **`experiment_markers`**,
  type `Markers`, channel format `int32`.
- A background thread on Computer B pushes `[0]` at **10 Hz** continuously
  ("keepalive") so Simulink's LSL Receive block never stalls waiting for data.
- Actual triggers are sent with `outlet.push_sample([code])`. Because every other
  sample in the stream is `0`, a single push of a non-zero code produces a clean
  pulse as seen by Simulink.
- There is no parallel port involved. The existing `EEGTrigger` class (parallel
  port wrapper) will be replaced by an `LSLTrigger` class with the same
  `.set(code)` / `.clear()` interface so the rest of the experiment code does not
  change.

---


## Reserved codes

| Code | Event | Notes |
|------|-------|-------|
| 0 | Keepalive / idle | Pushed continuously by background thread at 10 Hz; never used as an experiment marker |
| 1 | Experiment start | Sent once, immediately after the participant confirms the startup dialog |
| 99 | Experiment end | Sent once in the `finally` block, always fires even on crash/abort |

---

## Face onset triggers

Sent on the first frame each face appears (~16 ms pulse: set on frame 0, clear on
frame 1 — identical timing to the existing parallel-port logic). Encodes the full
experimental condition so the EEG can be epoched by prime type, identity, and face
role independently.

**Encoding**

| Tens digit | Prime type | Identity |
|-----------|------------|----------|
| 1x | DEATH | SELF |
| 2x | DEATH | OTHER |
| 3x | NEGATIVE | SELF |
| 4x | NEGATIVE | OTHER |

| Units digit | Face role |
|------------|-----------|
| x1 | Standard |
| x2 | Deviant |
| x3 | Target appearing at a standard slot |
| x4 | Target appearing at the deviant slot |

| Code | Prime | Identity | Face role |
|------|-------|----------|-----------|
| 11 | DEATH | SELF | Standard |
| 12 | DEATH | SELF | Deviant |
| 13 | DEATH | SELF | Target at standard slot |
| 14 | DEATH | SELF | Target at deviant slot |
| 21 | DEATH | OTHER | Standard |
| 22 | DEATH | OTHER | Deviant |
| 23 | DEATH | OTHER | Target at standard slot |
| 24 | DEATH | OTHER | Target at deviant slot |
| 31 | NEGATIVE | SELF | Standard |
| 32 | NEGATIVE | SELF | Deviant |
| 33 | NEGATIVE | SELF | Target at standard slot |
| 34 | NEGATIVE | SELF | Target at deviant slot |
| 41 | NEGATIVE | OTHER | Standard |
| 42 | NEGATIVE | OTHER | Deviant |
| 43 | NEGATIVE | OTHER | Target at standard slot |
| 44 | NEGATIVE | OTHER | Target at deviant slot |

---

## Prime word onset triggers

Sent on the first frame the Hebrew prime word appears (600 ms before the first
face). Encodes prime type and identity so the EEG can be epoched around word
onset to study priming separately from face processing.

| Code | Prime | Identity |
|------|-------|----------|
| 51 | DEATH | SELF |
| 52 | DEATH | OTHER |
| 61 | NEGATIVE | SELF |
| 62 | NEGATIVE | OTHER |

---

## Trial fixation onset

Sent at the start of every trial when the fixation cross first appears (before
the prime word). Duration is jittered 500–700 ms. Allows pre-prime baseline
computation and trial-level artifact rejection.

| Code | Event |
|------|-------|
| 80 | Trial fixation cross onset |

---

## Structural / phase markers

Sent once at phase transitions. Useful for coarse segmentation and for excluding
transition periods from EEG analysis.

| Code | Event |
|------|-------|
| 70 | Practice phase start — first practice trial about to begin |
| 71 | Practice phase end — practice complete screen shown |
| 72 | Main experiment start — first main trial about to begin |
| 73 | Block start — first trial of each main block about to begin |
| 74 | Block end — last trial of each main block just completed |
| 75 | Rest period start — eyes-closed rest screen shown |
| 76 | Rest period end — participant dismissed the rest screen |

---

## Participant response

| Code | Event |
|------|-------|
| 90 | SPACE key press (target detection response) |

---

## Summary

| Range | Category |
|-------|----------|
| 0 | Keepalive (idle, background thread) |
| 1, 99 | Experiment start / end |
| 11–44 | Face onsets — 2 × 2 conditions × 4 roles |
| 51–62 | Prime word onsets — 2 × 2 conditions |
| 70–76 | Structural phase markers |
| 80 | Trial fixation onset |
| 90 | Participant button press |
