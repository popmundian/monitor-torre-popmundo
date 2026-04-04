import os
import requests
from bs4 import BeautifulSoup

# ─── Configurações (lidas dos GitHub Secrets) ──────────────────────────────────
POPMUNDO_USER     = os.environ["POPMUNDO_USER"]
POPMUNDO_PASS     = os.environ["POPMUNDO_PASS"]
POPMUNDO_CHARNAME = os.environ["POPMUNDO_CHARNAME"]
TELEGRAM_TOKEN    = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID  = os.environ["TELEGRAM_CHAT_ID"]

# Tenta os 3 servidores possíveis automaticamente
SERVERS = ["73", "74", "75"]

FIRE_MARKER = "alerta da Torre Infernal"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}


# ─── Telegram ─────────────────────────────────────────────────────────────────

def send_telegram(message: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    resp = requests.post(url, json=payload, timeout=10)
    resp.raise_for_status()
    print("✅ Mensagem enviada ao Telegram!")


# ─── Helpers ASP.NET ──────────────────────────────────────────────────────────

def extract_hidden_fields(soup: BeautifulSoup) -> dict:
    fields = {}
    for tag in soup.find_all("input", {"type": "hidden"}):
        name = tag.get("name")
        if name:
            fields[name] = tag.get("value", "")
    return fields


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

def try_server(server: str) -> str | None:
    """
    Tenta logar e selecionar o personagem num servidor.
    Retorna a URL base do servidor se encontrou o personagem, ou None se não encontrou.
    """
    base_url        = f"https://{server}.popmundo.com"
    char_select_url = f"{base_url}/World/Popmundo.aspx/ChooseCharacter"
    print(f"\n🌐 Tentando servidor {server}...")

    with requests.Session() as session:
        # ── Etapa 1: navegar → redireciona pro login ──
        resp = session.get(char_select_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        page = detect_page(soup, resp.url)
        print(f"   Página inicial: {page}")

        # ── Etapa 2: login se necessário ──
        if page == "login":
            hidden   = extract_hidden_fields(soup)
            login_url = resp.url
            payload  = {
                **hidden,
                "ctl00$cphRightColumn$ucLogin$txtUsername": POPMUNDO_USER,
                "ctl00$cphRightColumn$ucLogin$txtPassword": POPMUNDO_PASS,
                "ctl00$cphRightColumn$ucLogin$ddlStatus":   "0",
                "ctl00$cphRightColumn$ucLogin$btnLogin":    "Entrar",
                "__EVENTTARGET":   "",
                "__EVENTARGUMENT": "",
            }
            print("🔐 Fazendo login...")
            resp = session.post(login_url, data=payload, headers={
                **HEADERS,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": login_url,
            }, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            page = detect_page(soup, resp.url)
            print(f"   Página após login: {page}")

        if page in ("already_logged", "char_main"):
            # Sessão já ativa, pula direto pra verificação da torre
            print("   Sessão já ativa neste servidor!")
            return base_url

        if page != "char_select":
            print(f"   ⚠️ Página inesperada ({page}), pulando servidor.")
            return None

        # ── Etapa 3: selecionar personagem ──
        print(f"🎭 Procurando personagem '{POPMUNDO_CHARNAME}'...")
        buttons = soup.find_all("input", {"type": "submit"})
        btn = next(
            (b for b in buttons if POPMUNDO_CHARNAME.lower() in b.get("value", "").lower()),
            None
        )

        if not btn:
            print(f"   Personagem não encontrado neste servidor. Pulando...")
            return None  # ← tenta o próximo servidor

        form   = soup.find("form")
        action = form.get("action", char_select_url)
        if not action.startswith("http"):
            action = base_url + "/" + action.lstrip("/")

        payload = {
            **extract_hidden_fields(soup),
            btn["name"]: btn["value"],
            "__EVENTTARGET":   "",
            "__EVENTARGUMENT": "",
        }

        print(f"   Selecionando '{btn['value']}'...")
        resp = session.post(action, data=payload, headers={
            **HEADERS,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": char_select_url,
        }, timeout=15)
        resp.raise_for_status()
        final_soup = BeautifulSoup(resp.text, "html.parser")
        final_page = detect_page(final_soup, resp.url)
        print(f"   Resultado: {final_page}")

        if final_page not in ("char_main", "already_logged"):
            print("   ⚠️ Não foi possível confirmar acesso ao personagem.")
            return None

        # ── Etapa 4: verificar a torre (dentro da mesma sessão!) ──
        tower_url = f"{base_url}/World/Popmundo.aspx/City/ToweringInferno"
        print(f"🔍 Verificando Torre Infernal no servidor {server}...")
        resp = session.get(tower_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()

        if FIRE_MARKER in resp.text:
            print("🔥 TORRE INFERNAL ATIVA!")
            send_telegram(
                f"🔥 <b>TORRE INFERNAL EM CHAMAS!</b>\n\n"
                f"Uma aventura está disponível agora no Popmundo!\n"
                f"👉 <a href='{tower_url}'>Clique aqui para entrar</a>"
            )
        else:
            print("🏰 Torre tranquila.")

        return base_url  # personagem encontrado, não precisa tentar outros servidores


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    for server in SERVERS:
        result = try_server(server)
        if result is not None:
            print(f"\n✅ Personagem encontrado e verificado no servidor {server}.")
            return

    # Se chegou aqui, não achou o personagem em nenhum servidor
    raise RuntimeError(
        f"❌ Personagem '{POPMUNDO_CHARNAME}' não encontrado em nenhum servidor "
        f"({', '.join(SERVERS)}). Verifique o nome no Secret."
    )


if __name__ == "__main__":
    main()
