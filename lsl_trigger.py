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
    once (at any model rate >= ~60 Hz the 0.100 s default spans many samples);
  - SHORTER than the minimum gap between successive events (the 600 ms face
    SOA here), so two events — even with identical codes — are separated by a
    return to 0 and each gets its own edge.

Do NOT call clear() one frame after set() anymore: that recreates the
transient. Let hold_duration handle the return to 0.
"""

import threading
from pylsl import StreamInfo, StreamOutlet, local_clock

_STREAM_NAME   = 'experiment_markers'
_KEEPALIVE_HZ  = 1200
_NOMINAL_SRATE = 1200
_HOLD_DURATION = 0.100   # 0 < consumer_period << hold << min_event_gap


class LSLTrigger:

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

        if not self.enabled:
            return
        self.keepalive_hz  = float(keepalive_hz)
        self.nominal_srate = float(nominal_srate)
        if self.keepalive_hz <= 0:
            raise ValueError("keepalive_hz must be positive.")
        if self.nominal_srate <= 0:
            raise ValueError("nominal_srate must be positive.")
        if self.hold_duration <= 0:
            raise ValueError("hold_duration must be positive.")

        info = StreamInfo(name=stream_name, type='Markers', channel_count=1,
                          nominal_srate=self.nominal_srate,
                          channel_format='int32', source_id=source_id)
        self.outlet = StreamOutlet(info)
        self._start_keepalive()

    # ------------------------------------------------------------------
    def _start_keepalive(self):
        self._stop_event.clear()
        self._keepalive_thread = threading.Thread(target=self._keepalive,
                                                   daemon=True)
        self._keepalive_thread.start()

    def _keepalive(self):
        interval = 1.0 / self.keepalive_hz
        while not self._stop_event.is_set():
            with self._lock:
                if self._expiry is not None and local_clock() >= self._expiry:
                    self._current_value = 0
                    self._expiry = None
                self.outlet.push_sample([self._current_value], pushthrough=True)
            self._stop_event.wait(interval)

    def set_with_timestamp(self, code):
        if self.outlet is None:
            return None
        ts = local_clock()
        with self._lock:
            self._current_value = int(code)
            self._expiry = ts + self.hold_duration
            self.outlet.push_sample([int(code)], pushthrough=True)
        return ts

    def set(self, code):
        self.set_with_timestamp(code)

    def clear(self):
        if self.outlet is None:
            return
        with self._lock:
            self._current_value = 0
            self._expiry = None
            self.outlet.push_sample([0], pushthrough=True)

    def stop(self):
        self._stop_event.set()
        if self._keepalive_thread is not None:
            self._keepalive_thread.join(timeout=1.0)
        self._keepalive_thread = None