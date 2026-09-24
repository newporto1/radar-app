"""Componentes de sinal, cada um inspirado num resultado publicado.
Todos devolvem um score por ativo em [-1, 1], calculado só com dados até t.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

BARS_PER_DAY = 6  # barras de 4h


def realized_vol(close: pd.DataFrame, days: int = 30) -> pd.DataFrame:
    r = close.pct_change(fill_method=None)
    bpy = 365 * BARS_PER_DAY
    return r.ewm(span=days * BARS_PER_DAY, min_periods=days * BARS_PER_DAY).std() * np.sqrt(bpy)


# 1) Ensemble de breakouts Donchian (Zarattini, Pagani & Barbon 2025; "Turtle" clássico)
def donchian_ensemble(high, low, close, lookbacks_days=(5, 10, 20, 30, 60, 90), long_short=True):
    scores = []
    for d in lookbacks_days:
        L = int(d * BARS_PER_DAY)
        up = high.rolling(L, min_periods=L).max().shift(1)
        dn = low.rolling(L, min_periods=L).min().shift(1)
        mid = (up + dn) / 2
        state = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
        state[close > up] = 1.0
        if long_short:
            state[close < dn] = -1.0
        # saída na linha média do canal (trailing)
        pos = state.copy()
        arr_c, arr_mid, arr_s = close.values, mid.values, state.values
        out = np.zeros_like(arr_c)
        cur = np.zeros(arr_c.shape[1])
        for i in range(arr_c.shape[0]):
            s = arr_s[i]
            cur = np.where(~np.isnan(s), s, cur)
            exit_long = (cur > 0) & (arr_c[i] < arr_mid[i])
            exit_short = (cur < 0) & (arr_c[i] > arr_mid[i])
            cur = np.where(exit_long | exit_short, 0.0, cur)
            cur = np.where(np.isnan(arr_c[i]) | np.isnan(arr_mid[i]), 0.0, cur)
            out[i] = cur
        scores.append(pd.DataFrame(out, index=close.index, columns=close.columns))
    return sum(scores) / len(scores)


# 2) Time-series momentum / cruzamento de EMAs (Moskowitz, Ooi & Pedersen 2012; estilo CTA)
def ema_trend_ensemble(close, pairs_days=((2, 8), (4, 16), (8, 32), (16, 64), (32, 128)), long_short=True):
    vol_px = close.pct_change(fill_method=None).ewm(span=30 * BARS_PER_DAY).std() * close
    scores = []
    for f, s in pairs_days:
        ef = close.ewm(span=f * BARS_PER_DAY, min_periods=s * BARS_PER_DAY).mean()
        es = close.ewm(span=s * BARS_PER_DAY, min_periods=s * BARS_PER_DAY).mean()
        x = (ef - es) / (vol_px * np.sqrt(s * BARS_PER_DAY))  # normalizado pela vol
        sc = np.tanh(x * 2)  # resposta contínua (forte tendência -> ±1)
        if not long_short:
            sc = sc.clip(lower=0)
        scores.append(sc)
    return (sum(scores) / len(scores)).fillna(0.0)


# 3) Momentum cross-sectional (Liu, Tsyvinski & Wu 2022) — neutro ao mercado
def xs_momentum(close, lookback_days=30, skip_days=1):
    L, S = lookback_days * BARS_PER_DAY, skip_days * BARS_PER_DAY
    vol = realized_vol(close)
    ret = close.shift(S) / close.shift(L) - 1
    x = ret / vol
    rk = x.rank(axis=1, pct=True)
    n = x.notna().sum(axis=1)
    sc = (rk.sub(rk.mean(axis=1), axis=0) * 2).where(n >= 4)
    return sc.fillna(0.0)


# 4) Reversão de curto prazo cross-sectional (efeito "reversal" semanal)
def xs_reversal(close, lookback_days=3):
    L = lookback_days * BARS_PER_DAY
    vol = realized_vol(close)
    x = (close / close.shift(L) - 1) / vol
    rk = x.rank(axis=1, pct=True)
    n = x.notna().sum(axis=1)
    sc = (-(rk.sub(rk.mean(axis=1), axis=0)) * 2).where(n >= 4)
    return sc.fillna(0.0)


def to_weights(score, close, asset_vol_target=0.10, cap=0.25, gross_max=1.0):
    """Volatility targeting por ativo, teto por ativo e sem alavancagem."""
    vol = realized_vol(close)
    w = score * (asset_vol_target / vol)
    w = w.clip(-cap, cap)
    w = w.where(close.notna() & vol.notna(), 0.0).fillna(0.0)
    g = w.abs().sum(axis=1)
    scale = (gross_max / g).where(g > gross_max, 1.0)
    return w.mul(scale, axis=0)
