import time
import threading
import os
from collections import defaultdict

LIMIT   = int(os.environ.get("RATE_LIMIT", "100"))
_counts = defaultdict(list)
_lock   = threading.Lock()


def is_rate_limited(key):
    now = time.time()
    with _lock:
        _counts[key] = [t for t in _counts[key] if now - t < 60]
        if len(_counts[key]) >= LIMIT:
            return True
        _counts[key].append(now)
        return False