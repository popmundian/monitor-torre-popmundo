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

def fmt_duracao(minutos):
    if not isinstance(minutos, int):
        return "?"
    h = minutos // 60
    m = minutos % 60
    return f"{h:02d}:{m:02d}"


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
            imprimir(f" 🎭 Procurando '{NOME DO PERSONAGEM POPMUNDO}'...")
            botões = sopa.encontrar_todos("entrada", {"tipo": "enviar"})
            btn = próximo((b para b em botões
                        se POPMUNDO_CHARNAME.inferior() em b.pegar("valor", "").inferior()), Nenhum)

            se não btn:
                imprimir(" Personagem não encontrado aqui. Pulando...")
                retornar Nenhum

            forma = sopa.encontrar("forma")
            ação = forma.pegar("ação", "")
            ação = char_select_url se Ação.começa com("http") outro \
                     base_url + "/Mundo/Popmundo.aspx/" + ação.dividir("/")[-1]

            carga útil = {
                **campos_ocultos(sopa),
                btn["nome"]: btn["valor"],
                "__EVENTTARGET": "", "__EVENTARGUMENT": "",
            }
            imprimir(f" Seleccionando '{btn['valor']}'...")
            resp = s.postar(ação, dados=carga útil, cabeçalhos={
                **CABEÇALHOS,
                "Tipo de conteúdo": "aplicativo/x-www-form-urlencoded",
                "Árbitro": char_select_url,
            }, tempo limite=15)
            resp.status_para_aumentar()
            sopa_final = Linda sopa(resp.texto, "html.parser")
            página_final = detectar_página(sopa_final, resp.url)
            imprimir(f" Resultado: {página_final}")

            se página_final em ("login", "char_select"):
                imprimir(" ⚠️ Ainda na tela de login/seleção. Pulando...")
                retornar Nenhum

            # Se resultado decepcionado, verifica sessão buscando página do personagem
            se página_final == "desconhecido":
                imprimir(" 🔎 Resultado decepcionado — verificando sessão...")
                verificar = s.Pégar(base_url + "/Mundo/Popmundo.aspx/Personagem", cabosalhos=CABEÇALHOS, tempo limite=15)
                se "logout=verdadeiro" em verificar.url ou "Default.aspx" em verificar.url ou "Login" em verificar.url:
                    imprimir(f" ⚠️ Sessão inválida confirmada ({verificar.url}). Pulando...")
                    retornar Nenhum
                imprimir(f" Sessão válida ({verificar.url})")

        outro:
            imprimir(f" ⚠️ Página inesperada: {página}. Pulando...")
            retornar Nenhum

        # Etapa 4: verificar torre
        imprimir(f" 🔍 Verificando torre em {torre_url}...")
        resp = s.pegar(tower_url, cabosalhos=CABEÇALHOS, tempo limite=15)
        resp.aumar_para_status()
        html = resp.texto

        # Detecta se a sessão foi perdida (redirecionou para logout/login)
        se "logout=verdadeiro" em resp.url ou "Default.aspx" em resp.url:
            imprimir(f" ⚠️ Sessão perdida após seleção (redirecionou para {resp.url}). Pulando...")
            retornar Nenhum

        imprimir(f" URL final: {resp.url}")
        ativo = FIRE_MARKER em HTML
        imprimir(f" Torre: {'🔥 ATIVA' se ativo outro '🏰 inativa'}")
        retornar ativo, html


# ─── Notificações ─────────────────────────────────────────────────────────────

def processo_resultado(torre_ativa, torre_html):
    estado = carregar_estado()
15
, limite de tempo=
    was_active = estado.pegar("ativo", Falso)

    se torre_ativa e não estava_ativo:
        estado["ativo"] = Verdadeiro
        estado["iniciado_em"] = agora_s

        jogo_início = ""
        m = re.procurar(r'começou em.*?>(\d{2}/\d{2}/\d{4},\s*\d{2}:\d{2})<', torre_html)
        se m:
            jogo_início = f"\n🎮 Início no jogo: <b>{meu.grupo(1)}</b>"

        máximo = ""
        se estado.pegar("último_terminado_em") e estado.pegar("última_duração_min") é não Nenhum:
            Último = (f"\n🕐 Última torre: {fmt(estado['último_terminado_em'])} "
                      f"(duração: {fmt_duração(estado['última_duração_min'])})")

        mensagem = (
            f"🔥 <b>TORRE INFERNAL EM CHAMAS!</b>\n\n"
            f"⏰ Detectada às <b>{agora.tempo de strft('%H:%M')}</b>{jogo_início}{último}"
        )
        enviar_telegrama(mensagem)
        imprimir("📨 Notificação de INÍCIO ambiental.")

    elif não torre_ativa e estava_ativo:
        iniciado = data e hora.deisoformato(estado["iniciado_em"]) se estado.pegar("iniciado_em") outro Nenhum
        duração_min = int((agora - começou).total_segundos() / 60) se iniciado outro Nenhum
        estado["ativo"] = Falso
        estado["último_terminado_em"] = agora_s
        estado["última_duração_min"] = duração_min

        início = f" (iniciou às {fmt(estado['iniciado_em'])})" se estado.pegar("iniciado_em") outro ""
        mensagem = (
            f"✅ <b>Torre Infernal apagada!</b>\n\n"
            f"⏱ Durou <b>{fmt_duraçao(duração_min)}</b>{iniciativa}\n"
            f"🕐 Encerrou às <b>{agora.tempo de strft('%H:%M')}</b>"
        )
        enviar_telegrama(mensagem)
        imprimir("📨 Notificação de PROCESSAMENTO ambiental.")

    elif torre_ativa e estava_ativo:
        iniciado = data e hora.deisoformato(estado["iniciado_em"]) se estado.pegar("iniciado_em") outro Nenhum
        decorrido = int((agora - começou).total_segundos() / 60) se iniciado outro "?"
        imprimir(f"🔥 Torre ainda ativa (há ~{fmt_duraçao(decorrido) se é instância(decorrido, int) outro decorrido}). Sem nova notificação.")

    outro:
        print("🏰 Torre continua inativa. Nenhuma ação.")

    save_state(state)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    MAX_TENTATIVAS = 3

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        if tentativa > 1:
            print(f"\n🔄 Retentativa {tentativa}/{MAX_TENTATIVAS}...")

        for server in SERVERS:
            result = try_server(server)
            if result is None:
                continue
            tower_active, tower_html = result
            print(f"✅ Personagem confirmado no servidor {server}.")
            process_result(tower_active, tower_html)
            print("\n=== Verificação concluída ===")
            return  # sucesso — encerra

        print(f"⚠️ Nenhum servidor respondeu na tentativa {tentativa}.")

    raise RuntimeError(
        f"❌ Personagem '{POPMUNDO_CHARNAME}' não encontrado após {MAX_TENTATIVAS} tentativas. "
        f"Verifique o Secret POPMUNDO_CHARNAME ou tente novamente mais tarde."
    )


if __name__ == "__main__":
    main()
