"""One save at a time. The workbooks are read, changed and written whole, and the host (Passenger on cPanel) may
run the app in several processes: two saves at once could each overwrite the other's change. Every request that
can change something (POST, PUT, PATCH, DELETE) holds a lock file in DATA_DIR while it runs; reads never wait.
"""
import os
from contextlib import contextmanager

from django.conf import settings

if os.name == "nt":
    import msvcrt
else:
    import fcntl

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@contextmanager
def write_lock():
    path = settings.DATA_DIR / ".write.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+b") as f:
        if os.name == "nt":
            f.seek(0)
            while True:  # msvcrt retries for about 10 s, then raises: keep waiting
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    pass
        else:
            fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)


class WriteLockMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method in SAFE_METHODS:
            return self.get_response(request)
        with write_lock():
            return self.get_response(request)
