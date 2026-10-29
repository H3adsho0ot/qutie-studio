import io

import pytest

from qutie import cups_backend, protocol


def test_uri_roundtrip():
    assert cups_backend.uri_to_mac("qutie://aa-bb-cc-00-11-22") == "AA:BB:CC:00:11:22"
    assert cups_backend.mac_to_uri("aa:bb:cc:00:11:22") == "qutie://AA-BB-CC-00-11-22"


@pytest.mark.parametrize("uri", ["", "qutie://", "qutie://AA:BB:CC:00:11:22", "http://AA-BB-CC-00-11-22", "qutie://AA-BB"])
def test_bad_uris(uri):
    with pytest.raises(ValueError):
        cups_backend.uri_to_mac(uri)


def test_discovery_line_format(monkeypatch):
    monkeypatch.setattr(cups_backend.discovery, "scan", lambda seconds: [("AA:BB:CC:00:11:22", "Qutie-1122")])
    out = io.StringIO()
    cups_backend.discover(out)
    line = out.getvalue().strip()
    assert line.startswith('direct qutie://AA-BB-CC-00-11-22 "PRT Qutie" ')
    assert line.endswith('"MFG:PRT;MDL:Qutie;CLS:PRINTER;"')


def test_backend_without_uri_fails():
    assert cups_backend.main(["qutie", "1", "u", "t", "1", ""], env={}) == cups_backend.FAILED


class FakeSession:
    """Stands in for transport.Session; `statuses` is consumed by successive status() calls."""
    statuses = []
    sent = b""

    def __init__(self, mac):
        FakeSession.mac = mac
        FakeSession.flushed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def send(self, data):
        FakeSession.sent += data

    def flush(self):
        FakeSession.flushed = True

    def status(self):
        item = FakeSession.statuses.pop(0) if FakeSession.statuses else protocol.Status(100, 900, 0)
        if isinstance(item, Exception):
            raise item
        return item


ENV = {"DEVICE_URI": "qutie://AA-BB-CC-00-11-22"}


def run_job(monkeypatch, statuses, payload=b"JOB"):
    monkeypatch.setattr(cups_backend, "Session", FakeSession)
    FakeSession.sent, FakeSession.statuses = b"", list(statuses)
    rc = cups_backend.main(["qutie", "1", "u", "t", "1", ""], env=ENV, stdin=io.BytesIO(payload))
    return rc


def ok(flags=0, battery=100):
    return protocol.Status(battery, 900, flags)


def test_backend_streams_job_through_session(monkeypatch, capsys):
    payload = bytes(range(256)) * 40
    assert run_job(monkeypatch, [ok(), ok()], payload) == cups_backend.OK
    assert FakeSession.sent == payload and FakeSession.mac == "AA:BB:CC:00:11:22" and FakeSession.flushed
    err = capsys.readouterr().err
    assert "STATE: -media-empty-report,-cover-open-report,-other-report" in err


def test_cover_open_blocks_the_job_and_asks_for_retry(monkeypatch, capsys):
    assert run_job(monkeypatch, [ok(flags=0x10)]) == cups_backend.RETRY
    assert FakeSession.sent == b""
    err = capsys.readouterr().err
    assert "ERROR: Paper cover is open" in err and "+cover-open-report" in err and "-media-empty-report" in err
    assert "INFO: Not ready: paper cover is open" in err


def test_no_paper_blocks_the_job(monkeypatch, capsys):
    assert run_job(monkeypatch, [ok(flags=0x01)]) == cups_backend.RETRY
    assert "+media-empty-report" in capsys.readouterr().err


@pytest.mark.parametrize("flag", [0x02, 0x04, 0x20])
def test_other_blocking_conditions_report_other(monkeypatch, capsys, flag):
    assert run_job(monkeypatch, [ok(flags=flag)]) == cups_backend.RETRY
    assert "+other-report" in capsys.readouterr().err


