"""Background work for the GUI: run a function in a thread, deliver progress / result on the Tk thread."""
import queue
import threading
import time

from pdf_parser import CancelledError


class Task:
    def __init__(self):
        self.cancel_event = threading.Event()
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        self.cancel_event.set()


class TaskRunner:
    """Widgets are only ever touched from callbacks that run in the Tk main loop (via after())."""

    def __init__(self, root, interval_ms=60):
        self.root = root
        self.interval = interval_ms
        self.q = queue.Queue()
        self.active = 0
        self._polling = False

    def run(self, fn, on_done=None, on_error=None, on_progress=None):
        """fn(progress) -> result.  progress(fraction 0..1, text) may raise CancelledError."""
        task = Task()
        last = [0.0]

        def progress(frac, text=''):
            if task.cancel_event.is_set():
                raise CancelledError()
            t = time.monotonic()
            if frac >= 1 or t - last[0] > 0.05:
                last[0] = t
                self.q.put((task, 'prog', (frac, text), on_progress))

        def work():
            try:
                res = fn(progress)
                self.q.put((task, 'done', res, on_done))
            except CancelledError:
                self.q.put((task, 'cancel', None, None))
            except BaseException as e:                      # delivered to on_error on the Tk thread
                self.q.put((task, 'err', e, on_error))

        self.active += 1
        threading.Thread(target=work, daemon=True).start()
        if not self._polling:
            self._polling = True
            self.root.after(self.interval, self._poll)
        return task

    def _poll(self):
        try:
            while True:
                task, kind, payload, cb = self.q.get_nowait()
                if kind in ('done', 'err', 'cancel'):
                    self.active -= 1
                if task.cancelled or cb is None:
                    continue
                cb(*payload) if kind == 'prog' else cb(payload)
        except queue.Empty:
            pass
        if self.active > 0:
            self.root.after(self.interval, self._poll)
        else:
            self._polling = False
