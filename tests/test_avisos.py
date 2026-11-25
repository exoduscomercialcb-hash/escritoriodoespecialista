"""E-mails de novos cancelados na campanha de resgate (app/avisos.py). SMTP falso e dados inventados."""
import html
import smtplib

import pytest
from sqlalchemy import select

from app import avisos
from app.avisos import LINK, TermoProibido, enviar_cancelados, montar_emails
from app.config import carregar
from app.dados import guardar, ler
from app.db import Atualizacao

from .conftest import cfg_teste
from .test_dados import EXPORTACAO

REMETENTE = "remetente.teste@exemplo.com.br"
SENHA = "abcd efgh ijkl mnop"  # inventada
LIDER_SGA = "LIDER INVENTADO DA SILVA"

NOTIF = {
    "LUA": {"lider": "Lider Inventado", "emails": ["lider.lua@exemplo.com.br", ""]},
    "ELIM": {"lider": "Lider Sem Lista", "emails": []},
    "_especialistas": {
        "ESPECIALISTA COM EMAIL INVENTADO": {"nome": "Especialista Inventado", "equipe": "LUA",
                                             "emails": ["especialista@exemplo.com.br"]},
        "ESPECIALISTA SEM EMAIL INVENTADO": {"nome": "Outro Inventado", "equipe": "LUA", "emails": [""]},
        LIDER_SGA: {"nome": "Lider Inventado", "equipe": "LUA", "emails": ["lider.pessoal@exemplo.com.br"]},
    },
}


def cancelado(n, esp, **mais):
    c = {"n": n, "mat": n[-1], "pl": "TST" + n[-1] + "A00", "mod": "FIAT/UNO WAY 1.0", "ano": "2019/2020",
         "moto": False, "wa": "552190000000" + n[-1], "dc": "2026-11-20", "mot": "Motivo inventado", "mp": 0.8, "b": 4,
         "esp": esp, "en": esp, "t": "LUA", "lt": "LUA"}
    c.update(mais)
    return c


def novos_inventados():
    return {
        "LUA": {"lider": "Lider Do Sga", "lider_sga": LIDER_SGA, "rows": [
            cancelado("ASSOCIADO INVENTADO 1", "ESPECIALISTA COM EMAIL INVENTADO"),   # vai para o especialista
            cancelado("ASSOCIADO INVENTADO 2", "ESPECIALISTA SEM EMAIL INVENTADO"),   # fica com o líder
            cancelado("ASSOCIADO INVENTADO 3", LIDER_SGA),                            # carteira do próprio líder
            cancelado("ASSOCIADO INVENTADO 4", "ESPECIALISTA SEM EMAIL INVENTADO", mp=0.5),        # margem baixa
            cancelado("ASSOCIADO INVENTADO 5", "ESPECIALISTA SEM EMAIL INVENTADO", b=1, coord=True),  # coordenador
            cancelado("ASSOCIADO INVENTADO 6", "ESPECIALISTA SEM EMAIL INVENTADO", b=1, mp=0.6, coord=True),
            cancelado("ASSOCIADO INVENTADO 7", "ESPECIALISTA SEM EMAIL INVENTADO", b=2),          # sem a marca coord
        ]},
        "ELIM": {"lider": "Lider Sem Lista", "lider_sga": "", "rows": [
            cancelado("ASSOCIADO INVENTADO 8", "ESPECIALISTA ELIM INVENTADO", t="ELIM", lt="ELIM")]},
    }


class SMTPFalso:
    def __init__(self, erro_no=None, erro=None):
        self.chamadas, self.enviadas, self.erro_no, self.erro = [], [], erro_no, erro

    def _talvez_erro(self, onde):
        if self.erro_no == onde:
            raise self.erro

    def starttls(self, **kw):
        self.chamadas.append(("starttls", bool(kw.get("context"))))
        self._talvez_erro("starttls")

    def login(self, usuario, senha):
        self.chamadas.append(("login", usuario, senha))
        self._talvez_erro("login")

    def send_message(self, msg):
        self._talvez_erro(("send", len(self.enviadas)))
        self.enviadas.append(msg)

    def quit(self):
        self.chamadas.append(("quit",))


def corpo(msg, tipo):
    return next(p for p in msg.walk() if p.get_content_type() == "text/" + tipo).get_content()


