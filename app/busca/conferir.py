"""Conferir um veículo no SGA: por que uma adesão não aparece no card "Comprovante de adesões".

Painel > Atualizações (só o administrador). Poucas chamadas ao SGA, todas de leitura:
1. o login;
2. a ficha do veículo: GET /veiculo/buscar/{valor}/{campo}, com campo = codigo, placa ou chassi;
3. se a ficha tiver data de contrato (ou se o administrador informou a data): UMA página de POST /listar/veiculo com
   data_contrato = data_contrato_final = esse dia, que é como a busca completa encontra as adesões do mês.
O limite do cliente (LIMITE_CHAMADAS) cobre uma renovação do login ou uma nova tentativa; nada além disso.

Depois aplica, item a item, as regras de app/busca/retorno.py (trecho "ativações (adesões) dos meses abertos" e a lista
ADES) e procura o veículo no pacote "all" atual. Sem o histórico de situações (seriam dezenas de chamadas), "saiu no mês"
e "ativo no fim do mês" usam a situação de hoje e a data da última alteração, como o script faz quando o veículo não tem
histórico.

O registro (tabela atualizacoes) guarda só a conclusão, sem nome de associado, placa ou chassi.
"""
from __future__ import annotations

import datetime as dt
import re

from sqlalchemy.orm import Session

from ..atualizacoes import TRAVA_SGA, concluir, iniciar, proximo_horario_sga, trava_ativa, travar
from ..config import FUSO, Config
from ..dados import N, chaves, ler
from ..fontes.sga import ClienteSGA, SGABloqueado, SGAErro
from ..servicos import ErroRegra
from ..tempo import agora, formatar
from .completa import TRAVA_BUSCA

# Cópias das regras de app/busca/retorno.py (lá ficam dentro de rodar()). tests/test_conferir_veiculo.py confere que
# continuam iguais ao script: se mudar lá, o teste avisa.
COOP = {"1": "EXODUS BENEFÍCIOS", "2": "LUA", "3": "PÉ NO CHÃO", "4": "ÁGUIAS", "5": "MAGNATAS", "6": "TUBARÕES",
        "7": "ELIM", "8": "ELITE", "9": "RECREIO"}
ACT_S = {"1", "18", "16", "19"}  # Ativo, Ativo - Pendente Instalação, Aguardando instalação, Ativo - Dispensa Instalação
SAIU = {"6", "10", "2"}  # cancelado, retirado, inativo
COMP_DESDE = "2026-10"  # o card "Comprovante de adesões" começa em out/26
REGRA_ATIVA_DESDE = "2026-10"  # a partir de out/26 só conta quem ficou ativo (regra do KPI COMERCIAL)

LIMITE_CHAMADAS = 4  # login + ficha + listagem, com folga para 1 renovação do login ou 1 nova tentativa
INTERVALO = 0.4  # o mesmo espaço entre chamadas da busca completa
POR_PAGINA = 100
CAMPOS = ("codigo_veiculo", "placa", "chassi", "data_contrato", "codigo_situacao", "descricao_situacao",
          "nome_voluntario", "codigo_cooperativa", "data_alteracao", "codigo_associado", "modelo")
MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro")
PLACA = re.compile(r"[A-Z]{3}[0-9][A-Z0-9][0-9]{2}")


def pl_(s) -> str:
    """Igual ao pl_() do script: só letras e números, sem acento, em maiúsculas."""
    return re.sub(r"[^A-Z0-9]", "", N(s))


def campo_da_busca(texto: str) -> tuple[str, str]:
    valor = pl_(texto)
    if valor.isdigit():
        return "codigo", valor
    if PLACA.fullmatch(valor):
        return "placa", valor
    if len(valor) == 17:
        return "chassi", valor
    raise ErroRegra("Informe a placa (ex.: ABC1D23), o chassi (17 letras e números) ou o código do veículo (só números).")


def _data_informada(texto: str | None) -> dt.date | None:
    if not texto:
        return None
    d = _dia(texto)
    if d is None:
        raise ErroRegra("A data do contrato não é válida (use dd/mm/aaaa).")
    return d


