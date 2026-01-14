import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timezone

ATM_BAND = 0.10 
#there is no guard for max>min. i guarded for when i accidently put the numbers in backwards. because i built this tool for personal use. 
def safe_sum(df, col):
    if df is None or df.empty or col not in df.columns:
        return np.nan
    s = pd.to_numeric(df[col], errors="coerce")
    return float(s.sum()) if s.notna().any() else np.nan

def filter_near_atm(df, spot):
    if df is None or df.empty or 'strike' not in df.columns:
        return pd.DataFrame()
    strikes = pd.to_numeric(df['strike'], errors="coerce")
    return df[(strikes >= spot * (1 - ATM_BAND)) & (strikes <= spot * (1 + ATM_BAND))]

def nearest_iv(df, spot):
    if df is None or df.empty:
        return np.nan
    if 'strike' not in df.columns or 'impliedVolatility' not in df.columns:
        return np.nan

    strikes = pd.to_numeric(df['strike'], errors="coerce")
    ivs = pd.to_numeric(df['impliedVolatility'], errors="coerce")
    valid = strikes.notna() & ivs.notna() & (ivs > 0)
    if not valid.any():
        return np.nan

    idx = (strikes[valid] - spot).abs().idxmin()
    return float(ivs.at[idx])

def get_current_price(t):
    hist = t.history(period="5d")
    if hist is not None and not hist.empty:
        try:
            return float(hist['Close'].iloc[-1])
        except Exception:
            pass

    fast = getattr(t, "fast_info", {}) or {}
    for k in ("last_price", "last_trade_price"):
        if k in fast:
            try:
                return float(fast[k])
            except Exception:
                pass

    info = getattr(t, "info", {}) or {}
    for k in ("regularMarketPrice", "previousClose"):
        if k in info:
            try:
                return float(info[k])
            except Exception:
                pass

    return np.nan

def read_int(prompt, default):
    s = input(prompt).strip()
    if not s:
        return default
    try:
        return max(0, int(s))
    except ValueError:
        return default

def option_cycle(d):
    if d.weekday() == 4 and 15 <= d.day <= 21:
        if d.month in (3, 6, 9, 12):
            return "quarterly"
        return "monthly"
    return "weekly"

def ticker_check(ticker):
    try:
        t = yf.Ticker(ticker)
        fast = getattr(t, "fast_info", {}) or {}
        if fast.get("last_price") or fast.get("last_trade_price"):
            return True
        if t.options:
            return True
    except Exception:
        pass
    return False

def main():
    ticker = input("enter ticker: ").strip().upper()
    if not ticker:
        print("ticker NF")
        return

    if not ticker_check(ticker):
        print("ticker NF")
        return

    min_dte = read_int("min days to expiration [1]: ", 1) #just because u can check right before expiry doesn't mean you should. as u can see it will likely contaminate the output
    max_dte = read_int("max days to expiration [180]: ", 180)
    if min_dte > max_dte:
        min_dte, max_dte = max_dte, min_dte

    stock = yf.Ticker(ticker)
    spot = get_current_price(stock)

    if np.isnan(spot):
        print("spot price unavailable")
        return

    expirations = stock.options or []
    if not expirations:
        print("no options available")
        return

    today = datetime.now(timezone.utc).date()
    records = []
    skipped = 0

    for e in expirations:
        try:
            d = datetime.strptime(e, "%Y-%m-%d").date()
        except Exception:
            continue

        dte = (d - today).days
        if not (min_dte <= dte <= max_dte):
            continue

        try:
            oc = stock.option_chain(e)
        except Exception:
            skipped += 1
            continue

        calls = filter_near_atm(oc.calls, spot)
        puts = filter_near_atm(oc.puts, spot)

        call_vol = safe_sum(calls, "volume")
        put_vol = safe_sum(puts, "volume")
        call_oi = safe_sum(calls, "openInterest")
        put_oi = safe_sum(puts, "openInterest")

        pc_vol = put_vol / call_vol if call_vol and not np.isnan(call_vol) else np.nan
        pc_oi = put_oi / call_oi if call_oi and not np.isnan(call_oi) else np.nan

        call_iv = nearest_iv(calls, spot)
        put_iv = nearest_iv(puts, spot)

        ivs = [v for v in (call_iv, put_iv) if not np.isnan(v)]
        atm_iv = float(np.mean(ivs)) if ivs else np.nan

        records.append({
            "expiration": e,
            "dte": dte,
            "cycle": option_cycle(d),
            "call_vol_atm": call_vol,
            "put_vol_atm": put_vol,
            "pc_vol_atm": pc_vol,
            "pc_oi_atm": pc_oi,
            "atm_iv_dec": atm_iv
        })

    if not records:
        print("valid option data NF")
        return

    df = pd.DataFrame(records).sort_values("dte")
    print(df.to_string(index=False))

    if skipped > 0:
        print(f"\nwarning: skipped {skipped} expirations (data unavailable)")

if __name__ == "__main__":
    main()
