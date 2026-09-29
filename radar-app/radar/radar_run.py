"""Radar v3 · universo largo — corre uma vez por dia, calcula a carteira-alvo e gera alertas.

Uso:  python radar_run.py --capital 1000 --prev prev_state.json --out new_state.json

Dados: velas 4h da Binance spot via API pública de dados de mercado (data-api.binance.vision,
sem chave). Se a API falhar, usa o dataset de 10 moedas (github.com/Speirsy11/crypto-dataset).

Universo (desde 2026-09-30): as 40 moedas com maior volume mediano diário em USDT nos últimos
30 dias (mínimo 5 M$/dia e ≥ 120 dias de histórico). Ficam de fora stablecoins, tokens
embrulhados (WBTC…) e tokens alavancados. Moedas em carteira continuam no universo enquanto
estiverem no top 50, para evitar entradas e saídas só por causa do volume.

Regras v3 (congeladas 2026-09-24): score = média(Donchian ensemble 5–90d, EMA ensemble 2/8–32/128d),
só long; só as 5 moedas do universo com score mais alto e score > 0,3 entram;
peso = score × 40% ÷ vol anual (30d); máx 40%/moeda; total ≤ 100%; sem alavancagem.
Alerta quando uma moeda passa de 0 para >0 (ABRIR), de >0 para 0 (FECHAR), ou quando a
diferença para a posição-alvo anterior é ≥ 5% do capital (AUMENTAR / REDUZIR).
"""
import argparse, io, json, time, datetime as dt
import numpy as np, pandas as pd, requests
import signals as S

API = "https://data-api.binance.vision/api/v3"
TOP, TOP_HOLD, MIN_USD, MIN_DAYS, CANDIDATES = 40, 50, 5e6, 120, 90
EXCLUDE = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "EUR", "AEUR", "EURI", "USDE", "PYUSD", "RLUSD",
           "USD1", "XUSD", "BFUSD", "USDS", "UST", "USTC", "PAXG", "XAUT", "WBTC", "WBETH", "BETH", "BNSOL",
           "GBP", "TRY", "BRL", "ARS", "JPY", "MXN", "PLN", "RON", "UAH", "ZAR", "COP", "IDRT", "BIDR"}

# fallback (dataset de 10 moedas, atualizado 1× por dia com ~1 dia de atraso)
FB_SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "TRXUSDT", "DOGEUSDT", "ZECUSDT", "ADAUSDT", "BCHUSDT"]
FB_BASE = "https://media.githubusercontent.com/media/Speirsy11/crypto-dataset/main/data/interval_id=4h"


def get(path, **params):
    for i in range(4):
        try:
            r = requests.get(f"{API}/{path}", params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (418, 429):
                time.sleep(5 * (i + 1))
                continue
            r.raise_for_status()
        except requests.RequestException:
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"Binance API falhou: {path} {params}")


def candidates(held):
    tick = get("ticker/24hr")
    rows = []
    for t in tick:
        s = t["symbol"]
        if not s.endswith("USDT"):
            continue
        base = s[:-4]
        if base in EXCLUDE or base.endswith(("UP", "DOWN", "BULL", "BEAR")) or float(t["lastPrice"]) <= 0:
            continue
        rows.append((s, float(t["quoteVolume"])))
    info = get("exchangeInfo", permissions="SPOT")
    trading = {x["symbol"] for x in info["symbols"] if x.get("status") == "TRADING"}
    rows = [r for r in rows if r[0] in trading]
    rows.sort(key=lambda r: -r[1])
    syms = [r[0] for r in rows[:CANDIDATES]]
    for h in held:  # moedas em carteira são sempre descarregadas
        if h + "USDT" not in syms and h + "USDT" in trading:
            syms.append(h + "USDT")
    return syms


