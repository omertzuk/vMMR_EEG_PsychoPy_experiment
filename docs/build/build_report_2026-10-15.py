"""Make docs/vMMR_marker_timing_calibration_2026-10-15.docx from the 13 Oct report:
new section 7 (database as run 14-15 Oct, display-setting issue, locked configuration),
caveats renumbered to 8, subtitle / next step 1 / jitter caveat updated."""
import re
from pathlib import Path
import docx
from docx.shared import Pt, Inches
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

REPO = Path(r"C:\Users\aviva-Lab\Desktop\vMMR_EEG_PsychoPy_experiment")
SRC = REPO / "docs" / "vMMR_marker_timing_calibration_2026-10-13.docx"
OUT = REPO / "docs" / "vMMR_marker_timing_calibration_2026-10-15.docx"

doc = docx.Document(str(SRC))


def add_runs(p, text, bold=False, size=None):
    for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not part:
            continue
        if part.startswith("**"):
            run = p.add_run(part[2:-2]); run.bold = True
        elif part.startswith("`"):
            run = p.add_run(part[1:-1]); run.font.name = "Consolas"; run.font.size = Pt(size or 9.5)
        else:
            run = p.add_run(part); run.bold = bold
        if size and not part.startswith("`"):
            run.font.size = Pt(size)


def set_text(p, text):
    for r in list(p.runs):
        r._r.getparent().remove(r._r)
    add_runs(p, text)


def shade(cell, hexcolor):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), hexcolor)
    tcPr.append(shd)


new = []   # body elements created at the end, moved before "7. Caveats" afterwards


def heading(text, level):
    new.append(doc.add_heading(text, level=level)._p)


def para(text, bold=False, size=None, space_after=6):
    p = doc.add_paragraph()
    add_runs(p, text, bold, size)
    p.paragraph_format.space_after = Pt(space_after)
    new.append(p._p)


def bullets(items):
    for it in items:
        p = doc.add_paragraph(style="List Bullet")
        add_runs(p, it)
        p.paragraph_format.space_after = Pt(2)
        new.append(p._p)


def table(header, rows, widths, caption, font=8.5):
    para(caption, bold=True, size=9.5, space_after=3)
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]; c.text = ""
        add_runs(c.paragraphs[0], h, bold=True, size=font); shade(c, "E8EEF7")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""; add_runs(cells[i].paragraphs[0], str(v), size=font)
    t.autofit = False
    for row in t.rows:
        for i, w in enumerate(widths):
            row.cells[i].width = Inches(w)
    new.append(t._tbl)
    para("", space_after=4)


# ------------------------------------------------------------------ section 7
heading("7. Database as run (14–15 October) and locked configuration", 1)
para("The two database days were run differently from the plan in section 6. This section records "
     "what was actually done, a display-setting issue found on 14 October, and the configuration that "
     "was locked on 15 October for the rest of the database and for the experiment.")

heading("7.1 Runs", 2)
bullets([
    "**Script:** `run_photodiode_latency_v1_trig_after_framerate_measurement.py` (not the database script). "
    "Square and optical sensor at the screen centre (commit `0cc537d`); the `on_cycle` field for long runs "
    "was added in `34fc744`. With `on_cycle = 0` the two versions present identical stimuli.",
    "**Run types:** short runs (100 flashes, `on_cycle = 0`) and long runs (400 flashes, `on_cycle = 100`, "
    "so the duration ramp repeats every 100 flashes and pulses stay pairable).",
    "**14 October (day 1):** 6 short runs, `sqcenter_run01`–`run06` (13:59–14:44), and 1 long run, "
    "`sqcenter_long01` (two complete attempts on computer B, 14:51 and 15:02; the one with the EEG file is "
    "the valid run). EEG files on computer A: `main_20261014_fl_8_sqcenter_run01.mat` … `run06.mat` and "
    "`main_20261014_fl_8_sqcenter_run_long_01.mat`, each with a matching `_LSLtiming.mat`. All PsychoPy "
    "run_info files show `lsl_resyncs: 0` and ~600.0 samples/s.",
    "**15 October (day 2):** further short and long runs, numbered again from 01 (the date in the file name "
    "distinguishes the days), session `002`, same script and dialog values.",
    "**Total:** both days are pooled into one database (decision of 15 October). This is fewer than the "
    "~50 sessions planned. With a between-run SD of about 4.8 ms, 14 runs give an expected 95 % CI of the "
    "correction of about ±2.8 ms (instead of ±1.3 ms) and a 95 % prediction interval for a new session of "
    "about ±11 ms; each additional run narrows the CI.",
    "**Traceability:** the v1 script does not write the git commit or file hashes to run_info (the database "
    "script would have). The code state is identified by commit `34fc744` (script unchanged since "
    "14 October 15:26) and by the `script:` and parameter lines in each run_info.",
])

