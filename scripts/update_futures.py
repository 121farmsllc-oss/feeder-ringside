#!/usr/bin/env python3
"""Update futures.json with current CME Live Cattle (LE) prices.

Standard library only. Sources, in order:
  1. CME Group settlements JSON (official settles; often blocks cloud/data-center IPs).
  2. Yahoo Finance chart API, one request per contract (LEZ26.CME ...). Yahoo's daily bar
     close equals the CME settlement once the session is final (checked against CME's
     Oct 1, 2026 final settles: all 10 contracts matched). A bar fetched the same evening
     can still be the last trade, so it is labeled "close" until a later run sees it the
     next day, when it is labeled "settle".

Never invents prices: a contract with no fresh quote is left out, and the file is not
written unless at least MIN_CONTRACTS contracts share the newest trade date.

Usage: python3 scripts/update_futures.py [--out futures.json] [--dry-run]
Exit code 0 = written or unchanged, 2 = no usable data (existing file left alone).
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

CT = ZoneInfo("America/Chicago")
ET = ZoneInfo("America/New_York")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
LETTERS = {2: "G", 4: "J", 6: "M", 8: "Q", 10: "V", 12: "Z"}
MON = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MIN_CONTRACTS = 6


def get(url, timeout=20, headers=None, ua=UA):
    h = {"User-Agent": ua, "Accept": "application/json,text/plain,*/*"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def candidate_months(today):
    """LE months from the current month through ~26 months out."""
    out = []
    y, m = today.year, today.month
    for i in range(0, 27):
        mm = (m - 1 + i) % 12 + 1
        yy = y + (m - 1 + i) // 12
        if mm in LETTERS:
            out.append((yy, mm))
    return out


def contract(y, m, price, date, symbol):
    return {"code": f"{MON[m]}{y}", "label": f"{MON[m]}{str(y)[2:]}", "symbol": symbol,
            "year": y, "month": m, "price": round(float(price), 3), "date": date}


def from_cme(now_ct):
    """Official CME settlements for the latest available trade date (tries today, then back 5 days)."""
    mon = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8,
           "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
    d = now_ct.date()
    for _ in range(6):
        if d.weekday() < 5:
            url = ("https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/22/FUT"
                   f"?strategy=DEFAULT&tradeDate={d:%m/%d/%Y}&pageSize=50")
            data = json.loads(get(url, headers={"Referer": "https://www.cmegroup.com/"}))
            rows = data.get("settlements") or []
            out = []
            for r in rows:
                parts = str(r.get("month", "")).split()
                if len(parts) != 2 or parts[0] not in mon:
                    continue
                try:
                    price = float(str(r.get("settle", "")).replace(",", ""))
                except ValueError:
                    continue
                y, m = 2000 + int(parts[1]), mon[parts[0]]
                out.append(contract(y, m, price, d.isoformat(), f"LE{LETTERS[m]}{str(y)[2:]}"))
            if out:
                final = str(data.get("reportType", "")).lower() == "final"
                return out, ("settle" if final else "close"), "CME Group settlements"
        d -= dt.timedelta(days=1)
    return [], None, None


def from_yahoo(now_ct):
    out = []
    for y, m in candidate_months(now_ct.date()):
        sym = f"LE{LETTERS[m]}{str(y)[2:]}"
        res, missing = None, False
        for attempt in range(4):
            host = "query1" if attempt % 2 == 0 else "query2"
            url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}.CME?range=10d&interval=1d"
            try:
                # Yahoo answers 429 to browser-like or library user agents; a bare "Mozilla/5.0" works.
                res = json.loads(get(url, ua="Mozilla/5.0"))["chart"]["result"]
                break
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    missing = True  # not listed / expired
                    break
                print(f"  yahoo {sym} ({host}): HTTP {e.code}", file=sys.stderr)
            except Exception as e:  # noqa: BLE001
                print(f"  yahoo {sym} ({host}): {e}", file=sys.stderr)
            time.sleep(2 + 3 * attempt)
        if missing or not res:
            continue
        if not res:
            continue
        r = res[0]
        ts = r.get("timestamp") or []
        closes = (r.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
        bars = [(t, c) for t, c in zip(ts, closes) if c is not None]
        if not bars:
            continue
        t, c = bars[-1]
        # Yahoo stamps daily futures bars at 00:00 New York time of the trade date
        date = dt.datetime.fromtimestamp(t, ET).date().isoformat()
        out.append(contract(y, m, c, date, sym))
        time.sleep(0.3)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "futures.json"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-cme", action="store_true")
    ap.add_argument("--now", help="testing only: pretend local CT time, e.g. 2026-10-03T06:30")
    args = ap.parse_args()
    now_ct = dt.datetime.fromisoformat(args.now).replace(tzinfo=CT) if args.now else dt.datetime.now(CT)

    rows, ptype, src = [], None, None
    if not args.skip_cme:
        try:
            rows, ptype, src = from_cme(now_ct)
        except Exception as e:  # noqa: BLE001
            print(f"CME settlements unavailable: {e}", file=sys.stderr)
    if not rows:
        rows = from_yahoo(now_ct)
        src = "Yahoo Finance (CME LE daily close)"
        ptype = None

    if not rows:
        print("No futures data from any source; leaving futures.json alone.", file=sys.stderr)
        return 2
    as_of = max(r["date"] for r in rows)
    fresh = [r for r in rows if r["date"] == as_of]
    bad = [r for r in fresh if not (100 <= r["price"] <= 400)]
    if len(fresh) < MIN_CONTRACTS or bad:
        print(f"Not enough sane contracts for {as_of} ({len(fresh)} fresh, {len(bad)} out of range); not writing.",
              file=sys.stderr)
        return 2
    if ptype is None:
        # Same-evening Yahoo bar may still be the last trade; a bar seen on a later CT date is the settle.
        ptype = "settle" if now_ct.date().isoformat() > as_of else "close"
    fresh.sort(key=lambda r: (r["year"], r["month"]))

    path = os.path.abspath(args.out)
    old = None
    if os.path.exists(path):
        try:
            old = json.load(open(path, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            old = None
    if old and str(old.get("asOf", "")) > as_of:
        print(f"Existing futures.json is newer ({old.get('asOf')} > {as_of}); not writing.")
        return 0
    if old and old.get("asOf") == as_of and old.get("priceType") == "settle" and ptype != "settle":
        print(f"Existing futures.json already has {as_of} settlements; not replacing with same-day closes.")
        return 0

    short = "CME settlements" if src.startswith("CME") else "CME data via Yahoo Finance"
    doc = {
        "schema": 1,
        "product": "CME Live Cattle futures (LE)",
        "units": "USD per cwt (= cents per lb)",
        "asOf": as_of,
        "priceType": ptype,
        "source": src,
        "sourceShort": short,
        "generatedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "contracts": fresh,
    }
    for r in fresh:
        print(f"  {r['label']}  {r['price']:8.3f}  {r['date']}  ({r['symbol']})")
    print(f"asOf {as_of} · {ptype} · {src} · {len(fresh)} contracts")

    def core(d):
        return {k: v for k, v in (d or {}).items() if k != "generatedAt"}

    if old and core(old) == core(doc):
        print("futures.json unchanged.")
        return 0
    if args.dry_run:
        print(json.dumps(doc, indent=2))
        return 0
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
