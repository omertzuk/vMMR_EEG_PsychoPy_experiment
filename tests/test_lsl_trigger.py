import importlib
import sys
import threading
import time
import types

import pytest


class FakeStreamInfo:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeStreamOutlet:
    instances = []

    def __init__(self, info):
        self.info = info
        self.samples = []
        self._samples_lock = threading.Lock()
        self.consumer_connected = True
        self.__class__.instances.append(self)

    def push_sample(self, sample, timestamp=None, pushthrough=False):
        with self._samples_lock:
            self.samples.append({
                "value": int(sample[0]),
                "timestamp": timestamp,
                "pushthrough": pushthrough,
                "wall_time": time.monotonic(),
            })

    def wait_for_consumers(self, timeout):
        return self.consumer_connected

    def snapshot(self):
        with self._samples_lock:
            return list(self.samples)


@pytest.fixture
def lsl_module(monkeypatch):
    FakeStreamOutlet.instances.clear()
    fake_pylsl = types.ModuleType("pylsl")
    fake_pylsl.StreamInfo = FakeStreamInfo
    fake_pylsl.StreamOutlet = FakeStreamOutlet
    fake_pylsl.local_clock = time.monotonic
    monkeypatch.setitem(sys.modules, "pylsl", fake_pylsl)
    sys.modules.pop("lsl_trigger", None)
    module = importlib.import_module("lsl_trigger")
    yield module
    sys.modules.pop("lsl_trigger", None)


def wait_until(predicate, timeout=0.25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.001)
    return predicate()


def test_lsl_event_sample_uses_the_returned_explicit_timestamp(lsl_module):
    trigger = lsl_module.LSLTrigger(
        enabled=True, keepalive_hz=200, nominal_srate=1200,
        hold_duration=0.040,
    )
    try:
        returned_timestamp = trigger.set_with_timestamp(42)
        explicit_events = [
            sample for sample in trigger.outlet.snapshot()
            if sample["value"] == 42 and sample["timestamp"] is not None
        ]
        assert len(explicit_events) == 1
        assert explicit_events[0]["timestamp"] == returned_timestamp
        assert explicit_events[0]["pushthrough"] is True
        assert trigger.outlet.info.kwargs["channel_format"] == "int32"
    finally:
        trigger.stop()


def test_lsl_latch_auto_expires_and_repeated_code_gets_new_edge(lsl_module):
    hold_duration = 0.040
    trigger = lsl_module.LSLTrigger(
        enabled=True, keepalive_hz=400, nominal_srate=1200,
        hold_duration=hold_duration,
    )
    assert trigger.requires_manual_clear is False
    try:
        first_timestamp = trigger.set_with_timestamp(17)
        samples = trigger.outlet.snapshot()
        first_event_index = next(
            index for index, sample in enumerate(samples)
            if sample["value"] == 17 and sample["timestamp"] is not None
        )

        time.sleep(hold_duration / 2)
        after_first_event = trigger.outlet.snapshot()[first_event_index + 1:]
        assert all(sample["value"] == 17 for sample in after_first_event)

        assert wait_until(
            lambda: any(
                sample["value"] == 0
                for sample in trigger.outlet.snapshot()[first_event_index + 1:]
            )
        )
        second_timestamp = trigger.set_with_timestamp(17)
        assert second_timestamp > first_timestamp

        values = [sample["value"] for sample in trigger.outlet.snapshot()]
        assert values[first_event_index] == 17
        assert 0 in values[first_event_index + 1:]
        last_zero = max(index for index, value in enumerate(values) if value == 0)
        assert 17 in values[last_zero + 1:]
    finally:
        trigger.stop()


def test_finish_holds_final_marker_then_clears_and_is_idempotent(lsl_module):
    hold_duration = 0.040
    margin = 0.015
    trigger = lsl_module.LSLTrigger(
        enabled=True, keepalive_hz=400, nominal_srate=1200,
        hold_duration=hold_duration,
    )

    start = time.monotonic()
    trigger.finish(final_code=99, margin=margin)
    elapsed = time.monotonic() - start

    samples = trigger.outlet.snapshot()
    final_index = next(
        index for index, sample in enumerate(samples)
        if sample["value"] == 99 and sample["timestamp"] is not None
    )
    first_zero_after = next(
        sample for sample in samples[final_index + 1:]
        if sample["value"] == 0
    )
    final_sample = samples[final_index]

    assert first_zero_after["wall_time"] - final_sample["wall_time"] >= 0.035
    assert elapsed >= hold_duration + margin - 0.010
    assert samples[-1]["value"] == 0
    assert trigger._keepalive_thread is None

    trigger.finish(final_code=99, margin=margin)
    trigger.stop()
    trigger.stop()