def _dia(v) -> dt.date | None:
    """Igual ao dia() do script: AAAA-MM-DD ou dd/mm/aaaa; datas vazias do SGA (0000-00-00) viram None."""
    s = str(v or "").strip()
    try:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m:
            return dt.date(int(m[1]), int(m[2]), int(m[3]))
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
        return dt.date(int(m[3]), int(m[2]), int(m[1])) if m else None
    except ValueError:
        return None


def _mes_txt(k: str) -> str:
    try:
        return f"{MESES[int(k[5:7]) - 1]} de {k[:4]}"
    except (ValueError, IndexError):
        return k


def _primeiro_mes_recalculado(hoje: dt.date) -> str:
    """O `cut` do script: a busca recalcula do mês de 2 meses atrás até o atual; os anteriores ficam congelados."""
    return ((hoje.replace(day=1) - dt.timedelta(days=1)).replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")


def _veiculos(resposta) -> list[dict]:
    if isinstance(resposta, list):
        return [x for x in resposta if isinstance(x, dict)]
    if isinstance(resposta, dict):
        if isinstance(resposta.get("veiculos"), list):
            return [x for x in resposta["veiculos"] if isinstance(x, dict)]
        if resposta.get("codigo_veiculo") is not None:
            return [resposta]
    return []


def _campos(x: dict | None) -> dict | None:
    return {c: x.get(c) for c in CAMPOS} if x else None


def _item(nome: str, ok: bool | None, texto: str) -> dict:
    """ok: True (passa), False (fica de fora por isto), None (atenção ou não deu para conferir)."""
    return {"item": nome, "ok": ok, "texto": texto}


# ---------------------------------------------------------------- SGA

def _consultar(sga: ClienteSGA, campo: str, valor: str, data: dt.date | None, avisos: list[str]):
    """Ficha e listagem do dia. Devolve (ficha, da_listagem, listagem_info)."""
    ficha = None
    try:
        achados = _veiculos(sga.get(f"/veiculo/buscar/{valor}/{campo}", tentativas=1))
        if len(achados) > 1:
            avisos.append(f"O SGA devolveu {len(achados)} veículos para essa busca; vale o de contrato mais recente.")
            achados.sort(key=lambda x: str(_dia(x.get("data_contrato")) or ""), reverse=True)
        ficha = achados[0] if achados else None
        if ficha is None:
            avisos.append(f"A busca por {campo} no SGA não achou nenhum veículo"
                          + (" (o SGA pode não aceitar esse campo: tente pelo código do veículo)." if campo != "codigo"
                             else "."))
    except SGAErro as e:  # campo não aceito (400/500...): registra e segue (a listagem do dia ainda pode achar)
        avisos.append(f"O SGA não aceitou a busca por {campo}: {e}.")

    dia = _dia((ficha or {}).get("data_contrato")) or data
    if ficha is not None and data and _dia(ficha.get("data_contrato")) and data != dia:
        avisos.append(f"A data informada ({data:%d/%m/%Y}) não é a do contrato no SGA ({dia:%d/%m/%Y}); "
                      "a listagem usou a do SGA.")
    if dia is None:
        return ficha, None, None
    corpo = {"data_contrato": dia.strftime("%d/%m/%Y"), "data_contrato_final": dia.strftime("%d/%m/%Y"),
             "quantidade_por_pagina": POR_PAGINA, "inicio_paginacao": 0}
    r = sga.post("/listar/veiculo", corpo)
    lista = _veiculos(r) if r != {} else []
    total = int(r.get("total_veiculos") or 0) if isinstance(r, dict) else len(lista)
    info = {"dia": dia.strftime("%d/%m/%Y"), "total": max(total, len(lista)), "lidos": len(lista)}
    if ficha is not None:
        cv = str(ficha.get("codigo_veiculo"))
        achado = next((x for x in lista if str(x.get("codigo_veiculo")) == cv), None)
    else:  # sem ficha: procura na listagem do dia pela placa, pelo chassi ou pelo código
        achado = next((x for x in lista if valor in {pl_(x.get("placa")), pl_(x.get("chassi")),
                                                     str(x.get("codigo_veiculo"))}), None)
        if achado is not None:
            avisos.append(f"O veículo foi achado na listagem de {info['dia']} (sem a ficha do SGA).")
        else:
            avisos.append(f"Na listagem de {info['dia']} ({info['lidos']} de {info['total']} veículo(s)) também não "
                          "veio nenhum veículo com essa placa, chassi ou código.")
    return ficha, achado, info


# ---------------------------------------------------------------- diagnóstico

def _no_pacote(db: Session, x: dict, nome_associado: str) -> dict | None:
    """A adesão no pacote "all" atual (lista ades), pela placa, pelo chassi ou pelo nome + data do contrato."""
    geral = ler(db, "all") or {}
    pl, ch = pl_(x.get("placa")), pl_(x.get("chassi"))
    d = _dia(x.get("data_contrato"))
    dc = d.strftime("%d/%m/%Y") if d else ""
    nome = N(nome_associado)
    for a in geral.get("ades") or []:
        if not isinstance(a, dict):
            continue
        if (pl and pl_(a.get("pl")) == pl) or (ch and pl_(a.get("ch")) == ch) \
                or (nome and N(a.get("n")) == nome and a.get("dc") == dc):
            return a
    return None


def _especialista_cadastrado(db: Session, nome_voluntario: str) -> str | None:
    alvo = N(nome_voluntario)
    for chave in chaves(db, "esp:"):
        esp = ler(db, chave) or {}
        if alvo == chave[4:] or alvo in (esp.get("sga") or []):
            return esp.get("nome") or chave[4:]
    return None


def diagnosticar(db: Session, ficha: dict | None, listado: dict | None, info: dict | None, hoje: dt.date,
                 nome_associado: str = "") -> tuple[list[dict], str, str]:
    """Itens do diagnóstico, conclusão (para a tela) e resumo (para o registro, sem dados do associado)."""
    x = listado or ficha  # a busca completa usa o registro da listagem por data de contrato
    if x is None:
        return [], "O SGA não devolveu nenhum veículo para essa busca.", "veículo não encontrado no SGA"
    itens = []
    mes = hoje.strftime("%Y-%m")

    s_dc = str(x.get("data_contrato") or "")
    d = _dia(s_dc)
    k = d.strftime("%Y-%m") if d else ""
    if d is None:
        itens.append(_item("Data do contrato", False, "o veículo não tem data de contrato no SGA (a busca só lê as "
                                                      "adesões pela data do contrato)"))
    elif not re.match(r"\d{4}-\d{2}-\d{2}", s_dc):
        itens.append(_item("Data do contrato", False, f"a data do contrato veio como {s_dc!r} e a busca compara o "
                                                      "começo dela com AAAA-MM"))
    else:
        itens.append(_item("Data do contrato", True, f"{d:%d/%m/%Y}"))

    if d is not None:
        if k >= COMP_DESDE:
            itens.append(_item("Mês do card de comprovantes", True, f"{_mes_txt(k)} (o card começa em out/26)"))
        else:
            itens.append(_item("Mês do card de comprovantes", False, f"o contrato é de {_mes_txt(k)} e o card de "
                                                                     "comprovantes só mostra a partir de outubro de 2026"))
        cut = _primeiro_mes_recalculado(hoje)
        if k > mes:
            itens.append(_item("Mês recalculado pela busca", False, f"o contrato está no futuro ({_mes_txt(k)})"))
        elif k < cut:
            itens.append(_item("Mês recalculado pela busca", False, f"o contrato é de {_mes_txt(k)} e a busca só "
                                                                    f"recalcula de {_mes_txt(cut)} em diante (os "
                                                                    "meses anteriores ficam congelados)"))
        else:
            itens.append(_item("Mês recalculado pela busca", True, f"de {_mes_txt(cut)} a {_mes_txt(mes)}"))

    if info is None:
        itens.append(_item("Vem na listagem por data de contrato", None, "não consultada (sem data de contrato)"))
    elif listado is not None:
        itens.append(_item("Vem na listagem por data de contrato", True,
                           f"veio na listagem de {info['dia']} ({info['total']} veículo(s) nesse dia)"))
    elif info["total"] > info["lidos"]:
        itens.append(_item("Vem na listagem por data de contrato", None,
                           f"não veio na 1ª página de {info['dia']} ({info['lidos']} de {info['total']}): "
                           "não dá para afirmar sem ler as outras páginas"))
    else:
        itens.append(_item("Vem na listagem por data de contrato", False,
                           f"o SGA não devolve este veículo na listagem por data de contrato de {info['dia']} "
                           f"({info['total']} veículo(s) nesse dia); a busca completa só enxerga o que vem nela"))

    sit = str(x.get("codigo_situacao") or "")
    desc = str(x.get("descricao_situacao") or "") or sit or "sem situação"
    if d is not None and k < REGRA_ATIVA_DESDE:
        itens.append(_item("Situação ativa", True, f"{desc} (antes de out/26 a situação não conta)"))
    elif sit in ACT_S:
        itens.append(_item("Situação ativa", True, desc))
    elif d is not None and k < mes:
        itens.append(_item("Situação ativa", None, f"hoje está {desc}; a busca ainda conta se estava ativo no fim de "
                                                   f"{_mes_txt(k)} (histórico de situações, não consultado aqui)"))
    else:
        itens.append(_item("Situação ativa", False, f"a situação é {desc} (código {sit or '—'}) e só contam Ativo, Ativo - "
                                                    "Pendente Instalação, Aguardando instalação e Ativo - Dispensa "
                                                    "Instalação"))

    alt = str(x.get("data_alteracao") or "")
    if sit in SAIU and d is not None and alt[:7] == k:
        itens.append(_item("Não saiu no mesmo mês", False, f"ficou {desc} em {_mes_txt(k)}, o mesmo mês do contrato "
                                                           "(pela última alteração no SGA)"))
    else:
        itens.append(_item("Não saiu no mesmo mês", True, "não foi cancelado, retirado nem inativado no mês do contrato"
                           if sit not in SAIU else f"saiu ({desc}) fora do mês do contrato"))

    coop = str(x.get("codigo_cooperativa") or "")
    equipe = COOP.get(coop)
    if equipe:
        itens.append(_item("Equipe (cooperativa)", True, f"cooperativa {coop} = {equipe}"))
    else:
        itens.append(_item("Equipe (cooperativa)", False, f"a cooperativa {coop or '(vazia)'} não é de nenhuma "
                                                          "equipe: a adesão fica sem equipe (só aparece em "
                                                          "\"Todas as equipes\", não na equipe nem para o líder)"))

    vol = str(x.get("nome_voluntario") or "").strip()
    if not vol:
        itens.append(_item("Especialista (voluntário)", None, "sem especialista no SGA: entra como \"sem "
                                                              "especialista\" e não aparece no card de nenhum"))
    else:
        cad = _especialista_cadastrado(db, vol)
        if cad:
            itens.append(_item("Especialista (voluntário)", True, f"{vol} (cadastro: {cad})"))
        else:
            itens.append(_item("Especialista (voluntário)", None, f"{vol}: não bate com nenhum especialista "
                                                                  "importado, então não aparece no card de um "
                                                                  "especialista (aparece no da equipe)"))

    a = _no_pacote(db, x, nome_associado)
    busca = ler(db, "busca") or {}
    quando = busca.get("feita_em") or ""
    try:
        quando_txt = formatar(dt.datetime.fromisoformat(quando)) if quando else ""
    except ValueError:
        quando_txt = ""
    ultima = f" (última busca: {quando_txt})" if quando_txt else ""
    if a is not None:
        itens.append(_item("Está nos dados atuais", True, f"{_mes_txt(a.get('m') or '')}, equipe "
                                                          f"{a.get('t') or 'sem equipe'}, especialista "
                                                          f"{a.get('esp') or 'sem especialista'}{ultima}"))
    else:
        itens.append(_item("Está nos dados atuais", False, f"não está na lista de adesões dos dados atuais{ultima}"))

    falhas = [i for i in itens if i["ok"] is False and i["item"] != "Está nos dados atuais"]
    motivos = "; e ".join(i["texto"] for i in falhas)
    if a is not None and (a.get("m") or "") >= COMP_DESDE:
        conclusao = (f"Tudo certo: aparece em {_mes_txt(a['m'])}, {a.get('t') or 'sem equipe'}, "
                     f"{a.get('esp') or 'sem especialista'}.")
        resumo = f"aparece no card ({a['m']}, {a.get('t') or 'sem equipe'})"
        if falhas:
            conclusao += f" Mas, pelo SGA de hoje, a próxima busca deixaria de fora ({motivos})."
            resumo += "; a próxima busca deixaria de fora: " + ", ".join(i["item"] for i in falhas)
    elif a is not None:
        conclusao = (f"Este veículo fica de fora porque está nos dados de {_mes_txt(a.get('m') or '')}, antes do card "
                     "de comprovantes (outubro de 2026).")
        resumo = "fica de fora: mês antes do card"
    elif falhas:
        conclusao = f"Este veículo fica de fora porque {motivos}."
        resumo = "fica de fora: " + ", ".join(i["item"] for i in falhas)
    else:
        conclusao = ("Este veículo fica de fora porque não está nos dados da última busca, embora cumpra as regras no "
                     "SGA hoje: a próxima busca completa deve incluí-lo" + (" (confira os itens em amarelo)." if any(
                         i["ok"] is None for i in itens) else "."))
        resumo = "fica de fora: não está nos dados atuais, mas cumpre as regras"
    return itens, conclusao, resumo


# ---------------------------------------------------------------- a conferência

def conferir_veiculo(db: Session, cfg: Config, busca: str, *, data: str | None = None, pessoa_id: int | None = None,
                     http=None) -> dict:
    """Respeita a pausa do SGA e a busca completa rodando. `http` só muda nos testes (SGA falso)."""
    campo, valor = campo_da_busca(busca)
    dia = _data_informada(data)
    if not cfg.sga_configurado:
        return {"ok": False, "mensagem": "Os acessos do SGA (SGA_TOKEN, SGA_USUARIO, SGA_SENHA) não estão no Render."}
    trava = trava_ativa(db, TRAVA_SGA)
    if trava is not None:
        return {"ok": False, "mensagem": f"SGA pausado até {formatar(trava.ate)}: {trava.motivo}. Nada foi consultado."}
    if trava_ativa(db, TRAVA_BUSCA) is not None:
        return {"ok": False, "mensagem": "A busca completa está rodando. Espere ela terminar para conferir."}

    a = iniciar(db, "sga", "conferência", pessoa_id)
    sga = ClienteSGA(cfg.sga_token, cfg.sga_usuario, cfg.sga_senha, http=http, limite_chamadas=LIMITE_CHAMADAS,
                     intervalo=INTERVALO)
    avisos: list[str] = []
    try:
        ficha, listado, info = _consultar(sga, campo, valor, dia, avisos)
        x = listado or ficha or {}
        nome = str(x.get("nome") or x.get("nome_associado") or (ficha or {}).get("nome")
                   or (ficha or {}).get("nome_associado") or "")
        itens, conclusao, resumo = diagnosticar(db, ficha, listado, info, agora().astimezone(FUSO).date(), nome)
    except SGABloqueado as e:
        ate = proximo_horario_sga()
        travar(db, TRAVA_SGA, ate, str(e))
        return concluir(db, a, False, f"{e}. Conferência parada. O SGA fica pausado até {formatar(ate)}.")
    except SGAErro as e:
        return concluir(db, a, False, f"Conferência parada: {e}.")
    finally:
        if http is None:
            sga.fechar()
    concluir(db, a, True, f"Conferência de 1 veículo por {campo} ({sga.chamadas} chamada(s) ao SGA): {resumo}.")
    return {"ok": True, "mensagem": conclusao, "conclusao": conclusao, "campo": campo, "chamadas": sga.chamadas,
            "avisos": avisos, "sga": _campos(ficha), "listagem": _campos(listado), "listagem_info": info,
            "diagnostico": itens}
