"""
lsl_trigger.py — LSL marker outlet for the vMMR EEG experiment.

Drop-in replacement for the parallel-port EEGTrigger. Creates a stream named
'experiment_markers' (int32) and keeps it alive with a background thread that
pushes [0] at the configured keepalive rate so Simulink's LSL Receive block
never stalls.

Interface is identical to EEGTrigger:
    trigger = LSLTrigger(enabled=True)
    trigger.set(code)    # push a non-zero marker
    trigger.clear()      # push 0 explicitly (keepalive also does this)
    trigger.stop()       # shut down keepalive thread on exit

Timing diagnostics can call:
    trigger.set_with_timestamp(code)  # push marker and return local LSL time

When enabled=False every method is a silent no-op, so the experiment runs
normally without any LSL hardware connected.
"""

import threading
from pylsl import StreamInfo, StreamOutlet, local_clock

_STREAM_NAME     = 'experiment_markers'
_KEEPALIVE_HZ    = 1200
_NOMINAL_SRATE   = 1200


class LSLTrigger:

    def __init__(self, enabled=False, stream_name=_STREAM_NAME,
                 source_id='vmmr_exp', keepalive_hz=_KEEPALIVE_HZ,
                 nominal_srate=_NOMINAL_SRATE):
        self.enabled = enabled
        self.outlet  = None
        self.keepalive_hz = keepalive_hz
        self.nominal_srate = nominal_srate
        self._stop_event       = threading.Event()
        self._keepalive_thread = None

        if not self.enabled:
            return
        self.keepalive_hz = float(keepalive_hz)
        self.nominal_srate = float(nominal_srate)
        if self.keepalive_hz <= 0:
            raise ValueError("keepalive_hz must be positive.")
        if self.nominal_srate <= 0:
            raise ValueError("nominal_srate must be positive.")

        info = StreamInfo(
            name=stream_name,
            type='Markers',
            channel_count=1,
            nominal_srate=self.nominal_srate,
            channel_format='int32',
            source_id=source_id,
        )
        self.outlet = StreamOutlet(info)

        self._keepalive_thread = threading.Thread(
            target=self._keepalive,
            args=(self.outlet, self._stop_event, self.keepalive_hz),
            daemon=True,
        )
        self._keepalive_thread.start()

    # ------------------------------------------------------------------
    def _keepalive(self, outlet, stop, keepalive_hz):
        interval = 1.0 / keepalive_hz
        while not stop.is_set():
            outlet.push_sample([0])
            stop.wait(interval)

    def set_with_timestamp(self, code):
        if self.outlet is not None:
            ts = local_clock()
            self.outlet.push_sample([int(code)], timestamp=ts,
                                    pushthrough=True)
            return ts
        return None

    def set(self, code):
        self.set_with_timestamp(code)

    def clear(self):
        if self.outlet is not None:
            self.outlet.push_sample([0], pushthrough=True)

    def stop(self):
        self._stop_event.set()
        if self._keepalive_thread is not None:
            self._keepalive_thread.join(timeout=1.0)