# --- exact-rate keepalive -----------------------------------------------------

def patch_min_wait(monkeypatch, min_wait):
    """Make every Event.wait(timeout) last at least min_wait (like Windows)."""
    original_wait = threading.Event.wait

    def slow_wait(self, timeout=None):
        if timeout is not None:
            timeout = max(float(timeout), min_wait)
        return original_wait(self, timeout)

    monkeypatch.setattr(threading.Event, "wait", slow_wait)


@pytest.mark.parametrize("min_wait", [0.002, 0.015])
def test_keepalive_delivers_exact_rate_with_slow_sleeps(
        lsl_module, monkeypatch, min_wait):
    patch_min_wait(monkeypatch, min_wait)
    trigger = lsl_module.LSLTrigger(enabled=True, keepalive_hz=600,
                                    nominal_srate=600, hold_duration=0.100)
    try:
        for _ in range(20):                 # ~20 set() calls during ~3 s
            time.sleep(0.150)
            trigger.set(20)
        stats = trigger.stats()
    finally:
        trigger.stop()

    assert stats["seconds"] >= 2.9
    assert stats["rate_hz"] == pytest.approx(600.0, rel=0.01)
    assert stats["samples_sent"] == len(trigger.outlet.snapshot())


@pytest.mark.parametrize("min_wait", [None, 0.015])
def test_set_plateau_matches_hold_duration_in_samples(
        lsl_module, monkeypatch, min_wait):
    if min_wait is not None:
        patch_min_wait(monkeypatch, min_wait)
    trigger = lsl_module.LSLTrigger(enabled=True, keepalive_hz=600,
                                    nominal_srate=600, hold_duration=0.100)
    try:
        time.sleep(0.050)
        trigger.set(42)
        time.sleep(0.250)
    finally:
        trigger.stop()

    values = [s["value"] for s in trigger.outlet.snapshot()]
    onset = values.index(42)
    plateau = 0
    while onset + plateau < len(values) and values[onset + plateau] == 42:
        plateau += 1
    assert abs(plateau - 60) <= 6
    assert values[onset + plateau] == 0


def test_stall_longer_than_max_catchup_resyncs_without_burst(lsl_module):
    trigger = lsl_module.LSLTrigger(enabled=True, keepalive_hz=600,
                                    nominal_srate=600)
    offset = [0.0]
    trigger._local_clock = lambda: time.monotonic() + offset[0]
    try:
        assert wait_until(lambda: len(trigger.outlet.snapshot()) > 10)
        resyncs_before = trigger.stats()["resyncs"]
        with trigger._lock:                 # simulate a 0.5 s stall
            n_before = len(trigger.outlet.snapshot())
            offset[0] += 5 * lsl_module._MAX_CATCHUP_S
        assert wait_until(
            lambda: trigger.stats()["resyncs"] > resyncs_before)
        with trigger._lock:
            n_after = len(trigger.outlet.snapshot())
    finally:
        trigger.stop()

    # A burst would be ~300 samples; the resync wake-up pushes one sample
    # (allow for one or two ordinary wake-ups before the lock is retaken).
    assert 1 <= n_after - n_before <= 4


def test_finish_latches_255_returns_to_zero_and_stops(lsl_module):
    trigger = lsl_module.LSLTrigger(enabled=True, keepalive_hz=600,
                                    nominal_srate=600)
    trigger.finish()
    values = [s["value"] for s in trigger.outlet.snapshot()]
    assert 255 in values
    assert 0 in values[values.index(255):]
    assert values[-1] == 0
    assert trigger._keepalive_thread is None

    trigger.finish()
    trigger.stop()
    trigger.finish()
    assert trigger.stats()["samples_sent"] == len(trigger.outlet.snapshot())


def test_disabled_trigger_is_noop(lsl_module):
    trigger = lsl_module.LSLTrigger(enabled=False)
    assert trigger.set_with_timestamp(11) is None
    trigger.set(11)
    trigger.clear()
    trigger.finish()
    trigger.stop()
    assert trigger.stats() == {"samples_sent": None, "seconds": None,
                               "rate_hz": None, "resyncs": None}
    assert FakeStreamOutlet.instances == []
