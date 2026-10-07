"""
lsl_trigger.py — latched LSL marker outlet for the vMMR EEG experiment.

The Simulink "LSL MARKERS FROM EXPERIMENT" inlet outputs one sample per model
step (no chunk mode) and is muxed sample-for-sample with the g.HIamp data into
the .mat. A 1-frame marker pulse can fall between two of the inlet's sample
instants and never be written — the cause of the randomly missing markers.
Instead of a transient, this class LATCHES the code: the value is held (and
re-pushed by the keepalive thread) until it auto-expires after hold_duration,
so a sample-and-hold consumer always sees it. Every push goes through one lock,
so the keepalive and marker threads can never collide on the outlet.

Event onset = the 0 -> code rising edge, at the set() call (the stimulus flip).
Detect events offline as LEADING EDGES, not by counting nonzero samples.

CONSTRAINT on hold_duration:
  - LONGER than one consumer sample period, so the code is sampled at least
    once (at the 600 Hz model rate the 0.100 s default spans ~60 samples);
  - SHORTER than the minimum gap between successive events (the 600 ms face
    SOA here), so two events — even with identical codes — are separated by a
    return to 0 and each gets its own edge.

Do NOT call clear() one frame after set() anymore: that recreates the
transient. Let hold_duration handle the return to 0.

SAMPLE RATE PACES THE SIMULINK MODEL:
  The inlet waits for one marker sample on every model step, so the number of
  samples this outlet sends per second sets the pace of the whole Simulink
  model. Too few samples -> the model runs slower than real time (marker
  durations look compressed, amplifier data lags and is dropped); too many ->
  samples queue up and the recorded markers are delayed.

  A plain "push, then sleep 1/keepalive_hz" loop under-delivers on Windows,
  where sleeps last longer than requested (about 500 samples/s when 600 are
  requested). The keepalive therefore counts samples against the clock: on
  every wake-up it pushes as many samples as are due since _t0, so it catches
  up after a long sleep and delivers exactly keepalive_hz samples/s on
  average. Every push (keepalive, set, clear) is counted. set() and clear()
  first send the samples still owed with the OLD value, so the new code lands
  at the stream position matching its real time, and each catch-up sample is
  given the value that was valid at its own scheduled time (latch expiry is
  resolved per sample, not per wake-up). After a stall longer than
  _MAX_CATCHUP_S the counter is reset instead of sending a large burst;
  stats()["resyncs"] counts these resets.
"""

import threading
from importlib import import_module

_STREAM_NAME   = 'experiment_markers'
# Both rates match the Simulink model / LSL Receive block (600 Hz). The
# keepalive must not push faster than the inlet consumes (one sample per
# model step), or samples may queue up and delay the recorded markers.
_KEEPALIVE_HZ  = 600.0
_NOMINAL_SRATE = 600.0
_END_CODE      = 255     # the Simulink model stops recording on this code
_HOLD_DURATION = 0.100   # 0 < consumer_period << hold << min_event_gap
_MAX_CATCHUP_S = 0.100   # longer gaps are resynced, not sent as a burst


