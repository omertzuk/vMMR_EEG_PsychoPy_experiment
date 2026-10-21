# check_display_refresh_rate.py
"""
Display refresh-rate check for the vMMR stimulus PC (computer B).

Verify that PsychoPy really flips at the Windows display refresh rate on this
PC, e.g. that a 120 Hz setting is not reduced to 60 Hz by the AMD driver.

The script opens a fullscreen window with the same settings as the experiment
scripts (screen 0, units "pix", black, waitBlanking=True), prints PsychoPy's
measured frame rate, then flips 1200 times with a white 200 px centre square
toggled on/off every frame and records every frame interval. It prints the
interval statistics, the share of intervals per band (<7, 7-10 (~8.33 ms =
120 Hz), 10-14, 14-19 (~16.67 ms = 60 Hz) and >19 ms) and the Windows refresh
setting (Win32_VideoController.CurrentRefreshRate), and saves the intervals to
data/display_refresh_check_<YYYYMMDD_HHMMSS>.csv.

Run with the project's .venv:
    .venv\\Scripts\\python check_display_refresh_rate.py

Read-only with respect to the system: it does not change any driver or
Windows setting.
"""

import csv
import statistics
import subprocess
from datetime import datetime
from pathlib import Path

from psychopy import core, visual

N_FLIPS = 1200
SQUARE_SIZE_PX = 200
SCREEN_WIDTH_PX = 1920
SCREEN_HEIGHT_PX = 1080

# (label, lower bound ms inclusive, upper bound ms exclusive)
BANDS = [
    ("<7 ms", 0.0, 7.0),
    ("7-10 ms (~8.33, 120 Hz)", 7.0, 10.0),
    ("10-14 ms", 10.0, 14.0),
    ("14-19 ms (~16.67, 60 Hz)", 14.0, 19.0),
    (">19 ms", 19.0, float("inf")),
]


def windows_refresh_setting():
    """Return 'Name: CurrentRefreshRate Hz' lines from Win32_VideoController."""
    command = ("Get-CimInstance Win32_VideoController | ForEach-Object "
               "{ \"$($_.Name): $($_.CurrentRefreshRate) Hz\" }")
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, text=True, timeout=30)
        return result.stdout.strip() or result.stderr.strip() or "(no output)"
    except Exception as exc:
        return f"(query failed: {exc})"


def run_flips(win, square):
    """Flip N_FLIPS times, square on every other frame; return intervals (s)."""
    win.recordFrameIntervals = True
    for i in range(N_FLIPS):
        if i % 2 == 0:
            square.draw()
        win.flip()
    win.recordFrameIntervals = False
    return list(win.frameIntervals)


def print_stats(intervals_ms):
    print(f"\nIntervals recorded: {len(intervals_ms)}")
    print(f"Median: {statistics.median(intervals_ms):.3f} ms")
    print(f"Mean:   {statistics.mean(intervals_ms):.3f} ms")
    print(f"SD:     {statistics.stdev(intervals_ms):.3f} ms")
    print("Interval bands:")
    n = len(intervals_ms)
    for label, lo, hi in BANDS:
        count = sum(lo <= iv < hi for iv in intervals_ms)
        print(f"  {label:26s} {count:5d}  ({100.0 * count / n:6.2f} %)")


def save_intervals(intervals_ms, data_dir):
    data_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = data_dir / f"display_refresh_check_{stamp}.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["frame_index", "interval_ms"])
        for i, iv in enumerate(intervals_ms):
            writer.writerow([i, f"{iv:.4f}"])
    return path


def main():
    root = Path(__file__).resolve().parent

    win = visual.Window(size=(SCREEN_WIDTH_PX, SCREEN_HEIGHT_PX),
                        fullscr=True, screen=0, units="pix", color="black",
                        allowGUI=False, waitBlanking=True)
    win.mouseVisible = False
    try:
        measured = win.getActualFrameRate(nIdentical=60, nMaxFrames=240,
                                          nWarmUpFrames=20, threshold=1)
        print(f"getActualFrameRate: {measured}")

        square = visual.Rect(win, width=SQUARE_SIZE_PX, height=SQUARE_SIZE_PX,
                             pos=(0, 0), units="pix",
                             fillColor="white", lineColor="white")
        intervals = run_flips(win, square)
    finally:
        win.close()

    intervals_ms = [iv * 1000.0 for iv in intervals]
    if len(intervals_ms) < 2:
        print("Too few frame intervals recorded.")
    else:
        print_stats(intervals_ms)

    print("\nWindows refresh setting (Win32_VideoController.CurrentRefreshRate):")
    print("  " + windows_refresh_setting().replace("\n", "\n  "))

    path = save_intervals(intervals_ms, root / "data")
    print(f"\nIntervals saved to: {path}")
    core.quit()


if __name__ == "__main__":
    main()