def test_needs_charge_only_warns(monkeypatch, capsys):
    assert run_job(monkeypatch, [ok(flags=0x08), ok(flags=0x08)]) == cups_backend.OK
    assert FakeSession.sent == b"JOB"
    err = capsys.readouterr().err
    assert "WARNING: Battery needs charging" in err and "+other-report" in err


def test_low_battery_percentage_warns(monkeypatch, capsys):
    assert run_job(monkeypatch, [ok(battery=8), ok(battery=8)]) == cups_backend.OK
    assert "WARNING: Battery low (8%)" in capsys.readouterr().err


def test_unreadable_status_does_not_block_printing(monkeypatch, capsys):
    assert run_job(monkeypatch, [ValueError("garbled"), ValueError("garbled")]) == cups_backend.OK
    assert FakeSession.sent == b"JOB"
    assert "cannot read printer status" in capsys.readouterr().err


def test_problem_after_job_is_flagged_but_job_completes(monkeypatch, capsys):
    assert run_job(monkeypatch, [ok(), ok(flags=0x01)]) == cups_backend.OK
    err = capsys.readouterr().err
    assert "+media-empty-report" in err and "may not have printed" in err


def test_backend_retries_when_printer_unreachable(monkeypatch):
    def boom(mac):
        raise OSError("Host is down")
    monkeypatch.setattr(cups_backend, "Session", boom)
    rc = cups_backend.main(["qutie", "1", "u", "t", "1", ""], env={"DEVICE_URI": "qutie://AA-BB-CC-00-11-22"},
                           stdin=io.BytesIO(b"x"))
    assert rc == cups_backend.RETRY


def test_discovery_parses_bluetoothctl_output(monkeypatch):
    from qutie import discovery

    class Result:
        stdout = ("Device AA:BB:CC:00:11:22 Qutie-1122\nDevice 11:22:33:44:55:66 SomeSpeaker\n"
                  "Device 99:88:77:66:55:44 Qutie-5544\n")

    monkeypatch.setattr(discovery.subprocess, "run", lambda *a, **k: Result())
    assert discovery.known_printers() == [("AA:BB:CC:00:11:22", "Qutie-1122"), ("99:88:77:66:55:44", "Qutie-5544")]


def test_backend_reports_unreadable_job_file(tmp_path, capsys):
    rc = cups_backend.main(["qutie", "1", "u", "t", "1", "", str(tmp_path / "missing")],
                           env={"DEVICE_URI": "qutie://AA-BB-CC-00-11-22"})
    assert rc == cups_backend.FAILED
    assert "cannot read job data" in capsys.readouterr().err


def test_scan_waits_out_a_scan_that_is_already_running(monkeypatch):
    from qutie import discovery
    waited = []

    class BusyPopen:
        def __init__(self, args, stdout=None, **kw):
            stdout.write("Failed to start discovery: org.bluez.Error.InProgress\n")
            stdout.flush()

        def poll(self):
            return 1

        def wait(self, timeout=None):
            return 1

    monkeypatch.setattr(discovery.subprocess, "Popen", BusyPopen)
    monkeypatch.setattr(discovery.time, "sleep", lambda s: waited.append(s))
    monkeypatch.setattr(discovery, "known_printers", lambda: [("AA:BB:CC:00:11:22", "Qutie-1122")])
    assert discovery.scan(8) == [("AA:BB:CC:00:11:22", "Qutie-1122")] and waited == [8]


def test_scan_can_be_cancelled_and_stops_bluetoothctl(monkeypatch):
    import subprocess
    import threading
    import time
    from qutie import discovery

    real_popen = subprocess.Popen
    started = []

    def slow_popen(args, **kw):
        proc = real_popen(["sleep", "30"], **kw)
        started.append(proc)
        return proc

    monkeypatch.setattr(discovery.subprocess, "Popen", slow_popen)
    monkeypatch.setattr(discovery, "known_printers", lambda: [("AA:BB:CC:00:11:22", "Qutie-1122")])
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    began = time.monotonic()
    assert discovery.scan(8, cancel) == []               # cancelled scans report nothing
    assert time.monotonic() - began < 3
    assert started[0].poll() is not None                 # the child process is gone
