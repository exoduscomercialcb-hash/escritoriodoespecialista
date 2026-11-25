"""E-mails de "novos cancelados na campanha de resgate" (porta do email_cancelados.py do Kit do sistema atual).

Depois de cada busca, `app/busca/completa.py` chama `enviar_cancelados` com `Saida.novos_cancelados` (o NOVOS do
script: {EQUIPE: {"lider", "lider_sga", "rows": [cancelados]}}). Quem recebe vem do pacote "notif_lideres" do banco
(o notif_lideres.json do Kit, pela importação; tem e-mails, por isso nunca entra no repositório):
    {"EQUIPE": {"lider", "emails": [...]}, ..., "_especialistas": {"NOME NO SGA": {"nome", "equipe", "emails": [...]}}}

Da linha `NOMES =` até o fim de `montar`: cópia do script, sem mudança (mesmas frases, mesmo HTML, mesma mensagem do
WhatsApp, mesmos critérios); só o LINK mudou (marcado ADAPTAÇÃO). `montar_emails` é o bloco __main__ do script sem os
arquivos. `enviar_cancelados` é novo: o envio pelo Gmail (no sistema atual, quem enviava era o Claude).

EMAILS_CANCELADOS (cfg.emails_cancelados): "desligado" não envia; "teste" (padrão) manda tudo só para o GMAIL_USUARIO,
com [TESTE] e para quem iria; "ligado" manda para os destinatários reais.
"""
from __future__ import annotations

import html
import logging
import re
import smtplib
import ssl
import unicodedata
import urllib.parse
from email.message import EmailMessage

from sqlalchemy.orm import Session

from .atualizacoes import concluir, iniciar
from .config import Config
from .dados import ler

log = logging.getLogger("escritorio")

# ---------------------------------------------------------------- cópia do email_cancelados.py (Kit), sem mudança
NOMES = {"ÁGUIAS": "Águias", "ELIM": "Elim", "ELITE": "Elite", "EXODUS BENEFÍCIOS": "Exodus Benefícios", "LUA": "Lua", "MAGNATAS": "Magnatas", "PÉ NO CHÃO": "Pé no Chão", "RECREIO": "Recreio", "TUBARÕES": "Tubarões"}
LINK = "https://escritorio.exodusbeneficios.com.br/escritorio"   # ADAPTAÇÃO: era o link do artefato do sistema atual
def first_name(n):
    w = (str(n or "").strip().split() or [""])[0]
    if not re.search(r"[A-Za-zÀ-ÿ]", w): return ""
    return "-".join(p[:1].upper() + p[1:].lower() for p in w.split("-"))
def short_model(m, moto):
    s_ = str(m or "").strip()
    if not s_: return ""
    if "/" in s_.split()[0]: s_ = s_.split("/", 1)[-1].strip() or s_   # só marca/modelo no 1º termo (ex.: FIAT/UNO); "KA 1.5 SE/SE PLUS" fica KA
    t = s_.split(); out = [t[0]]; i = 1
    if re.match(r"^(new|novo|nova|grand)$", t[0], re.I) and len(t) > 1: out.append(t[i]); i += 1
    if moto and len(t) > i and re.match(r"^\d{2,4}$", t[i]): out.append(t[i])
    return " ".join(out)
def mensagem(r):            # mesma mensagem da promoção do Escritório do Especialista
    mod = short_model(r.get("mod"), r.get("moto")); ano = str(r.get("ano") or "").split("/")[-1].strip()
    veic = " ".join(x for x in [mod or "seu veículo", ano] if x) + (" – " + r["pl"] if r.get("pl") else "")
    pn = first_name(r.get("n"))
    linhas = ("• *50% OFF* no 1º boleto\n\n• *10% OFF* nos demais" if r.get("moto")
              else "• *50% OFF* no 1º boleto\n\n• *10% OFF* nos demais (sem adesivo)\n\n• *20% OFF* nos demais (com adesivo)")
    return ("Olá" + (", " + pn if pn else "") + "! Tudo bem?\n\n" + "Você já foi associado da Exodus Benefícios com " + ("a" if r.get("moto") else "o") + ":\n" +
            veic + "\n\n" + "Temos uma promoção especial de retorno pra você:\n" + linhas + "\n\n" +
            "Quer garantir essa promoção com esse veículo ou com um novo? *É só digitar SIM aqui!*")
