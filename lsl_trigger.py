"""
lsl_trigger.py — LSL marker outlet for the vMMR EEG experiment.

Drop-in replacement for the parallel-port EEGTrigger. Creates a stream named
'experiment_markers' (int32, 10 Hz) and keeps it alive with a background
thread that pushes [0] at 10 Hz so Simulink's LSL Receive block never stalls.

Interface is identical to EEGTrigger:
    trigger = LSLTrigger(enabled=True)
    trigger.set(code)    # push a non-zero marker
    trigger.clear()      # push 0 explicitly (keepalive also does this)
    trigger.stop()       # shut down keepalive thread on exit

When enabled=False every method is a silent no-op, so the experiment runs
normally without any LSL hardware connected.
"""

import threading
from pylsl import StreamInfo, StreamOutlet

_STREAM_NAME     = 'experiment_markers'
_KEEPALIVE_HZ    = 1200
_NOMINAL_SRATE   = 1200


class LSLTrigger:

    def __init__(self, enabled=False, stream_name=_STREAM_NAME,
                 source_id='vmmr_exp'):
        self.enabled = enabled
        self.outlet  = None
        self._stop_event       = threading.Event()
        self._keepalive_thread = None

        if not self.enabled:
            return

        info = StreamInfo(
            name=stream_name,
            type='Markers',
            channel_count=1,
            nominal_srate=_NOMINAL_SRATE,
            channel_format='int32',
            source_id=source_id,
        )
        self.outlet = StreamOutlet(info)

        self._keepalive_thread = threading.Thread(
            target=self._keepalive,
            args=(self.outlet, self._stop_event),
            daemon=True,
        )
        self._keepalive_thread.start()

    # ------------------------------------------------------------------
    def _keepalive(self, outlet, stop):
        interval = 1.0 / _KEEPALIVE_HZ
        while not stop.is_set():
            outlet.push_sample([0])
            stop.wait(interval)

    def set(self, code):
        if self.outlet is not None:
            self.outlet.push_sample([int(code)])

    def clear(self):
        if self.outlet is not None:
            self.outlet.push_sample([0])

    def stop(self):
        self._stop_event.set()
        if self._keepalive_thread is not None:
            self._keepalive_thread.join(timeout=1.0)
