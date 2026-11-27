"""Advisory cross-process file locks (fcntl.flock) next to status.db."""

import errno
import fcntl
import math
import os
import time

LOCK_FILE_MODE = 0o664


def acquire_file_lock(lock_path: str, wait_seconds: float, poll_seconds: float) -> int | None:
    """Take an exclusive flock on lock_path; return the fd, or None if still held after wait_seconds.

    The file is opened read-only (flock needs no write access, so a lock file
    created by another user still works) and created with mode 0664 if
    missing. It is never deleted: deleting a lock file lets two processes lock
    different inodes.
    """
    created = not os.path.exists(lock_path)
    fd = os.open(lock_path, os.O_RDONLY | os.O_CREAT, LOCK_FILE_MODE)
    if created:
        try:
            os.fchmod(fd, LOCK_FILE_MODE)  # not narrowed by the umask
        except OSError:
            pass
    attempts = math.ceil(wait_seconds / poll_seconds) if wait_seconds > 0 else 0
    for attempt in range(attempts + 1):
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError as e:
            if e.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                os.close(fd)
                raise
        if attempt < attempts:
            time.sleep(poll_seconds)
    os.close(fd)
    return None


def release_file_lock(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)