def registros(db):
    return db.scalars(select(Atualizacao).where(Atualizacao.fonte == "email").order_by(Atualizacao.id)).all()


def cfg(modo="teste", **mais):
    return cfg_teste(**dict(dict(gmail_usuario=REMETENTE, gmail_senha_app=SENHA, emails_cancelados=modo), **mais))


# ---------------------------------------------------------------- montagem (igual ao script do sistema atual)

def test_quem_recebe_o_que():
    emails = montar_emails(novos_inventados(), NOTIF)
    assert [(e["equipe"], e.get("esp"), e["para"], e["n"]) for e in emails] == [
        ("LUA", None, ["lider.lua@exemplo.com.br"], 3),                 # ELIM não tem e-mail: não sai
        ("LUA", "Especialista Inventado", ["especialista@exemplo.com.br"], 1),
    ]
    lider, esp = emails
    assert "ASSOCIADO INVENTADO 1" not in lider["html"] and "ASSOCIADO INVENTADO 1" in esp["html"]
    for n in ("2", "3", "5"):  # especialista sem e-mail, carteira do próprio líder e o "coord" com margem boa
        assert "ASSOCIADO INVENTADO " + n in lider["html"] and "ASSOCIADO INVENTADO " + n in lider["texto"]
    for n in ("4", "6", "7"):  # margem < 70%, "coord" com margem < 70% e menos de 3 boletos sem a marca coord
        assert "ASSOCIADO INVENTADO " + n not in lider["html"]
    assert "Sua carteira (líder)" in lider["html"] and "Liderado: <b>ESPECIALISTA SEM EMAIL INVENTADO</b>" in lider["html"]
    assert "NEGOCIAR COM O COORDENADOR" in lider["html"] and "ENTRA NA PROMOÇÃO" in lider["html"]
    assert lider["assunto"] == "Escritório do Especialista · 3 novos cancelados para resgate · Equipe Lua"
    assert esp["assunto"] == "Escritório do Especialista · 1 novo cancelado na campanha de resgate · Equipe Lua"
    assert "Olá, Lider!" in lider["html"] and "Olá, Especialista!" in esp["html"]
    assert "da sua carteira com perfil para resgate" in esp["html"] and "Sua carteira</b>" in esp["html"]


def test_cancelado_repetido_em_duas_equipes_vai_uma_vez_para_o_especialista():
    c = cancelado("ASSOCIADO INVENTADO 1", "ESPECIALISTA COM EMAIL INVENTADO", lt="ELIM")
    novos = {"LUA": {"lider": "L", "lider_sga": LIDER_SGA, "rows": [c]}, "ELIM": {"lider": "L", "lider_sga": "", "rows": [c]}}
    assert [(e.get("esp"), e["n"]) for e in montar_emails(novos, NOTIF)] == [("Especialista Inventado", 1)]


def test_mensagem_do_whatsapp_e_link_novo():
    emails = montar_emails(novos_inventados(), NOTIF)
    esp = emails[1]
    assert LINK == "https://escritorio.exodusbeneficios.com.br/escritorio"
    assert LINK in esp["html"] and esp["texto"].endswith("Escritório do Especialista: " + LINK)
    assert "claude.ai" not in esp["html"] + esp["texto"]
    c1 = novos_inventados()["LUA"]["rows"][0]
    msg = avisos.mensagem(c1)  # a mesma mensagem da promoção do Escritório do Especialista
    assert msg.startswith("Olá, Associado! Tudo bem?\n\nVocê já foi associado da Exodus Benefícios com o:\nUNO 2020 – TST1A00")
    assert "*20% OFF* nos demais (com adesivo)" in msg and msg.endswith("*É só digitar SIM aqui!*")
    assert html.escape(avisos.wa_link(c1)) in esp["html"] and avisos.wa_link(c1) in esp["texto"]


def test_elegibilidade():
    assert avisos.elegivel({"mp": 0.7, "b": 3}) and not avisos.elegivel({"mp": 0.69, "b": 9})
    assert not avisos.elegivel({"mp": 0.9, "b": 2}) and not avisos.elegivel({"mp": None, "b": 5})