def wa_link(r): return "https://wa.me/" + str(r["wa"]) + "?text=" + urllib.parse.quote(mensagem(r))
def elegivel(c): return c.get("mp") is not None and c["mp"] >= 0.7 and c.get("b") is not None and c["b"] >= 3
def br(d): return "/".join(reversed(d.split("-"))) if d else ""
def pct(v): return ("%.0f%%" % (v * 100)).replace(".", ",")
def N(x): return " ".join(unicodedata.normalize("NFKD", str(x or "")).encode("ascii", "ignore").decode().upper().split())
def montar(team, lider, rows, teste=False, lider_sga="", esp=False):
    e = html.escape; LS = N(lider_sga)
    def dono(c):
        if LS and c.get("vi") and N(c["vi"]) == LS: return '<b style="color:#1d4f96">Sua carteira</b> (sorteio da carteira Exodus Benefícios' + ('' if N(c.get("en")) == "EXODUS BENEFICIOS" else ' · especialista ' + e(c.get("esp") or "—")) + ')'
        if LS and N(c.get("en") or c.get("esp")) == LS: return '<b style="color:#1d4f96">Sua carteira' + ('' if esp else ' (líder)') + '</b>'
        return 'Liderado: <b>' + e(c.get("esp") or "—") + '</b>'
    def dono_txt(c):
        if LS and c.get("vi") and N(c["vi"]) == LS: return "sua carteira (sorteio da carteira Exodus Benefícios)"
        return ("sua carteira" if esp else "sua carteira (líder)") if LS and N(c.get("en") or c.get("esp")) == LS else "liderado " + str(c.get("esp") or "—")
    eq = NOMES.get(team, team); n = len(rows)
    np_ = sum(1 for c in rows if not c.get("coord")); nc_ = n - np_
    pl_ = lambda k, a, b: a if k == 1 else b
    if nc_ == 0: assunto = "%d %s na campanha de resgate" % (n, pl_(n, "novo cancelado", "novos cancelados"))
    elif np_ == 0: assunto = "%d %s para negociar com o coordenador" % (n, pl_(n, "novo cancelado", "novos cancelados"))
    else: assunto = "%d %s para resgate" % (n, pl_(n, "novo cancelado", "novos cancelados"))
    tit = ("[TESTE] " if teste else "") + "Escritório do Especialista · " + assunto + " · Equipe " + eq
    lin = []
    def base_txt(c):
        if "ov" not in c: return ""
        ov = c["ov"]
        if ov:
            q = len(ov)
            return ('<tr><td style="padding:2px 16px 8px"><div style="background:#e3f4ea;color:#12784a;border-radius:10px;padding:10px 12px;font-size:14px">'
                    '<b>Continua associado</b> com %d outro%s veículo%s ativo%s na base: %s</div></td></tr>') % (q, "" if q == 1 else "s", "" if q == 1 else "s", "" if q == 1 else "s", e(", ".join(ov)))
        return ('<tr><td style="padding:2px 16px 8px"><div style="background:#fbe7e5;color:#a3261f;border-radius:10px;padding:10px 12px;font-size:14px">'
                '<b>Saiu da base:</b> esse associado cancelou e ficou sem nenhum veículo ativo na Exodus.</div></td></tr>')
    def base_plain(c):
        if "ov" not in c: return ""
        return (" · continua associado com " + ", ".join(c["ov"])) if c["ov"] else " · saiu da base (nenhum veículo ativo)"
    def fone(w):
        d = str(w or ""); d = d[2:] if d.startswith("55") else d
        return "(%s) %s-%s" % (d[:2], d[2:-4], d[-4:]) if len(d) >= 10 else d
    for c in sorted(rows, key=lambda c: (bool(c.get("coord")), c["dc"], c["n"])):
        veic = " · ".join(x for x in [c.get("mod", ""), c.get("ano", "")] if x)
        if c.get("coord"):
            pg = "não pagou boleto" if not c["b"] else ("pagou só 1 boleto" if c["b"] == 1 else "pagou só %d boletos" % c["b"])
            bt = ('<div style="background:#fcf0dc;color:#8a5205;border-radius:10px;padding:11px 13px;font-size:14px;margin:0 0 10px"><b>Negociar com o coordenador.</b> Perfil bom (margem %s), mas %s, então não entra na promoção automática. '
                  'Pode voltar para a base com condições negociadas: peça a autorização do coordenador antes de oferecer.</div>') % (pct(c["mp"]), pg)
            if c.get("wa"):
                bt += ('<a href="https://wa.me/%s" target="_blank" style="display:block;background:#ffffff;color:#1a7f47;border:2px solid #1faa59;font-size:16px;font-weight:800;text-decoration:none;text-align:center;padding:12px;border-radius:10px">'
                       '&#128172; Abrir conversa no WhatsApp</a><div style="text-align:center;color:#5d6b80;font-size:12px;margin-top:6px">%s · sem a mensagem da promoção</div>') % (e(str(c["wa"])), e(fone(c["wa"])))
            else:
                bt += '<div style="text-align:center;color:#9aa8c0;font-size:13px;padding:6px">Sem celular cadastrado no SGA</div>'
        elif c.get("wa"):
            bt = ('<a href="%s" target="_blank" style="display:block;background:#1faa59;color:#ffffff;font-size:17px;font-weight:800;text-decoration:none;text-align:center;padding:15px 12px;border-radius:10px">'
                  '&#128172; Enviar promoção no WhatsApp</a><div style="text-align:center;color:#5d6b80;font-size:12px;margin-top:6px">%s · a mensagem já vai escrita, é só tocar em enviar</div>') % (e(wa_link(c)), e(fone(c["wa"])))
        else:
            bt = '<div style="text-align:center;color:#9aa8c0;font-size:13px;padding:10px">Sem celular cadastrado no SGA</div>'
        lin.append(f'''<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate;border:1px solid #d6deea;border-radius:12px;margin:0 0 14px;background:#ffffff">
<tr><td style="padding:14px 16px 4px">
<div style="font-size:11px;font-weight:800;letter-spacing:.06em;margin:0 0 6px;color:{"#9a5b06" if c.get("coord") else "#12784a"}">{"NEGOCIAR COM O COORDENADOR" if c.get("coord") else "ENTRA NA PROMOÇÃO"}</div>
<div style="font-size:17px;font-weight:800;color:#142034">{e(c["n"])}</div>
<div style="color:#5d6b80;font-size:13px;margin-top:2px">{('<b style="color:#142034">' + e(c["pl"]) + '</b> · ') if c.get("pl") else ""}{e(veic)}</div>
</td></tr>
<tr><td style="padding:8px 16px;font-size:14px;line-height:1.6;color:#142034">
<div>{dono(c)}</div>
<div>Cancelou em <b>{br(c["dc"])}</b> · {e(c.get("mot") or "")}</div>
<div>Margem <b>{pct(c["mp"])}</b> · <b>{c["b"]}</b> {"boleto pago" if c["b"] == 1 else "boletos pagos"}</div>
</td></tr>
{base_txt(c)}
<tr><td style="padding:6px 16px 16px">{bt}</td></tr>
</table>''')
    partes = []
    if np_: partes.append(f'<b>{np_} {pl_(np_, "entra", "entram")} na promoção</b> (margem de 70% ou mais e pelo menos 3 boletos pagos): toque no <b>ícone de balão de conversa &#128172;</b> de cada um e o WhatsApp abre direto na conversa do associado, com a mensagem da promoção já escrita.')
    if nc_: partes.append(f'<b>{nc_} {pl_(nc_, "tem", "têm")} perfil bom, mas pagou menos de 3 boletos</b>: não {pl_(nc_, "entra", "entram")} na promoção automática; negocie com o coordenador a autorização antes de oferecer condições.')
    intro = pl_(n, "Entrou um novo cancelamento", "Entraram novos cancelamentos") + (" da sua carteira com perfil para resgate. " if esp else " da sua equipe com perfil para resgate. ") + " ".join(partes)
    corpo = f'''<div style="background:#f2f5f9;padding:24px 12px;font-family:Arial,Helvetica,sans-serif;color:#142034">
<div style="max-width:760px;margin:0 auto;background:#fff;border:1px solid #d6deea;border-radius:14px;overflow:hidden">
<div style="background:#0f2d5c;color:#fff;padding:20px 24px"><div style="font-size:11px;letter-spacing:.14em;font-weight:800;opacity:.85">EXODUS BENEFÍCIOS · ESCRITÓRIO DO ESPECIALISTA</div>
<div style="font-size:22px;font-weight:800;margin-top:6px">{e(assunto[0].upper() + assunto[1:])}</div>
<div style="opacity:.85;margin-top:4px">Equipe {e(eq)}</div></div>
<div style="padding:20px 24px">
{'<p style="background:#fcf0dc;color:#9a5b06;border-radius:8px;padding:10px 12px;font-weight:700;margin:0 0 14px">E-mail de teste da automação.</p>' if teste else ''}
<p style="margin:0 0 6px">Olá, {e(lider.split()[0])}!</p>
<p style="margin:0 0 14px">{intro}</p>
<p style="margin:0 0 14px"><b>Chame o quanto antes, ainda dá tempo de resgatá-lo!</b></p>
{"".join(lin)}
<p style="margin:18px 0 0"><a href="{LINK}" style="display:inline-block;background:#1d4f96;color:#fff;text-decoration:none;font-weight:700;padding:12px 18px;border-radius:9px">Abrir o Escritório do Especialista</a></p>
<div style="margin:16px 0 0;background:#e3f4ea;color:#12784a;border-radius:10px;padding:12px 14px;font-size:14px"><b>Onde consultar:</b> esses cancelados estão no <b>Escritório do Especialista</b>, na aba <b>Evolução da base → Cancelados recentes</b>. O especialista também pode consultar lá, com o veículo, o motivo, a margem e a mensagem da promoção pronta.</div>
<p style="margin:12px 0 0;color:#5d6b80;font-size:12px">O ícone de balão de conversa (&#128172;) abre a conversa do associado com a mesma mensagem da campanha de resgate do Escritório do Especialista. Nos casos "negociar com o coordenador", ele abre a conversa sem a mensagem da promoção. Margem e boletos: BI Brasil Atuarial. Aviso automático enviado quando o sistema atualiza.</p>
</div></div></div>'''
    txt = "\n".join([tit, "", f"Olá, {lider.split()[0]}!", "Novos cancelados com perfil para resgate. Toque no ícone de balão de conversa 💬 de cada um: o WhatsApp abre direto na conversa do associado, com a mensagem da promoção já escrita. Os marcados [NEGOCIAR COM O COORDENADOR] pagaram menos de 3 boletos: peça a autorização do coordenador antes de oferecer. Chame o quanto antes, ainda dá tempo de resgatá-lo!"] + [f"- {'[NEGOCIAR COM O COORDENADOR] ' if c.get('coord') else ''}{c['n']} · {c.get('pl') or '—'} · {dono_txt(c)} · cancelou em {br(c['dc'])} · {c.get('mot')} · margem {pct(c['mp'])}, {c['b']} boletos" + base_plain(c) + (f" · WhatsApp: https://wa.me/{c['wa']}" if c.get('coord') and c.get('wa') else f" · WhatsApp com a promoção: {wa_link(c)}" if c.get('wa') else "") for c in rows] + ["", "Esses cancelados estão no Escritório do Especialista, aba Evolução da base → Cancelados recentes; o especialista também pode consultar lá.", "Escritório do Especialista: " + LINK])
    return tit, corpo, txt


