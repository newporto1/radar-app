"""Corrida diária: executa o Radar, atualiza docs/data/*.json e envia notificação (ntfy).

Variáveis de ambiente (opcionais):
  CAPITAL      capital em € (por omissão 1000)
  NTFY_TOPIC   tópico ntfy.sh para receber notificações no telemóvel
  APP_URL      link da app, incluído na notificação
"""
import json, os, subprocess, sys, pathlib, requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
STATE, ALERTS, NEW = DATA / "state.json", DATA / "alerts.json", ROOT / "radar" / "new_state.json"
CAPITAL = os.environ.get("CAPITAL", "1000")


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

    STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False))
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
        notify(f"Radar: {len(alerts)} alerta(s)", body, "rotating_light")
        print(f"Radar: {len(alerts)} alerta(s)\n{body}")
    else:
        msg = f"Sem alterações. Investido {state['invested']*100:.0f}% (dados até {day})."
        if os.environ.get("NOTIFY_QUIET", "0") == "1":
            notify("Radar", msg, "white_check_mark")
        print("Radar: " + msg)


if __name__ == "__main__":
    main()