heading("7.2 Display-setting issue", 2)
para("On 14 October at 12:06 a new check (`check_display_refresh_rate.py`, 1200 flips) found Windows set to "
     "**120 Hz** on computer B, although the 13 October configuration specified the 60 Hz mode. PsychoPy "
     "still flipped at 59.94 Hz (all 1199 intervals 16.68 ms, SD 0.08 ms), because the AMD Vega 8 driver "
     "presents every second refresh. A further check was made at 12:16. The Windows setting in force during "
     "the day-1 runs (13:59–15:02) is not stored in any run file; the operators confirmed on 15 October that "
     "Windows had been set back to the 59.94 Hz mode before those runs, the same mode as on day 2.")
para("Why it matters: the flip rate and all frame counts are the same in both modes, but at 120 Hz the "
     "panel scans each image out in 8.3 ms instead of 16.7 ms, so the time from flip to light at the screen "
     "centre can differ by a few milliseconds. Each setting therefore has its own correction constant.")
para("Decision (15 October): pool day 1 and day 2, both recorded in the 59.94 Hz mode. On 15 October at "
     "12:22 Windows reported the 59 Hz (59.94 Hz) mode, and PsychoPy measured 59.942 Hz (1199/1199 intervals "
     "14–19 ms, mean 16.683 ms, SD 0.087 ms). Because the day-1 setting rests on the operators' account, the "
     "day-1 and day-2 offsets are still compared at analysis and the result is reported.")

heading("7.3 Locked configuration (15 October 2026)", 2)
para("This configuration applies to the remaining database runs, the experiment validation sessions and the "
     "real experiment. Any change to an item below requires new calibration runs.")
table(["Item", "Locked setting"], [
    ["Display (B)", "DELL P2426H (EDID DEL43D4), 1920×1080, Windows refresh **59.94 Hz** (Windows API "
     "reports 59 Hz; not 60 or 120). PsychoPy flips at 59.94 Hz (16.68 ms). Check with "
     "`check_display_refresh_rate.py` before each session"],
    ["GPU / OS (B)", "AMD Radeon Vega 8, driver 31.0.21916.2; Windows 11 Education 10.0.26200; "
     "power plan AMD Ryzen Balanced"],
    ["Software (B)", "Python 3.10.22 (.venv), PsychoPy 2026.2.4, pylsl 1.18.5 (liblsl 1.18); "
     "`lsl_api.cfg` KnownPeers 192.168.50.1 (computer A)"],
    ["Code", "branch `photodiode-latency-calibration`, commit `34fc744`"],
    ["Calibration script (B)", "`run_photodiode_latency_v1_trig_after_framerate_measurement.py`: expected "
     "refresh 59.94 Hz, LSL keepalive and nominal rate 600, 45 px white square at the screen centre, text at "
     "y = 320, `on_start_ms` 100, `on_step_ms` 16.7, `rng_seed` 20261006; short = 100 flashes, "
     "`on_cycle` 0; long = 400 flashes, `on_cycle` 100"],
    ["Markers", "9 start, 1 experiment start (after alignment), 5/6/5 calibration, 7 flash block, "
     "20 flash, 255 end (stops the model)"],
    ["Optical sensor", "GTEC-0270 taped over the screen centre; g.TRIGbox → g.HIamp digital input"],
    ["Model (A)", "`matlab/on_eeg_computer/HIamp_record_LSL_DD_vMMR.slx` + `LSLMarkerTimestamps.m` "
     "(R2020a, liblsl-Matlab on the path); g.HIamp 600 Hz, **frame length 8**; fixed-step discrete 1/600, "
     "single-tasking, pacing off, multithreaded co-sim on (model on, g.HIamp block auto), workspace logging "
     "on, LSL Receive 600 Hz, stop constant 255"],
    ["File names (A)", "short: `main_<YYYYMMDD>_fl_8_sqcenter_run<NN>.mat`; long: "
     "`main_<YYYYMMDD>_fl_8_sqcenter_run_long_<NN>.mat`; each plus the same name ending `_LSLtiming.mat` "
     "(fl = Simulink frame length; NN restarts at 01 each day)"],
    ["Run check", "`lsl_resyncs: 0` in the newest `data/*_run_info.txt` after every run"],
], widths=[1.6, 5.0], caption="Table 12. Locked configuration (15 October 2026)")

