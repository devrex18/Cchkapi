import requests
import threading
import time
import random
from proxy_manager import AGENTS

_cache = {}
_lock  = threading.Lock()
TTL    = 3600

EMOJI_MAP = {
    "UNITED STATES": "🇺🇸", "INDIA": "🇮🇳",
    "UNITED KINGDOM": "🇬🇧", "CANADA": "🇨🇦",
    "AUSTRALIA": "🇦🇺", "GERMANY": "🇩🇪",
    "FRANCE": "🇫🇷", "BRAZIL": "🇧🇷",
    "SOUTH KOREA": "🇰🇷", "JAPAN": "🇯🇵",
    "CHINA": "🇨🇳", "RUSSIA": "🇷🇺",
    "MEXICO": "🇲🇽", "ITALY": "🇮🇹",
    "SPAIN": "🇪🇸", "NETHERLANDS": "🇳🇱",
    "SINGAPORE": "🇸🇬", "HONG KONG": "🇭🇰",
    "TURKEY": "🇹🇷", "SAUDI ARABIA": "🇸🇦",
    "THAILAND": "🇹🇭", "INDONESIA": "🇮🇩",
    "PAKISTAN": "🇵🇰", "NIGERIA": "🇳🇬",
}

DEFAULT = {
    "brand": "UNKNOWN", "issuer": "UNKNOWN",
    "country": "UNKNOWN", "emoji": "🌐",
    "type": "UNKNOWN",   "level": "UNKNOWN",
}


def _flag(country):
    return EMOJI_MAP.get(country.upper(), "🌐")


def bin_lookup(cc):
    if not cc or len(cc) < 6:
        return DEFAULT.copy()

    bin6 = cc[:6]

    with _lock:
        entry = _cache.get(bin6)
        if entry and time.time() - entry["ts"] < TTL:
            return entry["data"]

    result = None

    try:
        r = requests.get(
            f"https://lookup.binlist.net/{bin6}",
            headers={"Accept-Version": "3", "User-Agent": random.choice(AGENTS)},
            timeout=5
        )
        if r.status_code == 200:
            d       = r.json()
            country = d.get("country", {}).get("name", "UNKNOWN").upper()
            result  = {
                "brand":   d.get("scheme", "UNKNOWN").upper(),
                "issuer":  d.get("bank", {}).get("name", "UNKNOWN").upper(),
                "country": country,
                "emoji":   d.get("country", {}).get("emoji", _flag(country)),
                "type":    d.get("type", "UNKNOWN").upper(),
                "level":   d.get("brand", "UNKNOWN").upper(),
            }
    except Exception:
        pass

    if not result:
        try:
            r = requests.get(
                f"https://api.bincodes.com/bin/?format=json&api_key=free&bin={bin6}",
                timeout=5
            )
            if r.status_code == 200:
                d       = r.json()
                country = d.get("country", "UNKNOWN").upper()
                result  = {
                    "brand":   d.get("card", "UNKNOWN").upper(),
                    "issuer":  d.get("bank", "UNKNOWN").upper(),
                    "country": country,
                    "emoji":   _flag(country),
                    "type":    d.get("type", "UNKNOWN").upper(),
                    "level":   "UNKNOWN",
                }
        except Exception:
            pass

    if not result:
        result = DEFAULT.copy()

    with _lock:
        _cache[bin6] = {"data": result, "ts": time.time()}

    return result