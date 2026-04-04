import os
import requests
from bs4 import BeautifulSoup

# ─── Configurações (lidas dos GitHub Secrets) ──────────────────────────────────
POPMUNDO_SERVER   = os.environ["POPMUNDO_SERVER"]   # ex: "73" → 73.popmundo.com
POPMUNDO_USER     = os.environ["POPMUNDO_USER"]
POPMUNDO_PASS     = os.environ["POPMUNDO_PASS"]
POPMUNDO_CHARNAME = os.environ["POPMUNDO_CHARNAME"]  # nome do seu personagem
TELEGRAM_TOKEN    = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID  = os.environ["TELEGRAM_CHAT_ID"]

BASE_URL         = f"https://{POPMUNDO_SERVER}.popmundo.com"
CHAR_SELECT_URL  = f"{BASE_URL}/World/Popmundo.aspx/ChooseCharacter"
TOWER_URL        = f"{BASE_URL}/World/Popmundo.aspx/City/ToweringInferno"

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
    """Extrai todos os campos hidden do formulário ASP.NET (ViewState etc.)."""
    fields = {}
    for tag in soup.find_all("input", {"type": "hidden"}):
        name = tag.get("name")
        if name:
            fields[name] = tag.get("value", "")
    return fields


def detect_page(soup: BeautifulSoup, url: str) -> str:
    """
    Identifica em qual etapa do fluxo estamos.
    Ordem de teste conforme documentação:
      already_logged → char_main → char_select → login
    """
    if soup.find("select", id=lambda x: x and x.endswith("ucCharacterBar_ddlCurrentCharacter")):
        return "already_logged"

    if "/Popmundo.aspx/Character" in url and "ChooseCharacter" not in url:
        return "char_main"

    if "ChooseCharacter" in url or soup.find("form", action=lambda x: x and "ChooseCharacter" in x):
        return "char_select"

    if soup.find(id="ctl00_cphRightColumn_ucLogin_txtUsername"):
        return "login"

    return "unknown"


# ─── Etapa 1: Login ───────────────────────────────────────────────────────────

def do_login(session: requests.Session) -> tuple:
    """
    Navega para ChooseCharacter → redirecionado ao login → faz o postback.
    Retorna (soup, url_final).
    """
    print("🌐 Acessando página de login...")
    resp = session.get(CHAR_SELECT_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    page = detect_page(soup, resp.url)
    print(f"   Página detectada: {page}")

    if page in ("already_logged", "char_main"):
        print("   Sessão já ativa, pulando login.")
        return soup, resp.url

    if page != "login":
        raise RuntimeError(f"Página inesperada: {page} ({resp.url})")

    hidden = extract_hidden_fields(soup)
    login_url = resp.url

    payload = {
        **hidden,
        "ctl00$cphRightColumn$ucLogin$txtUsername": POPMUNDO_USER,
        "ctl00$cphRightColumn$ucLogin$txtPassword": POPMUNDO_PASS,
        "ctl00$cphRightColumn$ucLogin$ddlStatus": "0",
        "ctl00$cphRightColumn$ucLogin$btnLogin": "Entrar",
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
    }

    print("🔐 Enviando credenciais...")
    resp = session.post(login_url, data=payload, headers={
        **HEADERS,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": login_url,
    }, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser"), resp.url


# ─── Etapa 2: Seleção de personagem ──────────────────────────────────────────

def do_char_select(session: requests.Session, soup: BeautifulSoup, current_url: str) -> bool:
    """
    Na tela ChooseCharacter, encontra o botão do personagem e submete.
    Retorna True se chegou na página principal do personagem.
    """
    page = detect_page(soup, current_url)

    if page in ("already_logged", "char_main"):
        print("✅ Personagem já selecionado.")
        return True

    if page != "char_select":
        if soup.find(id="ctl00_cphRightColumn_ucLogin_txtUsername"):
            raise RuntimeError("❌ Login falhou. Verifique usuário e senha.")
        raise RuntimeError(f"Página inesperada na seleção: {page}")

    print(f"🎭 Procurando personagem '{POPMUNDO_CHARNAME}'...")

    buttons = soup.find_all("input", {"type": "submit"})
    btn = next((b for b in buttons if POPMUNDO_CHARNAME.lower() in b.get("value", "").lower()), None)

    if not btn:
        char_names = [b.get("value", "") for b in buttons if b.get("value")]
        raise RuntimeError(
            f"Personagem '{POPMUNDO_CHARNAME}' não encontrado. "
            f"Disponíveis: {char_names}"
        )

    hidden = extract_hidden_fields(soup)
    form = soup.find("form")
    action = form.get("action", CHAR_SELECT_URL)
    if not action.startswith("http"):
        action = BASE_URL + "/" + action.lstrip("/")

    payload = {
        **hidden,
        btn["name"]: btn["value"],
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
    }

    print(f"   Selecionando '{btn['value']}'...")
    resp = session.post(action, data=payload, headers={
        **HEADERS,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": CHAR_SELECT_URL,
    }, timeout=15)
    resp.raise_for_status()

    final_soup = BeautifulSoup(resp.text, "html.parser")
    final_page = detect_page(final_soup, resp.url)
    print(f"   Resultado: {final_page} ({resp.url})")

    return final_page in ("char_main", "already_logged")


# ─── Etapa 3: Verifica a Torre ────────────────────────────────────────────────

def check_tower(session: requests.Session) -> bool:
    print("🔍 Verificando Torre Infernal...")
    resp = session.get(TOWER_URL, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return FIRE_MARKER in resp.text


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    with requests.Session() as session:
        soup, url = do_login(session)
        success = do_char_select(session, soup, url)

        if not success:
            raise RuntimeError("Não foi possível confirmar o acesso ao personagem.")

        print("✅ Autenticado com sucesso!")

        if check_tower(session):
            print("🔥 TORRE INFERNAL ATIVA!")
            message = (
                "🔥 <b>TORRE INFERNAL EM CHAMAS!</b>\n\n"
                "Uma aventura está disponível agora no Popmundo!\n"
                f"👉 <a href='{TOWER_URL}'>Clique aqui para entrar</a>"
            )
            send_telegram(message)
        else:
            print("🏰 Torre tranquila. Nenhuma ação necessária.")


if __name__ == "__main__":
    main()
