import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QPointF, QRectF  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PIL import Image, ImageChops  # noqa: E402

from qutie import protocol  # noqa: E402
from qutie.designer import app as designer_app, model, printing, render  # noqa: E402


@pytest.fixture
def window(monkeypatch):
    render.ensure_app()
    monkeypatch.setattr(designer_app.QMessageBox, "warning", lambda *a, **k: None)
    w = designer_app.MainWindow()
    w.show()
    QTest.qWait(30)
    yield w
    w.undo.setClean()
    w.close()


def place(window, tool, x=1.0, y=1.0):
    window.set_tool(tool)
    window.place_at(QPointF(x * 8, y * 8))
    return window.scene.doc.elements[-1]


@pytest.mark.parametrize("tool,kind", [("text", "text"), ("rect", "shape"), ("ellipse", "shape"), ("line", "shape"),
                                       ("qr", "qr"), ("barcode", "barcode")])
def test_every_tool_adds_an_element_inside_the_label(window, tool, kind):
    el = place(window, tool, x=500, y=500)            # clicks far outside are pulled back onto the label
    assert el.kind == kind
    assert 0 <= el.x <= window.scene.doc.length_mm - el.w and 0 <= el.y <= model.HEIGHT_MM - el.h
    assert window.tool == "select" and window.scene.selected_ids() == [el.id]


def test_properties_panel_edits_the_selected_element_and_merges_typing(window):
    el = place(window, "text")
    panel = window.properties
    assert panel.title.text() == "Text" and panel.stack.currentWidget() is panel.pages["text"]
    before = window.undo.count()
    panel.t_text.setPlainText("A")
    panel.t_text.setPlainText("AB")
    panel.t_text.setPlainText("ABC")
    assert window.scene.doc.find(el.id).text == "ABC" and window.undo.count() == before + 1
    panel.t_size.setValue(20)
    panel.t_bold.setChecked(True)
    live = window.scene.doc.find(el.id)
    assert live.size_pt == 20 and live.bold
    window.undo.undo()
    window.undo.undo()
    assert window.scene.doc.find(el.id).size_pt == 12 and not window.scene.doc.find(el.id).bold


def test_panel_follows_selection_and_model_changes(window):
    a = place(window, "rect", 1, 1)
    b = place(window, "qr", 20, 1)
    assert window.properties.pages["qr"] is window.properties.stack.currentWidget()
    window.scene.clearSelection()
    assert window.properties.title.text() == "Nothing selected"
    window.scene.select_only(a.id)
    assert window.properties.x.value() == window.scene.doc.find(a.id).x
    window.scene.edit([a.id], {"x": 7.5}, "Move")
    assert window.properties.x.value() == 7.5
    window.scene.select_only(b.id)
    window.properties.w.setValue(6)
    live = window.scene.doc.find(b.id)
    assert live.w == live.h == 6                       # QR codes stay square from the panel too


def test_invalid_code_data_shows_the_reason_in_the_panel(window):
    el = place(window, "barcode")
    window.properties.b_type.setCurrentIndex(window.properties.b_type.findData("ean13"))
    window.properties.b_data.setText("12")
    assert "12 digits" in window.properties.b_error.text() or "EAN" in window.properties.b_error.text()
    assert window.scene.problems()


def test_label_settings_panel(window):
    window.label_settings.length.setValue(60)
    window.label_settings.copies.setValue(3)
    window.label_settings.rotation.setCurrentIndex(window.label_settings.rotation.findData(90))
    doc = window.scene.doc
    assert (doc.length_mm, doc.copies, doc.rotation) == (60.0, 3, 90)
    window.undo.undo()
    assert window.scene.doc.rotation == 270


def test_duplicate_align_nudge_and_delete(window):
    el = place(window, "rect", 3, 3)
    window.duplicate_selected()
    assert len(window.scene.doc.elements) == 2
    clone = window.scene.doc.elements[1]
    assert (clone.x, clone.y) == (el.x + 2, el.y + 1) and window.scene.selected_ids() == [clone.id]
    window.align("left")
    assert window.scene.doc.find(clone.id).x == 0
    window.align("vcenter")
    live = window.scene.doc.find(clone.id)
    assert live.y == pytest.approx((model.HEIGHT_MM - live.h) / 2)
    window.nudge(0.5, 0)
    assert window.scene.doc.find(clone.id).x == 0.5
    window.delete_selected()
    assert len(window.scene.doc.elements) == 1


