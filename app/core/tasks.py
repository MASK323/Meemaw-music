from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, Dict, Optional

from PySide6.QtCore import QObject, Signal


class TaskRunner(QObject):
    """Runs background tasks on a bounded pool with latest-request-wins."""

    done = Signal(str, object)
    failed = Signal(str, str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._executor = ThreadPoolExecutor(
            max_workers=10, thread_name_prefix="mm-task"
        )
        self._lock = threading.Lock()
        self._generations: Dict[str, int] = {}
        self._outstanding: Dict[str, int] = {}

    def run(self, token: str, fn: Callable, *args, **kwargs) -> bool:
        with self._lock:
            generation = self._generations.get(token, 0) + 1
            if self._outstanding.get(token, 0) >= 3:
                self._generations[token] = generation
                return False
            self._generations[token] = generation
            self._outstanding[token] = self._outstanding.get(token, 0) + 1
        try:
            future = self._executor.submit(
                self._worker, token, generation, fn, args, kwargs
            )
        except RuntimeError:
            with self._lock:
                self._outstanding[token] = max(
                    0, self._outstanding.get(token, 0) - 1
                )
                if self._generations.get(token) == generation:
                    self._generations.pop(token, None)
            raise
        future.add_done_callback(
            lambda completed: self._finish(token, generation, completed)
        )
        return True

    def _worker(
        self,
        token: str,
        generation: int,
        fn: Callable,
        args: tuple,
        kwargs: dict,
    ) -> object:
        return fn(*args, **kwargs)

    def _finish(self, token: str, generation: int, future: Future) -> None:
        with self._lock:
            self._outstanding[token] = max(
                0, self._outstanding.get(token, 0) - 1
            )
            if self._outstanding.get(token, 0) == 0:
                self._outstanding.pop(token, None)
            if self._generations.get(token) != generation:
                return
            self._generations.pop(token, None)
        try:
            result = future.result()
        except Exception as exc:
            self.failed.emit(token, str(exc))
            return
        self.done.emit(token, result)