# ---------------------------------------------------------------- bloco __main__ do script, sem os arquivos

TERMOS_PROIBIDOS = ("voluntári", "cooperativa", "seguradora")  # termos da Exodus (10/11): nunca saem no e-mail


class TermoProibido(ValueError):
    """Um e-mail montado tem termo proibido: nenhum e-mail sai (no script, o assert parava tudo)."""


def montar_emails(novos: dict, notif: dict, teste: bool = False) -> list[dict]:
    """Quem recebe o quê, igual ao __main__ do script.

    O líder recebe os cancelados da equipe; o especialista que está em `_especialistas` (com e-mail) recebe os dele, e o
    líder deixa de receber esses. Entram os elegíveis (margem >= 70% e 3+ boletos) e os "coord" com margem >= 70%.
    Devolve [{equipe, esp?, para, assunto, html, texto, n}]. Termo proibido em qualquer e-mail: TermoProibido.
    """
    cfg = notif or {}
    ESPS = {N(k): v for k, v in (cfg.get("_especialistas") or {}).items() if [x for x in (v.get("emails") or []) if x]}
    res = []
    ok_ = lambda c: elegivel(c) or (c.get("coord") and c.get("mp") is not None and c["mp"] >= 0.7)
    dono_ = lambda c: N(c.get("vi") or c.get("en") or c.get("esp"))   # vi = vendedora interna que ficou com o cancelado no sorteio da carteira
    por_esp = {}
    for team, o in (novos or {}).items():
        dest = [x for x in ((cfg.get(team) or {}).get("emails") or []) if x]
        rows = [c for c in o["rows"] if ok_(c)]
        for c in rows:
            if dono_(c) in ESPS and dono_(c) != N(o.get("lider_sga") or ""):
                if not any(x.get("pl") == c.get("pl") and x.get("mat") == c.get("mat") for x in por_esp.get(dono_(c), [])): por_esp.setdefault(dono_(c), []).append(c)
        rows = [c for c in rows if dono_(c) not in ESPS or dono_(c) == N(o.get("lider_sga") or "")]
        if not rows or not dest: continue
        tit, corpo, txt = montar(team, (cfg.get(team) or {}).get("lider") or o["lider"], rows, teste, o.get("lider_sga") or "")
        res.append({"equipe": team, "para": dest, "assunto": tit, "html": corpo, "texto": txt, "n": len(rows)})
    for en, rows in por_esp.items():
        v = ESPS[en]; team = v.get("equipe") or (rows[0].get("t") or "")
        tit, corpo, txt = montar(team, v.get("nome") or en.title(), rows, teste, en, esp=True)
        res.append({"equipe": team, "esp": v.get("nome") or en, "para": [x for x in v["emails"] if x], "assunto": tit,
                    "html": corpo, "texto": txt, "n": len(rows)})
    for r in res:   # no script, a conferência era no HTML; aqui vale também para o assunto e o texto
        t_ = (r["assunto"] + "\n" + r["html"] + "\n" + r["texto"]).lower()
        achado = next((p for p in TERMOS_PROIBIDOS if p in t_), None)
        if achado:
            raise TermoProibido(f"termo proibido (\"{achado}\") no e-mail da equipe {NOMES.get(r['equipe'], r['equipe'])}")
    return res


