# Document builders

Scripts that generate the Word documents in `docs/` (need `python-docx`; not in the `.venv`).

| Script | Output | Input |
|---|---|---|
| `build_supplement.py` | `supplement_marker_timing_calibration_2026-10-15.docx` | `data/analysis/calibration_database/` (run `analysis/calibration_database_analysis.py` first) |
| `build_lab_docs.py` | `lab_guide_marker_timing_2026-10.docx`, `todo_experiment_and_analysis_2026-10.docx` | — |
| `build_report_2026-10-15.py` | `vMMR_marker_timing_calibration_2026-10-15.docx` | `vMMR_marker_timing_calibration_2026-10-13.docx` |

PDFs were exported from Word. The repository path is set at the top of each script.
