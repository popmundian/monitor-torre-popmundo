import os
import re
import json
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path
from bs4 import BeautifulSoup

# ─── Configurações ─────────────────────────────────────────────────────────────
POPMUNDO_USER     = os.environ["POPMUNDO_USER"]
POPMUNDO_PASS     = os.environ["POPMUNDO_PASS"]
POPMUNDO_CHARNAME = os.environ["POPMUNDO_CHARNAME"]
TELEGRAM_TOKEN    = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID  = os.environ["TELEGRAM_CHAT_ID"]

SERVERS     = ["73", "74", "75"]
FIRE_MARKER = "imgFire"
STATE_FILE  = Path("state.json")
BRT         = timezone(timedelta(hours=-3))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

print("=== Monitor Torre Infernal iniciado ===")

# ─── Estado ───────────────────────────────────────────────────────────────────

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"active": False, "started_at": None,
            "last_ended_at": None, "last_duration_min": None}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def now_brt():
    return datetime.now(BRT)

def fmt(iso):
    return datetime.fromisoformat(iso).strftime("%d/%m às %H:%M")


# ─── Telegram ─────────────────────────────────────────────────────────────────

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    requests.post(url, json=payload, timeout=10).raise_for_status()
    print("✅ Telegram enviado!")


# ─── ASP.NET helpers ──────────────────────────────────────────────────────────

def hidden_fields(soup):
    return {t["name"]: t.get("value", "")
            for t in soup.find_all("input", {"type": "hidden"}) if t.get("name")}

def detect_page(soup, url):
    if soup.find("select", id=lambda x: x and x.endswith("ucCharacterBar_ddlCurrentCharacter")):
        return "already_logged"
    if "/Popmundo.aspx/Character" in url and "ChooseCharacter" not in url:
        return "char_main"
    if "ChooseCharacter" in url or soup.find("form", action=lambda x: x and "ChooseCharacter" in x):
        return "char_select"
    if soup.find(id="ctl00_cphRightColumn_ucLogin_txtUsername"):
        return "login"
    return "unknown"


# ─── Fluxo por servidor ───────────────────────────────────────────────────────

