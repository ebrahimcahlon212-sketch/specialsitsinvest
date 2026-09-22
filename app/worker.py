"""One application worker; pending work exists only in memory."""

import logging
from queue import Queue
from threading import Lock, Thread

_queue = Queue()
_lock = Lock()
_thread = None
_busy = False


def _run():
    global _busy
    while True:
        function, args = _queue.get()
        try:
            function(*args)
        except Exception:
            logging.getLogger(__name__).exception('Background operation failed.')
        finally:
            with _lock:
                _busy = False
            _queue.task_done()


def submit(function, *args):
    global _thread, _busy
    with _lock:
        if _busy:
            raise ValueError('A background operation is already running. Wait for it to finish or cancel the active summary.')
        if _thread is None:
            _thread = Thread(target=_run, name='InvestResearch worker', daemon=True)
            _thread.start()
        _busy = True
        _queue.put((function, args))


def busy():
    with _lock:
        return _busy
