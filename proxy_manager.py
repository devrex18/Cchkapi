import requests
import threading
import time
import random
import itertools
from concurrent.futures import ThreadPoolExecutor, as_completed

AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6) AppleWebKit/605.1.15 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/119.0.0.0 Safari/537.36",
]

PROXY_SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
]


class ProxyManager:
    def __init__(self):
        self._live       = []
        self._dead       = set()
        self._lock       = threading.Lock()
        self._cycle      = None
        self._refreshing = False

    def _fetch_raw(self):
        proxies = []
        for url in PROXY_SOURCES:
            try:
                r = requests.get(
                    url, timeout=8,
                    headers={"User-Agent": random.choice(AGENTS)}
                )
                if r.status_code == 200:
                    for line in r.text.strip().split("\n"):
                        line = line.strip()
                        if ":" in line and len(line) < 25:
                            proxies.append("http://" + line)
            except Exception:
                pass
        return list(set(proxies))

    def _test_proxy(self, proxy):
        try:
            r = requests.get(
                "http://ip-api.com/json",
                proxies={"http": proxy, "https": proxy},
                timeout=4,
                headers={"User-Agent": random.choice(AGENTS)}
            )
            return proxy if r.status_code == 200 else None
        except Exception:
            return None

    def refresh(self):
        if self._refreshing:
            return
        self._refreshing = True
        try:
            raw   = self._fetch_raw()
            batch = raw[:80]
            live  = []

            with ThreadPoolExecutor(max_workers=8) as ex:
                futures = {ex.submit(self._test_proxy, p): p for p in batch}
                for f in as_completed(futures):
                    result = f.result()
                    if result:
                        live.append(result)

            with self._lock:
                self._live  = live
                self._dead  = set()
                self._cycle = itertools.cycle(live) if live else None

            print(f"[proxy] {len(live)} live proxies")

        except Exception as e:
            print(f"[proxy] refresh error: {e}")
        finally:
            self._refreshing = False

    def _loop(self):
        while True:
            try:
                self.refresh()
            except Exception as e:
                print(f"[proxy] loop error: {e}")
            time.sleep(1800)

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def get(self):
        with self._lock:
            if not self._cycle or not self._live:
                return None
            for _ in range(len(self._live) + 1):
                try:
                    p = next(self._cycle)
                    if p not in self._dead:
                        return {"http": p, "https": p}
                except StopIteration:
                    break
        return None

    def mark_dead(self, proxy):
        with self._lock:
            if proxy:
                self._dead.add(proxy)

    def status(self):
        with self._lock:
            return {
                "live":  len(self._live),
                "dead":  len(self._dead),
                "ready": self._cycle is not None
            }


proxy_mgr = ProxyManager()