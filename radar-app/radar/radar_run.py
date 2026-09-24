"""Radar v3 — corre uma vez por dia, calcula a carteira-alvo e gera alertas.

Uso:  python radar_run.py --capital 1000 --prev prev_state.json --out new_state.json
Dados: velas 4h da Binance spot (github.com/Speirsy11/crypto-dataset, atualizado diariamente).
Regras v3 (congeladas 2026-09-24): score = média(Donchian ensemble 5–90d, EMA ensemble 2/8–32/128d), só long;
só as 5 moedas com score mais alto e score > 0,3 entram; peso = score × 40% ÷ vol anual (30d);
máx 40%/moeda; total ≤ 100%; sem alavancagem.
Alerta quando uma moeda passa de 0 para >0 (ABRIR), de >0 para 0 (FECHAR), ou quando a
diferença para a posição-alvo anterior é ≥ 5% do capital (AUMENTAR / REDUZIR).
"""
import argparse, io, json, datetime as dt
import numpy as np, pandas as pd, requests
import signals as S

SYMS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "TRXUSDT", "DOGEUSDT", "ZECUSDT", "ADAUSDT", "BCHUSDT"]
BASE = "https://media.githubusercontent.com/media/Speirsy11/crypto-dataset/main/data/interval_id=4h"
MANIFEST = "https://raw.githubusercontent.com/Speirsy11/crypto-dataset/main/metadata/manifest.json"


def months_back(n):
    t = dt.date.today().replace(day=1)
    out = []
    for _ in range(n):
        out.append((t.year, t.month))
        t = (t - dt.timedelta(days=1)).replace(day=1)
    return out[::-1]


def fetch(sym, y, m):
    for mm in (f"{m:02d}", str(m)):
        r = requests.get(f"{BASE}/symbol_id={sym}/year={y}/month={mm}/{sym}-4h-{y}-{m:02d}.parquet", timeout=60)
        if r.status_code == 200 and r.content[:4] == b"PAR1":
            return pd.read_parquet(io.BytesIO(r.content))
    return None


def load(n_months=16):
    cols = {k: {} for k in ["high", "low", "close"]}
    for s in SYMS:
        parts = [d for d in (fetch(s, y, m) for y, m in months_back(n_months)) if d is not None]
        df = pd.concat(parts).drop_duplicates("timestamp").set_index("timestamp").sort_index()
        for k in cols:
            cols[k][s] = df[k].astype(float)
    return {k: pd.DataFrame(v).sort_index().ffill() for k, v in cols.items()}


def compute(capital):
    D = load()
    H, L, C = D["high"], D["low"], D["close"]
    score = (S.donchian_ensemble(H, L, C, long_short=False) + S.ema_trend_ensemble(C, long_short=False)) / 2
    rk = score.rank(axis=1, ascending=False)
    top = score.where((rk <= 5) & (score > 0.3), 0)
    w = S.to_weights(top, C, asset_vol_target=0.40, cap=0.40)
    t = w.index[-1]
    coins = []
    for s in SYMS:
        coins.append({"sym": s.replace("USDT", ""), "price": float(C[s].iloc[-1]), "score": round(float(score[s].iloc[-1]), 3),
                      "weight": round(float(w[s].iloc[-1]), 4), "eur": round(float(w[s].iloc[-1]) * capital, 2),
                      "chg7d": round(float(C[s].iloc[-1] / C[s].iloc[-43] - 1), 4)})
    # equity curve dos últimos 90 dias da estratégia (informativo)
    return {"version": "v3", "as_of": t.isoformat(), "generated": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "capital": capital, "invested": round(float(w.iloc[-1].sum()), 4), "coins": coins}


def diff(prev, new, capital, band=0.05):
    alerts = []
    pw = {c["sym"]: c["weight"] for c in (prev or {}).get("coins", [])}
    for c in new["coins"]:
        a, b = pw.get(c["sym"], 0.0), c["weight"]
        typ = None
        if a < 0.005 <= b:
            typ = "ABRIR"
        elif a >= 0.005 > b:
            typ = "FECHAR"
        elif abs(b - a) >= band:
            typ = "AUMENTAR" if b > a else "REDUZIR"
        if typ:
            alerts.append({"type": typ, "sym": c["sym"], "from_eur": round(a * capital, 2), "to_eur": round(b * capital, 2),
                           "delta_eur": round((b - a) * capital, 2), "price": c["price"], "score": c["score"],
                           "as_of": new["as_of"], "done": False})
    return alerts


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=1000)
    ap.add_argument("--prev", default=None)
    ap.add_argument("--out", default="new_state.json")
    a = ap.parse_args()
    prev = json.load(open(a.prev)) if a.prev else None
    new = compute(a.capital)
    if prev and prev.get("as_of") == new["as_of"]:
        new["stale"] = True  # o dataset ainda não atualizou desde a última corrida
    alerts = diff(prev, new, a.capital) if not new.get("stale") else []
    json.dump({"state": new, "alerts": alerts}, open(a.out, "w"), indent=1)
    print(json.dumps({"as_of": new["as_of"], "invested": new["invested"], "alerts": alerts}, indent=1))