def test_align_uses_the_rotated_bounding_box(window):
    el = place(window, "rect", 10, 1)
    window.scene.edit([el.id], {"w": 10.0, "h": 4.0, "rotation": 90.0}, "Rotate")
    window.align("left")
    live = window.scene.doc.find(el.id)
    item = window.scene.item_for(el.id)
    assert item.mapRectToScene(0, 0, item.width, item.height).left() == pytest.approx(0, abs=0.01)
    assert live.x == pytest.approx(-3.0)               # a 10 x 4 box turned 90 degrees sticks out 3 mm each side


def test_save_open_roundtrip_and_dirty_flag(window, tmp_path, monkeypatch):
    place(window, "text")
    assert "*" in window.windowTitle()
    window.path = str(tmp_path / "a.qlabel")
    assert window.save() and "*" not in window.windowTitle()
    other = designer_app.MainWindow()
    monkeypatch.setattr(other, "_confirm_discard", lambda: True)
    other.open_label(window.path)
    assert other.scene.doc.to_json() == window.scene.doc.to_json()
    assert other.undo.isClean() and not other.undo.canUndo()
    other.undo.setClean()
    other.close()


def test_opening_a_broken_file_reports_and_keeps_the_document(window, tmp_path):
    place(window, "text")
    bad = tmp_path / "bad.qlabel"
    bad.write_text("{not json")
    window.undo.setClean()
    window.open_label(str(bad))
    assert len(window.scene.doc.elements) == 1


def test_preview_overlay_shows_one_bit_and_never_reaches_the_print_image(window):
    place(window, "text")
    plain = render.render_scene(window.scene)
    window.act_preview.setChecked(True)
    window._update_preview()
    assert window.overlay is not None and window.overlay.zValue() > 1000
    assert ImageChops.difference(plain, render.render_scene(window.scene)).getbbox() is None
    window.act_preview.setChecked(False)
    window._update_preview()
    assert window.overlay is None