@pytest.mark.parametrize("termo", ["Virou voluntário", "Foi para outra COOPERATIVA", "Contratou seguradora"])
def test_termo_proibido_bloqueia(termo):
    novos = novos_inventados()
    novos["LUA"]["rows"][1]["mot"] = termo
    with pytest.raises(TermoProibido):
        montar_emails(novos, NOTIF)


# ---------------------------------------------------------------- envio

def test_modo_teste_manda_tudo_so_para_o_remetente(db):
    guardar(db, "notif_lideres", NOTIF, "importacao")
    smtp = SMTPFalso()
    r = enviar_cancelados(db, cfg("teste"), novos_inventados(), smtp=smtp)
    assert r["ok"] and r["enviados"] == 2 and r["modo"] == "teste"
    assert smtp.chamadas == [("starttls", True), ("login", REMETENTE, "abcdefghijklmnop"), ("quit",)]
    assert [m["To"] for m in smtp.enviadas] == [REMETENTE, REMETENTE]
    assert all(m["Subject"].startswith("[TESTE] Escritório do Especialista · ") for m in smtp.enviadas)
    lider = smtp.enviadas[0]
    assert "iria para lider.lua@exemplo.com.br (equipe Lua)" in corpo(lider, "html")
    texto = corpo(lider, "plain").splitlines()
    assert texto[0].startswith("[TESTE] ") and "iria para lider.lua@exemplo.com.br (equipe Lua)" in texto[1]
    assert "iria para especialista@exemplo.com.br (especialista Especialista Inventado)" in corpo(smtp.enviadas[1], "plain")
    # o resto do texto é o do e-mail real
    real = montar_emails(novos_inventados(), NOTIF)[0]["texto"].splitlines()
    assert texto[2:] == real[1:]
    (a,) = registros(db)
    assert (a.tipo, a.ok) == ("teste", True) and "2 e-mails de 1 equipe" in a.mensagem
    assert "@" not in a.mensagem and "INVENTADO" not in a.mensagem and "Inventad" not in a.mensagem


def test_modo_ligado_manda_para_os_destinatarios_reais(db):
    guardar(db, "notif_lideres", NOTIF, "importacao")
    smtp = SMTPFalso()
    r = enviar_cancelados(db, cfg("ligado"), novos_inventados(), smtp=smtp)
    assert r["ok"] and r["enviados"] == 2
    assert [m["To"] for m in smtp.enviadas] == ["lider.lua@exemplo.com.br", "especialista@exemplo.com.br"]
    assert [m["From"] for m in smtp.enviadas] == [REMETENTE, REMETENTE]
    assert not any("[TESTE]" in m["Subject"] for m in smtp.enviadas)
    assert "E-mail de teste" not in corpo(smtp.enviadas[0], "html") and LINK in corpo(smtp.enviadas[0], "html")
    (a,) = registros(db)
    assert (a.tipo, a.ok) == ("ligado", True) and a.mensagem.startswith("2 e-mails enviados para 1 equipe.")
    assert "Elim" in a.mensagem  # equipe com cancelados e sem e-mail cadastrado
    assert "@" not in a.mensagem and "ASSOCIADO" not in a.mensagem


def test_desligado_nao_manda_nem_registra(db):
    guardar(db, "notif_lideres", NOTIF, "importacao")
    smtp = SMTPFalso()
    assert enviar_cancelados(db, cfg("desligado"), novos_inventados(), smtp=smtp)["enviados"] == 0
    assert smtp.chamadas == [] and smtp.enviadas == [] and registros(db) == []


def test_termo_proibido_nao_envia_nada(db):
    guardar(db, "notif_lideres", NOTIF, "importacao")
    novos = novos_inventados()
    novos["LUA"]["rows"][0]["mot"] = "Foi para seguradora"  # o do especialista: o do líder também não sai
    smtp = SMTPFalso()
    r = enviar_cancelados(db, cfg("ligado"), novos, smtp=smtp)
    assert not r["ok"] and smtp.chamadas == [] and smtp.enviadas == []
    assert "termo proibido" in registros(db)[0].mensagem


