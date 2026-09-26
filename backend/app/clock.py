"""The app's clock: real UTC time plus a fast-forward offset, so a demo can jump ahead to when posts are due.

The offset lives in memory, so restarting the backend (or "reset") returns to real time. Scheduled times are
stored as real UTC times, and a post is due once the clock (with its offset) reaches them. After a reset, posts
published during the fast-forward carry later timestamps than "now"; their metrics pause until real time catches up.
"""

import threading
from collections.abc import Callable
from datetime import datetime, timedelta

from app.db import utc_now


class VirtualClock:
    def __init__(self, real_now: Callable[[], datetime] = utc_now) -> None:
        self._real_now = real_now
        self._offset = timedelta(0)
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._real_now() + self._offset

    @property
    def offset(self) -> timedelta:
        with self._lock:
            return self._offset

    def reset(self) -> datetime:
        """Back to real time: drop the fast-forward offset."""
        with self._lock:
            self._offset = timedelta(0)
        return self.now()

    def advance(self, delta: timedelta) -> datetime:
        """Move the clock forward. Only reset() goes back, and only to real time."""
        if delta <= timedelta(0):
            raise ValueError(f"The clock only moves forward; got {delta}")
        with self._lock:
            self._offset += delta
        return self.now()


app_clock = VirtualClock()