heading("7.4 Result: the correction", 2)
para("The database was recorded as planned above: 22 sessions (14 Oct: 6 short + 1 long; 15 Oct: 12 short + 2 long "
     "+ 1 full experiment length of 1200 flashes), 4,200 flashes, no session excluded. Full methods and results: "
     "`docs/supplement_marker_timing_calibration_2026-10-15.docx`.")
bullets([
    "**Correction: 62.4 ms** (95 % CI 61.7–63.0) from the timestamp-placed marker to the light at the screen "
    "centre; between-session SD 1.4 ms; a new session is expected within 59.4–65.3 ms.",
    "**Clock mapping changed during the analysis.** The planned single median of t_A − model time per session gave "
    "53.2 ms with SD 4.7 ms and two clusters of sessions, because the model processes the amplifier's 8-sample "
    "frames either in bursts or steadily one frame behind. The local 90th percentile within ±10 s of each event "
    "removes this and also follows the ~4 ppm amplifier-vs-PC clock drift (11 ms over 29 min with the median). "
    "The pilot value of ~56 ms in this report used the old mapping and is superseded.",
    "**Per event:** SD 5.7 ms, 97.7 % within ±10 ms, all within one display frame (leave-one-session-out).",
    "**Replication:** the 8 sessions of 13 October (corner sensor) gave SD 0.9 ms with the new mapping; the corner "
    "is 2.0 ms later than the centre.",
    "**Implementation:** `analysis/marker_timing.py` (`correct_events`), shared with the calibration analysis "
    "`analysis/calibration_database_analysis.py`. Data: `data/EEG/final database/` (EEG_Computer_A, Computer_B, "
    "run_manifest.csv).",
])

# ------------------------------------------------------------------ move section 7 before the caveats
paras = doc.paragraphs
cav = next(p for p in paras if p.style.name == "Heading 1" and p.text.strip() == "7. Caveats")
for el in new:
    cav._p.addprevious(el)
cav.runs[0].text = "8. Caveats"
for r in cav.runs[1:]:
    r.text = ""

# ------------------------------------------------------------------ small text updates
paras = doc.paragraphs
sub = paras[1]
set_text(sub, sub.text.replace("6–13 October 2026", "6–15 October 2026"))

step1 = next(p for p in paras if p.style.name == "List Number" and p.text.startswith("Build the calibration database"))
set_text(step1, "Done – calibration database: 22 centre sessions on 14–15 October (18 short, 3 long, 1 full "
                "experiment length), pooled (section 7). The configuration was locked on 15 October (Table 12), "
                "including Windows at 59.94 Hz on computer B; check it before every session.")
status = {
    "Analyse the database": "Done – correction 62.4 ms (95 % CI 61.7–63.0), between-session SD 1.4 ms, with the local "
                            "upper-envelope clock mapping (section 7.4).",
    "Write the correction as a function": "Done – analysis/marker_timing.py (correct_events); checked on all 22 "
                                          "sessions (mean error −0.2 ms, SD 5.7 ms) and with synthetic tests.",
    "Update the experiment script": "Open – see docs/todo_experiment_and_analysis_2026-10.docx (part 1).",
    "Final test with the experiment script": "Open – after the experiment-script update "
                                             "(docs/todo_experiment_and_analysis_2026-10.docx).",
    "Ask Claude to write the final methods supplement": "Done – docs/supplement_marker_timing_calibration_2026-10-15.docx "
                                                        "([TBD] fields: computer-A versions, commit, data location).",
    "Document the final configuration": "Done – README.md and AGENTS.md; lab guide "
                                        "docs/lab_guide_marker_timing_2026-10.docx. Re-check runs after any change remain "
                                        "the rule.",
}
for p in paras:
    if p.style.name == "List Number":
        for start, text in status.items():
            if p.text.startswith(start):
                set_text(p, text)

jit = next(p for p in paras if p.style.name == "List Bullet" and p.text.startswith("The display-side cause"))
set_text(jit, "The display-side cause of the ~5.5 ms within-run jitter is a hypothesis; the jitter was accepted "
              "on 13 October and not investigated further.")

new_cav = [
    "The Windows refresh setting is not written to run_info. Windows was found at 120 Hz at 12:06 on 14 October; "
    "the operators confirmed it was back at 59.94 Hz for the day-1 runs, as on day 2. Day 1 and day 2 are "
    "still compared at analysis (section 7.2).",
    "The database has far fewer runs (2 days) than the ~50 planned, so the correction is less precise "
    "(expected 95 % CI about ±2.8 ms with 14 runs).",
]
anchor = jit
for text in new_cav:
    p = doc.add_paragraph(style="List Bullet")
    add_runs(p, text)
    p.paragraph_format.space_after = Pt(2)
    anchor._p.addnext(p._p)
    anchor = p

doc.save(str(OUT))
print("saved", OUT)