@pytest.mark.parametrize("faltando", ["gmail_usuario", "gmail_senha_app"])
def test_sem_usuario_ou_senha_nao_envia(db, faltando):
    guardar(db, "notif_lideres", NOTIF, "importacao")
    smtp = SMTPFalso()
    r = enviar_cancelados(db, cfg("ligado", **{faltando: ""}), novos_inventados(), smtp=smtp)
    assert not r["ok"] and smtp.chamadas == [] and smtp.enviadas == []
    (a,) = registros(db)
    assert a.ok is False and "GMAIL_SENHA_APP" in a.mensagem


def test_sem_lista_de_destinatarios_nao_envia(db):
    smtp = SMTPFalso()
    r = enviar_cancelados(db, cfg("ligado"), novos_inventados(), smtp=smtp)
    assert not r["ok"] and smtp.chamadas == [] and "notif_lideres" in registros(db)[0].mensagem


def test_sem_cancelado_novo_registra_e_nao_conecta(db):
    guardar(db, "notif_lideres", NOTIF, "importacao")
    smtp = SMTPFalso()
    r = enviar_cancelados(db, cfg("ligado"), {}, smtp=smtp)
    assert r["ok"] and r["enviados"] == 0 and smtp.chamadas == []
    assert registros(db)[0].mensagem == "Nenhum cancelado novo para avisar."


def test_erro_no_login_e_registrado_sem_a_senha(db):
    guardar(db, "notif_lideres", NOTIF, "importacao")
    smtp = SMTPFalso(erro_no="login", erro=smtplib.SMTPAuthenticationError(535, b"recusado " + SENHA.encode()))
    r = enviar_cancelados(db, cfg("ligado"), novos_inventados(), smtp=smtp)  # não levanta erro
    assert not r["ok"] and r["enviados"] == 0 and smtp.chamadas[-1] == ("quit",)
    (a,) = registros(db)
    assert a.ok is False and "SMTPAuthenticationError" in a.mensagem and "0 de 2 e-mails" in a.mensagem
    assert SENHA not in a.mensagem and "abcd" not in a.mensagem and "recusado" not in a.mensagem


def test_erro_no_meio_do_envio_conta_o_que_saiu(db):
    guardar(db, "notif_lideres", NOTIF, "importacao")
    smtp = SMTPFalso(erro_no=("send", 1), erro=smtplib.SMTPServerDisconnected("caiu"))
    r = enviar_cancelados(db, cfg("ligado"), novos_inventados(), smtp=smtp)
    assert not r["ok"] and r["enviados"] == 1 and len(smtp.enviadas) == 1
    assert "SMTPServerDisconnected" in registros(db)[0].mensagem and "1 de 2 e-mails" in registros(db)[0].mensagem


def test_sem_conexao_com_o_gmail_nao_derruba(db, monkeypatch):
    guardar(db, "notif_lideres", NOTIF, "importacao")

    def recusa(*a, **kw):
        raise OSError("sem rede")

    monkeypatch.setattr(avisos.smtplib, "SMTP", recusa)
    r = enviar_cancelados(db, cfg("ligado"), novos_inventados())
    assert not r["ok"] and "OSError" in registros(db)[0].mensagem


# ---------------------------------------------------------------- configuração e importação

def test_configuracao_do_modo():
    assert carregar({}).emails_cancelados == "teste"  # padrão: nunca manda aos reais sem querer
    assert carregar({"EMAILS_CANCELADOS": " Ligado "}).emails_cancelados == "ligado"
    assert carregar({"EMAILS_CANCELADOS": "desligado"}).emails_cancelados == "desligado"
    assert carregar({"EMAILS_CANCELADOS": "sim"}).emails_cancelados == "teste"
    c = carregar({"GMAIL_USUARIO": REMETENTE, "GMAIL_SENHA_APP": SENHA})
    assert (c.gmail_usuario, c.gmail_senha_app) == (REMETENTE, SENHA) and SENHA not in repr(c)


def test_notif_lideres_vem_pela_importacao_e_nao_vai_para_a_pagina(admin, db):
    r = admin.post("/api/admin/importar-sistema-atual", json=dict(EXPORTACAO, notif_lideres=NOTIF))
    assert r.status_code == 200, r.text
    db.expire_all()
    assert ler(db, "notif_lideres") == NOTIF
    pagina = admin.get("/api/dados")
    assert pagina.status_code == 200 and "exemplo.com.br" not in pagina.text and "notif" not in pagina.text