class LSLTrigger:

    # LSL is a latched state channel. Its keepalive thread returns the marker to
    # zero after hold_duration, so display code must not clear it on frame 2.
    requires_manual_clear = False

    def __init__(self, enabled=False, stream_name=_STREAM_NAME,
                 source_id='vmmr_exp', keepalive_hz=_KEEPALIVE_HZ,
                 nominal_srate=_NOMINAL_SRATE, hold_duration=_HOLD_DURATION):
        self.enabled = enabled
        self.outlet  = None
        self.keepalive_hz  = keepalive_hz
        self.nominal_srate = nominal_srate
        self.hold_duration = float(hold_duration)
        self._lock = threading.Lock()
        self._current_value = 0
        self._expiry = None
        self._stop_event = threading.Event()
        self._keepalive_thread = None
        self._lifecycle_lock = threading.Lock()
        self._finished = False
        self._stopped = False
        # Sample counting (all guarded by _lock). _pushed counts samples since
        # _t0; _total_pushed counts samples since _start_time.
        self._t0 = None
        self._pushed = 0
        self._total_pushed = 0
        self._start_time = None
        self._resyncs = 0

        if not self.enabled:
            return

        # pylsl is optional when LSL output is disabled. Import it lazily so
        # importing this module does not fail in installations without pylsl.
        try:
            pylsl = import_module('pylsl')
            stream_info = pylsl.StreamInfo
            stream_outlet = pylsl.StreamOutlet
            self._local_clock = pylsl.local_clock
        except (ImportError, AttributeError) as exc:
            raise RuntimeError(
                "LSL output requires the optional 'pylsl' package."
            ) from exc

        self.keepalive_hz  = float(keepalive_hz)
        self.nominal_srate = float(nominal_srate)
        if self.keepalive_hz <= 0:
            raise ValueError("keepalive_hz must be positive.")
        if self.nominal_srate <= 0:
            raise ValueError("nominal_srate must be positive.")
        if self.hold_duration <= 0:
            raise ValueError("hold_duration must be positive.")

        info = stream_info(name=stream_name, type='Markers', channel_count=1,
                   nominal_srate=self.nominal_srate,
                   channel_format='int32', source_id=source_id)
        self.outlet = stream_outlet(info)
        self._start_keepalive()

    # ------------------------------------------------------------------
    def _start_keepalive(self):
        self._stop_event.clear()
        self._keepalive_thread = threading.Thread(target=self._keepalive,
                                                   daemon=True)
        self._keepalive_thread.start()

    def _start_counting(self, now):
        """Start the sample clock. Call with _lock held."""
        self._t0 = self._start_time = now
        self._pushed = 0
        self._total_pushed = 0
        self._resyncs = 0

    def _push_due(self, now, include_now=True):
        """Push every sample due by `now` (exclusive of the `now` slot when
        include_now is False). Each sample carries the value valid at its own
        scheduled time, so the latch expires at the right stream position even
        when a wake-up is late. Call with _lock held."""
        if self._t0 is None:
            self._start_counting(now)
        due = int((now - self._t0) * self.keepalive_hz) + 1 - self._pushed
        if not include_now:
            due -= 1
        max_due = max(1, int(_MAX_CATCHUP_S * self.keepalive_hz))
        if due > max_due:
            # Stalled too long: restart the count instead of sending a burst.
            self._t0 = now
            self._pushed = 0
            due = 1 if include_now else 0
            self._resyncs += 1
        for _ in range(max(0, due)):
            slot_time = self._t0 + self._pushed / self.keepalive_hz
            if self._expiry is not None and slot_time >= self._expiry:
                self._current_value = 0
                self._expiry = None
            self.outlet.push_sample([self._current_value], pushthrough=True)
            self._pushed += 1
            self._total_pushed += 1
        if self._expiry is not None and now >= self._expiry:
            self._current_value = 0
            self._expiry = None

    def _keepalive(self):
        interval = 1.0 / self.keepalive_hz
        outlet = self.outlet
        if outlet is None:
            return
        with self._lock:
            if self._t0 is None:
                self._start_counting(self._local_clock())
        while not self._stop_event.is_set():
            with self._lock:
                self._push_due(self._local_clock())
            self._stop_event.wait(interval)

    def set_with_timestamp(self, code):
        if self.outlet is None:
            return None
        value = int(code)
        with self._lock:
            timestamp = self._local_clock()
            # Send the samples still owed with the old value first, so the
            # code sample sits at the stream position of `timestamp`.
            self._push_due(timestamp, include_now=False)
            self._current_value = value
            self._expiry = timestamp + self.hold_duration
            self.outlet.push_sample(
                [value], timestamp=timestamp, pushthrough=True
            )
            self._pushed += 1
            self._total_pushed += 1
        return timestamp

    def set(self, code):
        self.set_with_timestamp(code)

    def clear(self):
        if self.outlet is None:
            return
        with self._lock:
            self._push_due(self._local_clock(), include_now=False)
            self._current_value = 0
            self._expiry = None
            self.outlet.push_sample([0], pushthrough=True)
            self._pushed += 1
            self._total_pushed += 1

    def stats(self):
        """Samples sent since the keepalive started and the average rate.
        All values are None when the outlet is disabled."""
        if self.outlet is None or self._start_time is None:
            return {"samples_sent": None, "seconds": None,
                    "rate_hz": None, "resyncs": None}
        with self._lock:
            total = self._total_pushed
            elapsed = self._local_clock() - self._start_time
            resyncs = self._resyncs
        return {"samples_sent": total, "seconds": elapsed,
                "rate_hz": total / elapsed if elapsed > 0 else None,
                "resyncs": resyncs}

    def wait_for_consumers(self, timeout=15.0):
        """Wait for an inlet when supported; return None on older pylsl."""
        if self.outlet is None:
            return False
        wait = getattr(self.outlet, "wait_for_consumers", None)
        if wait is None:
            return None
        return bool(wait(float(timeout)))

    def finish(self, final_code=_END_CODE, margin=0.050):
        """Latch a final marker, return to zero, and stop exactly once."""
        margin = float(margin)
        if margin < 0:
            raise ValueError("margin must not be negative.")

        with self._lifecycle_lock:
            if self._finished or self._stopped:
                return
            self._finished = True

        if self.outlet is None:
            self.stop()
            return

        try:
            self.set(final_code)
            # Keep the outlet and keepalive thread alive for the full latch.
            self._stop_event.wait(self.hold_duration + margin)
            self.clear()
        finally:
            self.stop()

    def stop(self):
        """Stop and join the keepalive thread; safe to call repeatedly."""
        with self._lifecycle_lock:
            if self._stopped:
                return
            self._stopped = True
            self._stop_event.set()
            thread = self._keepalive_thread

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
            if thread.is_alive():
                raise RuntimeError("LSL keepalive thread did not stop cleanly.")

        with self._lifecycle_lock:
            self._keepalive_thread = None