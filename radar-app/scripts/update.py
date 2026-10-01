"""Corrida diária: executa o Radar, atualiza docs/data/*.json e envia notificação (ntfy).

Variáveis de ambiente (opcionais):
  CAPITAL      capital em € (por omissão 1000)
  NTFY_TOPIC   tópico ntfy.sh para receber notificações no telemóvel
  APP_URL      link da app, incluído na notificação
"""
import json, os, subprocess, sys, pathlib, requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
STATE, ALERTS, PERF, NEW = DATA / "state.json", DATA / "alerts.json", DATA / "perf.json", ROOT / "radar" / "new_state.json"
FEE = 0.001  # comissão spot por lado usada na carteira modelo
CAPITAL = os.environ.get("CAPITAL", "1000")
PAPER = os.environ.get("PAPER_MODE", "0") == "1"  # modo simulação: alertas não são para executar


def eur(x):
    return f"{abs(x):,.0f} €".replace(",", " ")


def usd(x):
    return f"{x:,.2f} $".replace(",", " ") if x < 1000 else f"{x:,.0f} $".replace(",", " ")


def line(a):
    verb = "comprar" if a["delta_eur"] > 0 else "vender"
    s = f"{a['type']} {a['sym']}: {verb} ~{eur(a['delta_eur'])}"
    return s + (f" (preço ~{usd(a['price'])})" if a["type"] == "ABRIR" else "")


def notify(title, body, tags):
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        print("NTFY_TOPIC não definido — sem notificação.")
        return
    headers = {"Title": title.encode("utf-8"), "Tags": tags, "Priority": "high" if tags == "rotating_light" else "default"}
    if os.environ.get("APP_URL"):
        headers["Click"] = os.environ["APP_URL"]
    requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), headers=headers, timeout=30)


def update_perf(state, perf=None):
    """Carteira modelo: segue os alertas à risca (comissão 0,1%/lado) para medir o resultado real do Radar."""
    if perf is None:
        perf = json.loads(PERF.read_text()) if PERF.exists() else None
    cap = float(state["capital"])
    if perf is None:
        perf = {"start": state["as_of"], "capital": cap, "cash": cap, "units": {}, "last_px": {}, "fees": 0.0, "history": []}
    if perf.get("last_as_of") == state["as_of"]:
        return perf
    px = dict(perf["last_px"])
    px.update({c["sym"]: c["price"] for c in state["coins"]})
    held_val = {s: u * px[s] for s, u in perf["units"].items() if s in px}
    eq = perf["cash"] + sum(held_val.values())
    target = {c["sym"]: c["weight"] * eq for c in state["coins"] if c["weight"] > 0}
    turnover = sum(abs(target.get(s, 0) - held_val.get(s, 0)) for s in set(target) | set(held_val))
    fee = turnover * FEE
    eq_after = eq - fee
    k = eq_after / eq if eq > 0 else 1
    perf["units"] = {s: v * k / px[s] for s, v in target.items()}
    perf["cash"] = eq_after - sum(v * k for v in target.values())
    perf["fees"] = round(perf["fees"] + fee, 2)
    perf["last_px"] = px
    perf["last_as_of"] = state["as_of"]
    perf["equity"] = round(eq_after, 2)
    perf["history"].append({"t": state["as_of"], "equity": round(eq_after, 2), "turnover": round(turnover, 2)})
    return perf


def main():
    prev = STATE if STATE.exists() else None
    cmd = [sys.executable, "radar_run.py", "--capital", CAPITAL, "--out", str(NEW)] + (["--prev", str(prev)] if prev else [])
    subprocess.run(cmd, cwd=ROOT / "radar", check=True)
    out = json.loads(NEW.read_text())
    state, alerts = out["state"], out["alerts"]
    NEW.unlink()

    if state.get("stale"):
        print("Radar: sem dados novos hoje.")
        return

    state["paper"] = PAPER
    STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False))
    PERF.write_text(json.dumps(update_perf(state), indent=1, ensure_ascii=False))
    hist = json.loads(ALERTS.read_text()) if ALERTS.exists() else []
    ids = {h["id"] for h in hist}
    for a in alerts:
        a["id"] = f"{a['as_of'][:10]}_{a['sym']}_{a['type']}"
        if a["id"] not in ids:
            hist.append(a)
    ALERTS.write_text(json.dumps(hist, indent=1, ensure_ascii=False))

    day = state["as_of"][:10]
    if alerts:
        body = "\n".join(line(a) for a in alerts)
        perf = json.loads(PERF.read_text()) if PERF.exists() else None
        if PAPER:
            pl = f"\nCarteira modelo: {perf['equity']:.0f} € ({(perf['equity']/perf['capital']-1)*100:+.1f}%)" if perf else ""
            notify(f"Radar SIMULAÇÃO: {len(alerts)} alerta(s) — não executar", body + pl, "test_tube")
        else:
            notify(f"Radar: {len(alerts)} alerta(s)", body, "rotating_light")
        print(f"Radar: {len(alerts)} alerta(s)\n{body}")
    else:
        msg = f"Sem alterações. Investido {state['invested']*100:.0f}% (dados até {day})."
        if os.environ.get("NOTIFY_QUIET", "0") == "1":
            notify("Radar", msg, "white_check_mark")
        print("Radar: " + msg)


if __name__ == "__main__":
    main()