# ---------------------------------------------------------------- envio pelo Gmail

SMTP_SERVIDOR, SMTP_PORTA = "smtp.gmail.com", 587
AVISO_TESTE = "E-mail de teste da automação."


def _marcar_teste(e: dict) -> dict:
    """Modo teste: o e-mail igual ao real (montado com teste=True, como o --teste do script) e uma linha no topo com
    para quem iria. O resto do texto não muda."""
    quem = ("especialista " + str(e["esp"])) if e.get("esp") else ("equipe " + NOMES.get(e["equipe"], e["equipe"]))
    linha = f"Com EMAILS_CANCELADOS=ligado, iria para {', '.join(e['para'])} ({quem})."
    marca = AVISO_TESTE + "</p>"
    corpo = e["html"].replace(marca, AVISO_TESTE + " " + html.escape(linha) + "</p>", 1) if marca in e["html"] else (
        '<p style="font-weight:700">' + html.escape(linha) + "</p>" + e["html"])
    titulo, _, resto = e["texto"].partition("\n")
    return dict(e, html=corpo, texto=titulo + "\n" + AVISO_TESTE + " " + linha + "\n" + resto)


def _mensagem(remetente: str, para: list[str], e: dict) -> EmailMessage:
    m = EmailMessage()
    m["Subject"], m["From"], m["To"] = e["assunto"], remetente, ", ".join(para)
    m.set_content(e["texto"])
    m.add_alternative(e["html"], subtype="html")
    return m


