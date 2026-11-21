"""An operating-system lock elects one recovery coordinator for a local profile."""

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def worker_leadership(directory: Path) -> Iterator[bool]:
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "compute-worker.lock").open("a+b") as stream:
        stream.seek(0)
        if sys.platform == "win32":
            import msvcrt

            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                yield False
                return
        else:
            import fcntl

            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
        # Closing the descriptor also releases ownership if the process stops.
        yield True