def klines(sym, bars=1500):
    out, end = [], None
    while len(out) < bars:
        p = {"symbol": sym, "interval": "4h", "limit": 1000}
        if end:
            p["endTime"] = end
        k = get("klines", **p)
        if not k:
            break
        out = k + out
        end = k[0][0] - 1
        if len(k) < 1000:
            break
        time.sleep(0.1)
    df = pd.DataFrame(out).iloc[:, :8]
    df.columns = ["t", "open", "high", "low", "close", "vol", "tclose", "qvol"]
    now_ms = int(time.time() * 1000)
    df = df[df["tclose"] < now_ms]  # só velas fechadas
    df["t"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    return df.drop_duplicates("t").set_index("t").astype(float)


def load_binance(held):
    syms = candidates(held)
    cols = {k: {} for k in ["high", "low", "close", "qvol"]}
    for s in syms:
        try:
            df = klines(s)
        except RuntimeError:
            continue
        if len(df) < 200:
            continue
        for k in cols:
            cols[k][s] = df[k]
    D = {k: pd.DataFrame(v).sort_index() for k, v in cols.items()}
    for k in ("high", "low", "close"):
        D[k] = D[k].ffill(limit=6)
    return D


def fetch_fb(sym, y, m):
    for mm in (f"{m:02d}", str(m)):
        r = requests.get(f"{FB_BASE}/symbol_id={sym}/year={y}/month={mm}/{sym}-4h-{y}-{m:02d}.parquet", timeout=60)
        if r.status_code == 200 and r.content[:4] == b"PAR1":
            return pd.read_parquet(io.BytesIO(r.content))
    return None


def load_fallback(n_months=16):
    t = dt.date.today().replace(day=1)
    months = []
    for _ in range(n_months):
        months.append((t.year, t.month))
        t = (t - dt.timedelta(days=1)).replace(day=1)
    cols = {k: {} for k in ["high", "low", "close", "qvol"]}
    for s in FB_SYMS:
        parts = [d for d in (fetch_fb(s, y, m) for y, m in months[::-1]) if d is not None]
        df = pd.concat(parts).drop_duplicates("timestamp").set_index("timestamp").sort_index()
        for k in ("high", "low", "close"):
            cols[k][s] = df[k].astype(float)
        cols["qvol"][s] = (df["volume"] * df["close"]).astype(float)
    return {k: pd.DataFrame(v).sort_index().ffill() for k, v in cols.items()}


def universe(D, held):
    qv_day = D["qvol"].resample("1D").sum(min_count=1)
    med = qv_day.iloc[-31:-1].median()  # últimos 30 dias completos
    age = D["close"].notna().sum() / 6
    ok = (med >= MIN_USD) & (age >= MIN_DAYS)
    rk = med.where(ok).rank(ascending=False)
    uni = set(rk[rk <= TOP].index)
    for h in held:
        s = h + "USDT"
        if s in rk.index and rk.get(s, np.inf) <= TOP_HOLD:
            uni.add(s)
    return sorted(uni), med


def compute(capital, held):
    source = "binance"
    try:
        D = load_binance(held)
        if D["close"].shape[1] < 20:
            raise RuntimeError("poucas moedas")
        uni, med = universe(D, held)
    except Exception as e:  # noqa: BLE001
        print("Aviso: Binance indisponível, a usar dataset de 10 moedas:", e)
        source = "fallback-10"
        D = load_fallback()
        uni, med = list(D["close"].columns), None
    H, L, C = D["high"][uni], D["low"][uni], D["close"][uni]
    score = (S.donchian_ensemble(H, L, C, long_short=False) + S.ema_trend_ensemble(C, long_short=False)) / 2
    rk = score.rank(axis=1, ascending=False)
    top = score.where((rk <= 5) & (score > 0.3), 0)
    w = S.to_weights(top, C, asset_vol_target=0.40, cap=0.40)
    t = w.index[-1]
    last_w, last_s = w.iloc[-1], score.iloc[-1]
    # mostrar: posições + as 10 tendências mais fortes + moedas em carteira que saíram
    show = set(last_w[last_w > 0].index) | set(last_s.sort_values(ascending=False).index[:10]) | {h + "USDT" for h in held if h + "USDT" in C.columns}
    coins = []
    for s in sorted(show, key=lambda x: (-last_w.get(x, 0), -np.nan_to_num(last_s.get(x, 0)))):
        c = C[s].dropna()
        coins.append({"sym": s[:-4], "price": float(c.iloc[-1]), "score": round(float(np.nan_to_num(last_s[s])), 3),
                      "weight": round(float(last_w[s]), 4), "eur": round(float(last_w[s]) * capital, 2),
                      "chg7d": round(float(c.iloc[-1] / c.iloc[-43] - 1), 4) if len(c) > 43 else 0.0})
    return {"version": "v3 · top 40", "source": source, "universe_size": len(uni), "universe": [u[:-4] for u in uni],
            "as_of": t.isoformat(), "generated": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "capital": capital, "invested": round(float(last_w.sum()), 4), "coins": coins}


def diff(prev, new, capital, band=0.05):
    alerts = []
    pw = {c["sym"]: c["weight"] for c in (prev or {}).get("coins", [])}
    nw = {c["sym"]: c for c in new["coins"]}
    for sym in sorted(set(pw) | set(nw)):
        a = pw.get(sym, 0.0)
        c = nw.get(sym)
        b = c["weight"] if c else 0.0
        typ = None
        if a < 0.005 <= b:
            typ = "ABRIR"
        elif a >= 0.005 > b:
            typ = "FECHAR"
        elif abs(b - a) >= band:
            typ = "AUMENTAR" if b > a else "REDUZIR"
        if typ:
            alerts.append({"type": typ, "sym": sym, "from_eur": round(a * capital, 2), "to_eur": round(b * capital, 2),
                           "delta_eur": round((b - a) * capital, 2), "price": c["price"] if c else None,
                           "score": c["score"] if c else None, "as_of": new["as_of"], "done": False})
    return alerts


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=1000)
    ap.add_argument("--prev", default=None)
    ap.add_argument("--out", default="new_state.json")
    a = ap.parse_args()
    prev = json.load(open(a.prev)) if a.prev else None
    held = [c["sym"] for c in (prev or {}).get("coins", []) if c.get("weight", 0) >= 0.005]
    new = compute(a.capital, held)
    if prev and prev.get("as_of") == new["as_of"]:
        new["stale"] = True  # sem velas novas desde a última corrida
    if prev and new["source"] != "binance" and prev.get("source") == "binance":
        new["stale"] = True  # API falhou hoje: não gerar FECHAR falsos para moedas fora das 10 do fallback
    alerts = diff(prev, new, a.capital) if not new.get("stale") else []
    json.dump({"state": new, "alerts": alerts}, open(a.out, "w"), indent=1)
    print(json.dumps({"as_of": new["as_of"], "source": new["source"], "universe": new["universe_size"],
                      "invested": new["invested"], "alerts": alerts}, indent=1))