def _plural(n: int, um: str, varios: str) -> str:
    return f"{n} {um if n == 1 else varios}"


def enviar_cancelados(db: Session, cfg: Config, novos: dict, smtp=None) -> dict:
    """Envia os e-mails dos novos cancelados conforme cfg.emails_cancelados. Nunca levanta erro: registra no painel
    (fonte "email", tipo = o modo) quantos e-mails e para quantas equipes, sem endereços nem nomes de associados.

    `smtp`: conexão já aberta (nos testes, um objeto falso com starttls, login, send_message e quit). Sem ela, abre
    smtp.gmail.com:587 com STARTTLS.
    """
    modo = cfg.emails_cancelados
    if modo == "desligado":
        return {"ok": True, "modo": modo, "enviados": 0, "mensagem": "E-mails de cancelados desligados (EMAILS_CANCELADOS)."}
    try:
        a = iniciar(db, "email", modo)
    except Exception as e:  # noqa: BLE001 - o aviso nunca derruba a busca
        log.warning("E-mails de cancelados: não deu para registrar (%s).", type(e).__name__)
        return {"ok": False, "modo": modo, "enviados": 0, "mensagem": "Não deu para registrar o envio."}

    def fim(ok: bool, mensagem: str, enviados: int = 0) -> dict:
        return dict(concluir(db, a, ok, mensagem), modo=modo, enviados=enviados)

    if not cfg.gmail_usuario or not cfg.gmail_senha_app:
        return fim(False, "Nenhum e-mail enviado: falta no Render GMAIL_USUARIO ou GMAIL_SENHA_APP.")
    notif = ler(db, "notif_lideres")
    if not notif:
        return fim(False, "Nenhum e-mail enviado: falta a lista de destinatários (notif_lideres, pela importação do "
                          "sistema atual).")
    try:
        emails = montar_emails(novos or {}, notif, teste=modo == "teste")
    except TermoProibido as e:
        return fim(False, f"Nenhum e-mail enviado: {e}.")
    except Exception as e:  # noqa: BLE001
        return fim(False, f"Nenhum e-mail enviado: erro ao montar os e-mails ({type(e).__name__}).")
    sem_email = sorted(NOMES.get(t, t) for t, o in (novos or {}).items()
                       if o.get("rows") and not [x for x in ((notif.get(t) or {}).get("emails") or []) if x])
    obs = (" Equipes com cancelados e sem e-mail cadastrado: " + ", ".join(sem_email) + ".") if sem_email else ""
    if not emails:
        return fim(True, "Nenhum cancelado novo para avisar." + obs)

    if modo == "teste":
        emails = [_marcar_teste(e) for e in emails]
        destinos = [[cfg.gmail_usuario] for _ in emails]
    else:
        destinos = [e["para"] for e in emails]
    equipes = len({e["equipe"] for e in emails})
    enviados = 0
    try:
        if smtp is None:
            smtp = smtplib.SMTP(SMTP_SERVIDOR, SMTP_PORTA, timeout=30)
        try:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(cfg.gmail_usuario, cfg.gmail_senha_app.replace(" ", ""))
            for e, para in zip(emails, destinos):
                smtp.send_message(_mensagem(cfg.gmail_usuario, para, e))
                enviados += 1
        finally:
            try:
                smtp.quit()
            except Exception:  # noqa: BLE001 - a conexão já pode ter caído
                pass
    except Exception as e:  # noqa: BLE001 - só o tipo do erro: a mensagem do servidor pode repetir o login
        return fim(False, f"Erro no envio pelo Gmail ({type(e).__name__}): {enviados} de "
                          f"{_plural(len(emails), 'e-mail', 'e-mails')} enviado(s).{obs}", enviados)
    if modo == "teste":
        reais = len({x for e in emails for x in e["para"]})
        texto = (f"Modo teste: {_plural(enviados, 'e-mail', 'e-mails')} de {_plural(equipes, 'equipe', 'equipes')}, "
                 f"enviados só para o remetente (com EMAILS_CANCELADOS=ligado, iriam para "
                 f"{_plural(reais, 'endereço', 'endereços')}).")
    else:
        texto = f"{_plural(enviados, 'e-mail enviado', 'e-mails enviados')} para {_plural(equipes, 'equipe', 'equipes')}."
    return fim(True, texto + obs, enviados)