def try_server(server):
    base_url        = f"https://{server}.popmundo.com"
    char_select_url = f"{base_url}/World/Popmundo.aspx/ChooseCharacter"
    tower_url       = f"{base_url}/World/Popmundo.aspx/City/ToweringInferno"

    print(f"\n🌐 Tentando servidor {server}...")

    with requests.Session() as s:
        # Etapa 1: navegar → redireciona pro login
        resp = s.get(char_select_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        page = detect_page(soup, resp.url)
        print(f"   Página inicial: {page}")

        # Etapa 2: login
        if page == "login":
            login_url = resp.url
            payload = {
                **hidden_fields(soup),
                "ctl00$cphRightColumn$ucLogin$txtUsername": POPMUNDO_USER,
                "ctl00$cphRightColumn$ucLogin$txtPassword": POPMUNDO_PASS,
                "ctl00$cphRightColumn$ucLogin$ddlStatus":   "0",
                "ctl00$cphRightColumn$ucLogin$btnLogin":    "Entrar",
                "__EVENTTARGET": "", "__EVENTARGUMENT": "",
            }
            print("   🔐 Fazendo login...")
            resp = s.post(login_url, data=payload, headers={
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": login_url,
            }, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            page = detect_page(soup, resp.url)
            print(f"   Página após login: {page}")

        # Etapa 3: selecionar personagem
        if page in ("already_logged", "char_main"):
            print("   Sessão já ativa!")

        elif page == "char_select":
            print(f"   🎭 Procurando '{POPMUNDO_CHARNAME}'...")
            buttons = soup.find_all("input", {"type": "submit"})
            btn = next((b for b in buttons
                        if POPMUNDO_CHARNAME.lower() in b.get("value", "").lower()), None)

            if not btn:
                print("   Personagem não encontrado aqui. Pulando...")
                return None

            form   = soup.find("form")
            action = form.get("action", "")
            action = char_select_url if action.startswith("http") else \
                     base_url + "/World/Popmundo.aspx/" + action.split("/")[-1]

            payload = {
                **hidden_fields(soup),
                btn["name"]: btn["value"],
                "__EVENTTARGET": "", "__EVENTARGUMENT": "",
            }
            print(f"   Selecionando '{btn['value']}'...")
            resp = s.post(action, data=payload, headers={
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": char_select_url,
            }, timeout=15)
            resp.raise_for_status()
            final_page = detect_page(BeautifulSoup(resp.text, "html.parser"), resp.url)
            print(f"   Resultado: {final_page}")

            if final_page in ("login", "char_select"):
                print("   ⚠️ Ainda na tela de login/seleção. Pulando...")
                return None

        else:
            print(f"   ⚠️ Página inesperada: {page}. Pulando...")
            return None

        # Etapa 4: verificar torre
        print(f"   🔍 Verificando torre em {tower_url}...")
        resp = s.get(tower_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text

        # Detecta se a sessão foi perdida (redirecionou para logout/login)
        if "logout=true" in resp.url or "Default.aspx" in resp.url:
            print(f"   ⚠️ Sessão perdida após seleção (redirecionou para {resp.url}). Pulando...")
            return None

        print(f"   URL final: {resp.url}")
        active = FIRE_MARKER in html
        print(f"   Torre: {'🔥 ATIVA' if active else '🏰 inativa'}")
        return active, html


# ─── Notificações ─────────────────────────────────────────────────────────────

def process_result(tower_active, tower_html):
    state = load_state()
    now   = now_brt()
    now_s = now.isoformat()
    was_active = state.get("active", False)

    if tower_active and not was_active:
        state["active"]     = True
        state["started_at"] = now_s

        game_start = ""
        m = re.search(r'começou em.*?>(\d{2}/\d{2}/\d{4},\s*\d{2}:\d{2})<', tower_html)
        if m:
            game_start = f"\n🎮 Início no jogo: <b>{m.group(1)}</b>"

        ultimo = ""
        if state.get("last_ended_at") and state.get("last_duration_min") is not None:
            ultimo = (f"\n🕐 Última torre: {fmt(state['last_ended_at'])} "
                      f"({state['last_duration_min']} min de duração)")

        msg = (
            f"🔥 <b>TORRE INFERNAL EM CHAMAS!</b>\n\n"
            f"⏰ Detectada às <b>{now.strftime('%H:%M')}</b>{game_start}{ultimo}\n\n"
            f"Corre lá no Popmundo!"
        )
        send_telegram(msg)
        print("📨 Notificação de INÍCIO enviada.")

    elif not tower_active and was_active:
        started      = datetime.fromisoformat(state["started_at"]) if state.get("started_at") else None
        duration_min = int((now - started).total_seconds() / 60) if started else "?"
        state["active"]            = False
        state["last_ended_at"]     = now_s
        state["last_duration_min"] = duration_min

        inicio = f" (iniciou às {fmt(state['started_at'])})" if state.get("started_at") else ""
        msg = (
            f"✅ <b>Torre Infernal apagada!</b>\n\n"
            f"⏱ Durou <b>{duration_min} minutos</b>{inicio}\n"
            f"🕐 Encerrou às <b>{now.strftime('%H:%M')}</b>"
        )
        send_telegram(msg)
        print("📨 Notificação de ENCERRAMENTO enviada.")

    elif tower_active and was_active:
        started = datetime.fromisoformat(state["started_at"]) if state.get("started_at") else None
        elapsed = int((now - started).total_seconds() / 60) if started else "?"
        print(f"🔥 Torre ainda ativa (há ~{elapsed} min). Sem nova notificação.")

    else:
        print("🏰 Torre continua inativa. Nenhuma ação.")

    save_state(state)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    for server in SERVERS:
        result = try_server(server)
        if result is None:
            continue
        tower_active, tower_html = result
        print(f"✅ Personagem confirmado no servidor {server}.")
        process_result(tower_active, tower_html)
        print("\n=== Verificação concluída ===")
        return

    raise RuntimeError(
        f"❌ Personagem '{POPMUNDO_CHARNAME}' não encontrado em nenhum servidor "
        f"({', '.join(SERVERS)}). Verifique o nome no Secret POPMUNDO_CHARNAME."
    )


if __name__ == "__main__":
    main()
