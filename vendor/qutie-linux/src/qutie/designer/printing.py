"""Background workers: printer discovery, status check and printing (all Bluetooth I/O off the UI thread)."""
import errno
import threading
import time

from PIL import Image
from PySide6.QtCore import QObject, QThread, Signal, Slot

from .. import discovery, job, protocol
from ..transport import Session


UNREACHABLE_ERRNOS = {errno.EHOSTDOWN, errno.EHOSTUNREACH, errno.ECONNREFUSED, errno.ECONNRESET,
                      errno.ECONNABORTED, errno.ETIMEDOUT, errno.ENETDOWN, errno.ENODEV, errno.EBADFD}


def explain(exc: Exception) -> tuple[str, bool]:
    """Turn an exception into text for the user; the flag says the printer could not be reached at all."""
    if isinstance(exc, TimeoutError) or (isinstance(exc, OSError) and exc.errno in UNREACHABLE_ERRNOS):
        detail = exc.strerror if isinstance(exc, OSError) and exc.strerror else "no answer"
        return ("Cannot reach the printer (" + detail + ").\n\n"
                "- Switch it on (long-press the power button) and keep it close to this computer.\n"
                "- Make sure no phone is connected to it; it only talks to one device at a time.\n"
                "- If you replaced the printer, choose it again."), True
    return (str(exc) or exc.__class__.__name__), False


class Worker(QObject):
    finished = Signal(bool, str)     # ok, message
    unreachable = Signal()           # emitted just before `finished` when the printer could not be reached

    def run_safely(self, func):
        try:
            message = func()
            self.finished.emit(True, message or "")
        except (OSError, ValueError, ConnectionError) as exc:
            message, unreachable = explain(exc)
            if unreachable:
                self.unreachable.emit()
            self.finished.emit(False, message)


class ScanWorker(Worker):
    found = Signal(list)

    def __init__(self, seconds: int = 8):
        super().__init__()
        self.seconds = seconds
        self.cancel = threading.Event()

    @Slot()
    def run(self):
        def scan():
            printers = discovery.scan(self.seconds, self.cancel)
            self.found.emit(printers)
            return f"{len(printers)} printer(s) found"
        self.run_safely(scan)


class PrinterWorker(Worker):
    """Checks the printer status and, when given an image, prints it."""
    status = Signal(object)          # protocol.Status
    progress = Signal(int, int)      # copy, copies

    def __init__(self, mac: str, image: Image.Image | None = None, copies: int = 1, density: int = 75,
                 rotation: int = 270, feed_mm: float = 14.0, attempts: int = 2):
        super().__init__()
        self.mac, self.image, self.attempts = mac, image, attempts
        self.options = dict(copies=copies, density=density, rotation=rotation, feed_mm=feed_mm)

    @Slot()
    def run(self):
        self.run_safely(self._run)

    @staticmethod
    def _status_after_printing(session, timeout: float = 8.0):
        """The printer does not answer while it is mechanically printing, so ask repeatedly for a few seconds."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                return session.status()
            except ValueError:
                continue          # no (or partial) reply yet
            except OSError:
                return None
        return None

    def _run(self) -> str:
        with Session(self.mac, attempts=self.attempts) as session:
            before = session.status()
            self.status.emit(before)
            if not before.can_print:
                raise OSError("Printer not ready: " + ", ".join(before.problems))
            if self.image is None:
                return describe(before)
            job.send_image(session, self.image, progress=self.progress.emit, **self.options)
            after = self._status_after_printing(session)
            if after is None:
                return "Sent to the printer."
            self.status.emit(after)
            if not after.can_print:
                return "Sent, but the printer reports: " + ", ".join(after.problems) + " - the label may not have printed."
            return "Printed."


def describe(status: protocol.Status) -> str:
    state = "ready" if not status.problems else ", ".join(status.problems)
    return f"battery {status.battery}%, {state}"


_active: set = set()      # running (thread, worker) pairs; a QThread must outlive its run, whoever started it


def run_in_thread(worker: Worker) -> QThread:
    """Run `worker.run` on a new thread. The thread is owned here, so closing the dialog or window that started
    it cannot destroy it while it is still running; it cleans itself up when the worker finishes."""
    thread = QThread()
    entry = (thread, worker)
    _active.add(entry)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    thread.finished.connect(lambda: _active.discard(entry))
    thread.finished.connect(worker.deleteLater)
    thread.start()
    return thread


def shutdown(timeout_ms: int = 4000) -> None:
    """Stop scans and wait for worker threads; call before the application exits."""
    for thread, worker in list(_active):
        getattr(worker, "cancel", threading.Event()).set()
        thread.quit()
        thread.wait(timeout_ms)
