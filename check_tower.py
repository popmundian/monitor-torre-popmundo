import os
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
FIRE_MARKER = "alerta da Torre Infernal"
STATE_FILE  = Path("state.json")
BRT         = timezone(timedelta(hours=-3))  # Horário de Brasília

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}


# ─── Estado persistido ────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {
        "active": False,
        "started_at": None,      # ISO string BRT
        "last_ended_at": None,   # ISO string BRT
        "last_duration_min": None
    }

def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def now_brt() -> datetime:
    return datetime.now(BRT)

def fmt(iso: str) -> str:
    """Formata ISO string para exibição amigável."""
    dt = datetime.fromisoformat(iso)
    return dt.strftime("%d/%m às %H:%M")


# ─── Telegram ─────────────────────────────────────────────────────────────────

def send_telegram(message: str):
    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    requests.post(url, json=payload, timeout=10).raise_for_status()
    print("✅ Telegram enviado!")


# ─── ASP.NET helpers ──────────────────────────────────────────────────────────

def hidden_fields(soup: BeautifulSoup) -> dict:
    return {t["name"]: t.get("value", "")
            for t in soup.find_all("input", {"type": "hidden"}) if t.get("name")}

def detect_page(soup: BeautifulSoup, url: str) -> str:
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

def try_server(server: str) -> bool | None:
    """
    Loga, seleciona personagem e verifica a torre num servidor.
    Retorna True (torre ativa), False (torre inativa) ou None (personagem não encontrado).
    """
    base_url        = f"https://{server}.popmundo.com"
    char_select_url = f"{base_url}/World/Popmundo.aspx/ChooseCharacter"
    tower_url       = f"{base_url}/World/Popmundo.aspx/City/ToweringInferno"
    print(f"\n🌐 Tentando servidor {server}...")

    with requests.Session() as s:
        # ── Etapa 1: navegar → redireciona pro login ──
        resp = s.get(char_select_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        page = detect_page(soup, resp.url)
        print(f"   Página inicial: {page}")

        # ── Etapa 2: login ──
        if page == "login":
            login_url = resp.url
            payload   = {
                **hidden_fields(soup),
                "ctl00$cphRightColumn$ucLogin$txtUsername": POPMUNDO_USER,
                "ctl00$cphRightColumn$ucLogin$txtPassword": POPMUNDO_PASS,
                "ctl00$cphRightColumn$ucLogin$ddlStatus":   "0",
                "ctl00$cphRightColumn$ucLogin$btnLogin":    "Entrar",
                "__EVENTTARGET": "", "__EVENTARGUMENT": "",
            }
            print("🔐 Fazendo login...")
            resp = s.post(login_url, data=payload, headers={
                **HEADERS, "Content-Type": "application/x-www-form-urlencoded",
                "Referer": login_url,
            }, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            page = detect_page(soup, resp.url)
            print(f"   Página após login: {page}")

        if page in ("already_logged", "char_main"):
            print("   Sessão já ativa!")
        elif page == "char_select":
            # ── Etapa 3: selecionar personagem ──
            print(f"🎭 Procurando '{POPMUNDO_CHARNAME}'...")
            buttons = soup.find_all("input", {"type": "submit"})
            btn     = next((b for b in buttons
                            if POPMUNDO_CHARNAME.lower() in b.get("value", "").lower()), None)
            if not btn:
                print("   Não encontrado aqui. Pulando...")
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
                **HEADERS, "Content-Type": "application/x-www-form-urlencoded",
                "Referer": char_select_url,
            }, timeout=15)
            resp.raise_for_status()
            final_page = detect_page(BeautifulSoup(resp.text, "html.parser"), resp.url)
            print(f"   Resultado: {final_page}")
            if final_page not in ("char_main", "already_logged"):
                print("   ⚠️ Não confirmado. Pulando...")
                return None
        else:
            print(f"   ⚠️ Página inesperada: {page}. Pulando...")
            return None

        # ── Etapa 4: verificar torre ──
        print("🔍 Verificando Torre Infernal...")
        resp = s.get(tower_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        active = FIRE_MARKER in resp.text
        print(f"   Torre {'🔥 ATIVA' if active else '🏰 inativa'}")
        return active


# ─── Lógica de estado e notificações ─────────────────────────────────────────

def process_result(tower_active: bool, tower_url: str):
    state = load_state()
    now   = now_brt()
    now_s = now.isoformat()

    was_active = state.get("active", False)

    if tower_active and not was_active:
        # ── Torre ACABOU DE ACENDER ──
        state["active"]     = True
        state["started_at"] = now_s

        ultimo = ""
        if state.get("last_ended_at") and state.get("last_duration_min") is not None:
            ultimo = (f"\n\n🕐 Última torre: {fmt(state['last_ended_at'])} "
                      f"({state['last_duration_min']} min de duração)")

        msg = (
            f"🔥 <b>TORRE INFERNAL EM CHAMAS!</b>\n\n"
            f"⏰ Iniciou às <b>{now.strftime('%H:%M')}</b>{ultimo}\n\n"
            f"👉 <a href='{tower_url}'>Clique aqui para entrar</a>"
        )
        send_telegram(msg)
        print("📨 Notificação de INÍCIO enviada.")

    elif not tower_active and was_active:
        # ── Torre ACABOU DE APAGAR ──
        started = datetime.fromisoformat(state["started_at"]) if state.get("started_at") else None
        duration_min = int((now - started).total_seconds() / 60) if started else "?"

        state["active"]           = False
        state["last_ended_at"]    = now_s
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
    tower_active = None
    tower_url    = None

    for server in SERVERS:
        result = try_server(server)
        if result is not None:
            tower_active = result
            tower_url    = f"https://{server}.popmundo.com/World/Popmundo.aspx/City/ToweringInferno"
            print(f"\n✅ Personagem encontrado no servidor {server}.")
            break

    if tower_active is None:
        raise RuntimeError(
            f"❌ Personagem '{POPMUNDO_CHARNAME}' não encontrado em nenhum servidor."
        )

    process_result(tower_active, tower_url)


if __name__ == "__main__":
    main()