def test_export_png_is_one_bit_landscape(window, tmp_path, monkeypatch):
    place(window, "qr")
    window.scene.doc.trim = False
    target = tmp_path / "out.png"
    monkeypatch.setattr(designer_app.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    window.export_png()
    img = Image.open(target)
    assert img.mode == "1" and img.size == (320, 96)


def test_printing_refuses_problem_labels(window, monkeypatch):
    place(window, "barcode")
    window.scene.edit([window.scene.doc.elements[0].id], {"symbology": "ean13", "data": "x"}, "Edit")
    started = []
    monkeypatch.setattr(window, "_run_printer_job", lambda image: started.append(image))
    window.print_label()
    assert started == []


# --- printer worker -------------------------------------------------------------------------------
class FakeSession:
    statuses = []
    sent = []

    def __init__(self, mac, **kw):
        self.mac = mac

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def status(self):
        item = FakeSession.statuses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def send(self, data):
        FakeSession.sent.append(data)

    def flush(self):
        pass


@pytest.fixture
def fake_session(monkeypatch):
    FakeSession.sent, FakeSession.statuses = [], []
    monkeypatch.setattr(printing, "Session", FakeSession)
    return FakeSession


def ready(flags=0, battery=100):
    return protocol.Status(battery, 900, flags)


def test_worker_prints_and_reports(fake_session):
    fake_session.statuses = [ready(), ready()]
    worker = printing.PrinterWorker("AA:BB:CC:00:11:22", Image.new("L", (320, 96), 0), copies=2, density=90,
                                    rotation=270, feed_mm=4)
    states = []
    worker.status.connect(states.append)
    assert worker._run() == "Printed."
    assert fake_session.sent.count(protocol.cmd_density(90)) == 2 and len(states) == 2
    assert fake_session.sent[-1] == protocol.cmd_feed(32)


def test_worker_does_not_print_when_cover_is_open(fake_session):
    fake_session.statuses = [ready(flags=0x10)]
    worker = printing.PrinterWorker("AA:BB:CC:00:11:22", Image.new("L", (320, 96), 0))
    with pytest.raises(OSError, match="cover is open"):
        worker._run()
    assert fake_session.sent == []


def test_worker_flags_a_problem_after_sending(fake_session):
    fake_session.statuses = [ready(), ready(flags=0x01)]
    worker = printing.PrinterWorker("AA:BB:CC:00:11:22", Image.new("L", (320, 96), 0))
    message = worker._run()
    assert "out of paper" in message and "may not have printed" in message


def test_worker_status_check_only(fake_session):
    fake_session.statuses = [ready(battery=64)]
    worker = printing.PrinterWorker("AA:BB:CC:00:11:22")
    assert "64%" in worker._run() and fake_session.sent == []


def test_worker_reports_unreachable_printer_through_the_signal(monkeypatch):
    def boom(mac, **kw):
        raise OSError("Something odd")
    monkeypatch.setattr(printing, "Session", boom)
    worker = printing.PrinterWorker("AA:BB:CC:00:11:22")
    results = []
    worker.finished.connect(lambda ok, msg: results.append((ok, msg)))
    worker.run()
    assert results == [(False, "Something odd")]


# --- regression: scan dialog and thread ownership --------------------------------------------------
class SlowScanWorker(printing.Worker):
    found = printing.Signal(list)

    def __init__(self, seconds=8, delay=0.6, printers=()):
        super().__init__()
        import threading
        self.delay, self.printers = delay, list(printers)
        self.cancel = threading.Event()

    @printing.Slot()
    def run(self):
        import time
        time.sleep(self.delay)
        self.found.emit(self.printers)
        self.finished.emit(True, "done")


def wait_until(condition, timeout=5.0):
    import time
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QTest.qWait(20)
        if condition():
            return True
    return False


def test_cancelling_the_printer_dialog_during_a_scan_does_not_crash(window, monkeypatch):
    monkeypatch.setattr(designer_app, "ScanWorker", SlowScanWorker)
    dialog = designer_app.FindPrintersDialog(window)
    assert printing._active                              # scan thread is running
    worker = dialog._scan_worker
    dialog.reject()
    assert worker.cancel.is_set()                        # closing the dialog cancels the scan
    del dialog                                           # a dialog parented to nothing is destroyed here
    import gc
    gc.collect()
    assert wait_until(lambda: not printing._active)      # thread finished by itself; no "Destroyed while running"


def test_scan_dialog_disables_rescan_and_explains_an_empty_result(window, monkeypatch):
    monkeypatch.setattr(designer_app, "ScanWorker", lambda seconds: SlowScanWorker(delay=0.3))
    dialog = designer_app.FindPrintersDialog(window)
    assert not dialog.rescan.isEnabled()
    assert wait_until(lambda: dialog.rescan.isEnabled())
    assert "No Qutie found" in dialog.status.text()
    dialog.reject()


def test_scan_dialog_lists_found_printers(window, monkeypatch):
    found = [("AA:BB:CC:00:11:22", "Qutie-1122")]
    monkeypatch.setattr(designer_app, "ScanWorker", lambda seconds: SlowScanWorker(delay=0.1, printers=found))
    dialog = designer_app.FindPrintersDialog(window)
    assert wait_until(lambda: dialog.rescan.isEnabled())
    assert dialog.list.count() == 1 and "1 printer(s) found" in dialog.status.text()
    dialog._accept()
    assert dialog.mac == "AA:BB:CC:00:11:22"
    dialog.reject()


def test_job_results_are_delivered_on_the_gui_thread(window, monkeypatch):
    from PySide6.QtCore import QThread
    seen = {}

    class FakeWorker(printing.Worker):
        status = printing.Signal(object)
        progress = printing.Signal(int, int)

        def __init__(self, *a, **k):
            super().__init__()

        @printing.Slot()
        def run(self):
            seen["worker"] = QThread.currentThread()
            self.status.emit(ready())
            self.finished.emit(True, "Printed.")

    monkeypatch.setattr(designer_app, "PrinterWorker", FakeWorker)
    monkeypatch.setattr(designer_app.QMessageBox, "information", lambda *a, **k: seen.setdefault("box", QThread.currentThread()))
    window.settings.setValue("printer/mac", "AA:BB:CC:00:11:22")
    original = window._job_done

    def job_done(ok, message):
        seen["slot"] = QThread.currentThread()
        original(ok, message)

    window.check_printer()
    # the real slot is connected by bound method; verify through its side effects
    assert wait_until(lambda: not window._busy)
    gui = QThread.currentThread()
    assert seen["worker"] is not gui and seen["box"] is gui
    assert "battery 100%" in window.printer_label.text()


def test_window_refuses_to_close_while_the_printer_is_busy(window, monkeypatch):
    shown = []
    monkeypatch.setattr(designer_app.QMessageBox, "information", lambda *a, **k: shown.append(a))
    window._busy = True
    assert window.close() is False and shown
    window._busy = False


# --- unreachable printer ---------------------------------------------------------------------------
@pytest.mark.parametrize("exc", [OSError(112, "Host is down"), OSError(111, "Connection refused"),
                                 TimeoutError("timed out"), OSError(104, "Connection reset by peer")])
def test_unreachable_errors_get_a_helpful_message(exc):
    message, unreachable = printing.explain(exc)
    assert unreachable and "Cannot reach the printer" in message and "long-press" in message


def test_other_errors_are_passed_through_unchanged():
    assert printing.explain(OSError("Printer not ready: paper cover is open")) == (
        "Printer not ready: paper cover is open", False)
    assert printing.explain(ValueError("bad")) == ("bad", False)


def test_worker_signals_unreachable_before_finishing(monkeypatch):
    def boom(mac, **kw):
        raise OSError(112, "Host is down")
    monkeypatch.setattr(printing, "Session", boom)
    worker = printing.PrinterWorker("AA:BB:CC:00:11:22")
    events = []
    worker.unreachable.connect(lambda: events.append("unreachable"))
    worker.finished.connect(lambda ok, msg: events.append(("finished", ok, "Cannot reach" in msg)))
    worker.run()
    assert events == ["unreachable", ("finished", False, True)]


def test_window_offers_a_rescan_and_retries_the_print(window, monkeypatch):
    place(window, "text")
    window.settings.setValue("printer/mac", "AA:BB:CC:00:11:22")
    calls = {"jobs": 0}

    class FailThenWork(printing.Worker):
        status = printing.Signal(object)
        progress = printing.Signal(int, int)

        def __init__(self, mac, *a, **k):
            super().__init__()
            self.mac = mac

        @printing.Slot()
        def run(self):
            calls["jobs"] += 1
            if self.mac == "AA:BB:CC:00:11:22":
                self.unreachable.emit()
                self.finished.emit(False, "Cannot reach the printer (Host is down).")
            else:
                self.finished.emit(True, "Printed.")

    asked = []
    monkeypatch.setattr(designer_app, "PrinterWorker", FailThenWork)
    monkeypatch.setattr(window, "_ask_rescan", lambda message: asked.append(message) or True)
    monkeypatch.setattr(window, "choose_printer", lambda: window.settings.setValue("printer/mac", "11:22:33:44:55:66") or "11:22:33:44:55:66")
    window.print_label()
    assert wait_until(lambda: calls["jobs"] == 2 and not window._busy)
    assert len(asked) == 1 and "Cannot reach the printer" in asked[0]
    assert window.printer_mac() == "11:22:33:44:55:66"


def test_window_without_rescan_choice_just_stops(window, monkeypatch):
    place(window, "text")
    window.settings.setValue("printer/mac", "AA:BB:CC:00:11:22")
    jobs = []

    class AlwaysUnreachable(printing.Worker):
        status = printing.Signal(object)
        progress = printing.Signal(int, int)

        def __init__(self, *a, **k):
            super().__init__()

        @printing.Slot()
        def run(self):
            jobs.append(1)
            self.unreachable.emit()
            self.finished.emit(False, "Cannot reach the printer")

    monkeypatch.setattr(designer_app, "PrinterWorker", AlwaysUnreachable)
    monkeypatch.setattr(window, "_ask_rescan", lambda message: False)
    window.print_label()
    assert wait_until(lambda: not window._busy)
    QTest.qWait(100)
    assert jobs == [1]


def test_worker_keeps_asking_while_the_printer_is_busy_printing(fake_session):
    fake_session.statuses = [ready(), ValueError("no reply"), ValueError("no reply"), ready()]
    worker = printing.PrinterWorker("AA:BB:CC:00:11:22", Image.new("L", (320, 96), 0))
    assert worker._run() == "Printed."


def test_worker_gives_up_quietly_if_the_printer_never_answers_after_printing(fake_session, monkeypatch):
    fake_session.statuses = [ready()] + [ValueError("no reply")] * 50
    monkeypatch.setattr(printing.PrinterWorker, "_status_after_printing",
                        staticmethod(lambda session, timeout=0.0: None))
    worker = printing.PrinterWorker("AA:BB:CC:00:11:22", Image.new("L", (320, 96), 0))
    assert worker._run() == "Sent to the printer."


def test_tests_never_use_the_real_user_configuration(window):
    import os
    window.settings.setValue("printer/mac", "AA:BB:CC:00:11:22")
    window.settings.sync()
    assert window.settings.fileName().startswith(os.environ["XDG_CONFIG_HOME"])
    assert "qutie-test-config-" in window.settings.fileName()


# --- status bar and background monitoring ----------------------------------------------------------
def label_state(window):
    return window.printer_label.text(), window.printer_label.styleSheet()


def test_status_bar_colours_and_text(window):
    window.settings.setValue("printer/name", "Qutie-1122")
    window._show_status(ready())
    text, style = label_state(window)
    assert "Qutie-1122" in text and "ready" in text and "battery 100%" in text and "#2e9e4f" in style
    window._show_status(ready(flags=0x10))
    text, style = label_state(window)
    assert "paper cover is open" in text and "#d64545" in style
    window._show_status(ready(flags=0x08, battery=40))
    text, style = label_state(window)
    assert "needs charging" in text and "#d98e04" in style
    window._show_status(ready(battery=7))
    text, style = label_state(window)
    assert "charge soon" in text and "#d98e04" in style
    window._show_unreachable()
    assert "not reachable" in label_state(window)[0]
    window.settings.remove("printer/name")


def test_status_tooltip_has_check_time_and_auto_off(window):
    window._show_status(ready())
    assert "Checked at" in window.printer_label.toolTip() and "15 min" in window.printer_label.toolTip()


def test_polling_only_when_it_makes_sense(window, monkeypatch):
    monkeypatch.setattr(window, "isActiveWindow", lambda: True)
    window.settings.setValue("printer/mac", "AA:BB:CC:00:11:22")
    window.act_monitor.setChecked(True)
    assert window._should_poll()
    window.act_monitor.setChecked(False)
    assert not window._should_poll()
    window.act_monitor.setChecked(True)
    window._busy = True
    assert not window._should_poll()
    window._busy = False
    window._polling = True
    assert not window._should_poll()
    window._polling = False
    monkeypatch.setattr(window, "isActiveWindow", lambda: False)     # never keep the printer awake in the background
    assert not window._should_poll()
    monkeypatch.setattr(window, "isActiveWindow", lambda: True)
    window.settings.remove("printer/mac")
    assert not window._should_poll()


class PollWorker(printing.Worker):
    status = printing.Signal(object)
    progress = printing.Signal(int, int)
    created = []
    outcome = "ready"

    def __init__(self, mac, *a, **k):
        super().__init__()
        PollWorker.created.append((mac, k))

    @printing.Slot()
    def run(self):
        if PollWorker.outcome == "unreachable":
            self.unreachable.emit()
            self.finished.emit(False, "Cannot reach the printer")
        else:
            self.status.emit(ready(battery=88))
            self.finished.emit(True, "battery 88%, ready")


@pytest.fixture
def pollable(window, monkeypatch):
    PollWorker.created, PollWorker.outcome = [], "ready"
    monkeypatch.setattr(designer_app, "PrinterWorker", PollWorker)
    monkeypatch.setattr(window, "isActiveWindow", lambda: True)
    window.settings.setValue("printer/mac", "AA:BB:CC:00:11:22")
    window.act_monitor.setChecked(True)
    window._last_poll = 0.0
    boxes = []
    for name in ("warning", "information", "question", "critical"):
        monkeypatch.setattr(designer_app.QMessageBox, name, lambda *a, _n=name, **k: boxes.append(_n))
    window.boxes = boxes
    return window


def test_poll_updates_the_status_bar_quietly_with_a_single_attempt(pollable):
    pollable._poll_printer()
    assert wait_until(lambda: not pollable._polling)
    assert "battery 88%" in label_state(pollable)[0] and pollable.boxes == []
    assert PollWorker.created[0][1].get("attempts") == 1              # fail fast instead of retrying


def test_poll_failure_shows_not_reachable_without_dialogs(pollable):
    PollWorker.outcome = "unreachable"
    pollable._poll_printer()
    assert wait_until(lambda: not pollable._polling)
    assert "not reachable" in label_state(pollable)[0] and pollable.boxes == []


def test_polls_are_rate_limited_but_can_be_forced(pollable):
    pollable._poll_printer()
    assert wait_until(lambda: not pollable._polling)
    pollable._poll_printer()                      # too soon after the last one
    assert len(PollWorker.created) == 1
    pollable._poll_printer(force=True)
    assert wait_until(lambda: not pollable._polling)
    assert len(PollWorker.created) == 2


def test_a_job_waits_for_a_running_status_check(pollable):
    place(pollable, "text")
    pollable._polling = True
    pollable.print_label()
    QTest.qWait(150)
    assert PollWorker.created == []               # nothing started while the poll holds the connection
    pollable._polling = False
    assert wait_until(lambda: len(PollWorker.created) == 1)


def test_monitor_toggle_is_remembered_and_triggers_a_check(pollable):
    pollable.act_monitor.setChecked(False)
    pollable._toggle_monitor()
    assert pollable.settings.value("printer/monitor", True, type=bool) is False
    pollable.act_monitor.setChecked(True)
    pollable._toggle_monitor()
    assert pollable.settings.value("printer/monitor", False, type=bool) is True
    assert wait_until(lambda: len(PollWorker.created) == 1)


def test_poll_timer_runs_every_thirty_seconds(window):
    assert window._poll_timer.isActive() and window._poll_timer.interval() == designer_app.POLL_MS == 30_000


# --- trimming and fitting ----------------------------------------------------------------------------
def test_new_labels_trim_by_default_but_old_files_do_not():
    assert model.Label().trim is True and model.Label().trim_margin_mm == 1.0
    old = model.Label.from_json('{"version": 1, "label": {"length_mm": 40}, "elements": []}')
    assert old.trim is False


def test_trim_fields_roundtrip_and_margin_is_clamped():
    label = model.Label(trim=False, trim_margin_mm=2.5)
    again = model.Label.from_json(label.to_json())
    assert (again.trim, again.trim_margin_mm) == (False, 2.5)
    wild = model.Label.from_json('{"version": 1, "label": {"trim": true, "trim_margin_mm": 99}, "elements": []}')
    assert wild.trim_margin_mm == 10.0


def test_trim_to_content_keeps_only_ink_plus_margin():
    img = Image.new("L", (200, 96), 255)
    for x in range(40, 100):
        img.putpixel((x, 10), 0)
    out = render.trim_to_content(img, 8)
    assert out.size == (60 + 16, 96)
    assert render.ink_extent(out) == (8, 68)             # margin before the ink, ink width kept
    assert render.trim_to_content(Image.new("L", (50, 96), 255), 8).size == (50, 96)    # blank stays as is


def test_ink_is_measured_not_the_element_box(window):
    window.scene.doc.trim = True
    el = place(window, "text", 1, 1)
    window.scene.edit([el.id], {"text": "I", "w": 30.0, "size_pt": 12.0}, "Edit")     # tiny ink in a wide box
    printed = window.printable_image()
    assert printed.width < 80 and printed.width < 30 * 8


def test_print_uses_the_trimmed_image(window, monkeypatch):
    el = place(window, "text", 1, 1)
    window.scene.edit([el.id], {"text": "Hi", "w": 30.0}, "Edit")
    got = []
    monkeypatch.setattr(window, "_run_printer_job", lambda image: got.append(image))
    window.print_label()
    assert got and got[0].width < window.scene.doc.size_dots[0]
    window.scene.edit_label(trim=False)
    window.print_label()
    assert got[1].width == window.scene.doc.size_dots[0]


def test_fit_length_moves_content_to_the_start_and_is_one_undo_step(window):
    a = place(window, "rect", 10, 2)
    window.scene.edit([a.id], {"x": 12.0, "w": 6.0, "h": 6.0, "stroke_mm": 0.5}, "Edit")
    b = place(window, "rect", 20, 2)
    window.scene.edit([b.id], {"x": 22.0, "w": 5.0, "h": 6.0}, "Edit")
    window.scene.doc.trim_margin_mm = 1.0
    before = render.render_scene(window.scene, QRectF(12 * 8 - 8, 0, 15 * 8 + 16, 96))
    count = window.undo.count()
    window.fit_length_to_content()
    doc = window.scene.doc
    assert window.undo.count() == count + 1               # whole fit is a single macro
    assert doc.length_mm == pytest.approx(15 + 2)         # 12..27 mm of content + 1 mm margin each side
    assert doc.find(a.id).x == pytest.approx(1.0) and doc.find(b.id).x == pytest.approx(11.0)
    after = render.render_scene(window.scene, QRectF(0, 0, doc.size_dots[0], 96))
    assert ImageChops.difference(before, after).getbbox() is None      # content is pixel-identical, just moved
    assert render.ink_extent(after) == (8, doc.size_dots[0] - 8)
    window.undo.undo()
    assert window.scene.doc.length_mm == 40.0 and window.scene.doc.find(a.id).x == 12.0


def test_fit_length_sees_content_outside_the_label_and_respects_limits(window):
    el = place(window, "rect", 1, 1)
    window.scene.edit([el.id], {"x": -6.0, "w": 10.0, "h": 6.0}, "Edit")          # partly off the left edge
    window.fit_length_to_content()
    doc = window.scene.doc
    assert doc.find(el.id).x == pytest.approx(1.0) and doc.length_mm == pytest.approx(12.0)
    tiny = place(window, "rect", 1, 1)
    window.scene.edit([tiny.id], {"x": 1.0, "w": 1.0, "h": 1.0}, "Edit")
    for e in list(window.scene.doc.elements):
        if e.id != tiny.id:
            window.scene.select_only(e.id)
            window.delete_selected()
    window.fit_length_to_content()
    assert window.scene.doc.length_mm == model.MIN_LENGTH_MM


def test_fit_on_an_empty_label_does_nothing(window):
    window.fit_length_to_content()
    assert window.scene.doc.length_mm == 40.0 and window.undo.count() == 0


def test_label_panel_controls_and_info_text(window):
    panel = window.label_settings
    el = place(window, "rect", 5, 2)
    window.scene.edit([el.id], {"x": 15.0, "w": 6.0, "h": 6.0}, "Edit")
    window._refresh_extras()
    assert "Prints" in panel.info.text() and "saves" in panel.info.text()
    panel.trim.setChecked(False)
    window._refresh_extras()
    assert window.scene.doc.trim is False and "whole 40" in panel.info.text() and not panel.margin.isEnabled()
    panel.trim.setChecked(True)
    panel.margin.setValue(2.0)
    assert window.scene.doc.trim_margin_mm == 2.0
    window.undo.undo()
    assert window.scene.doc.trim_margin_mm == 1.0
    panel.fitRequested.emit()
    assert window.scene.doc.length_mm < 40.0                       # the button is wired to the fit action


def test_preview_greys_out_the_trimmed_zones(window):
    el = place(window, "rect", 5, 2)
    window.scene.edit([el.id], {"x": 15.0, "w": 6.0, "h": 6.0, "fill": True}, "Edit")
    window.act_preview.setChecked(True)
    window._update_preview()
    image = window.overlay.pixmap().toImage()
    far_left = image.pixelColor(5, 48)
    inside = image.pixelColor(15 * 8 + 24, 48)
    assert far_left.red() < 255 and far_left.red() > 0 and far_left.blue() > far_left.red()      # shaded, not black/white
    assert inside.red() == 0                                                                  # the ink itself is untouched
    window.scene.edit_label(trim=False)
    window._update_preview()
    assert window.overlay.pixmap().toImage().pixelColor(5, 48).red() == 255
