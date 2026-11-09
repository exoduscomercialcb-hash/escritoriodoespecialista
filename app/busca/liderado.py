"""Adesão no nome do LÍDER no SGA, mas vendida por um LIDERADO (afiliado no Power CRM) -> conta para o liderado.

Regra do Rafael (09/11/2026), porta do `kit/liderado_pc.py` do sistema atual (regras intactas). Exemplo: um liderado da
equipe Elim fez 5 adesões em out/26; 2 foram cadastradas no SGA no nome do líder.

Roda depois do script adaptado (app/busca/retorno.py), sobre os pacotes que ele devolveu:
- muda `ades[].esp` para o liderado e guarda o nome do SGA em `esp_sga` (idempotente: adesão com `esp_sga` não muda de novo);
- acerta as séries `<equipe>|propria`, `<equipe>|liderados` e `<equipe>|lid:<NOME>` (ad e va) e o `vesp` da equipe, no
  pacote geral ("all") e no da equipe ("t:<EQUIPE>");
- o pacote do próprio liderado ("e:<NOME>") recebe as adesões movidas e a série "ALL|equipe";
- toda série fica com `base[]` (série sem base travou o painel dos líderes em 09/11).
O total da equipe não muda. Vale a partir de set/26.

De onde vem o liderado: das cotações do Power CRM que o script já leu (venda concretizada, não arquivada, `nameAffiliate`).
Se o Power CRM falhou nesta busca, vale o que a busca anterior já tinha movido (`esp_sga` no pacote "all" anterior), para a
regra não sumir dos líderes por uma falha do Power CRM.
"""
from __future__ import annotations

import re
from typing import Any

from ..dados import N

DESDE = "2026-09"
PART = {"DE", "DA", "DO", "DOS", "DAS", "E", "DI", "DU"}
CAMPOS = ("ad", "va", "rt", "rv")


def pl_(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", N(s))


def UK(s) -> str:
    return " ".join([w for w in N(s).split() if w not in PART][:2])


def tc(s) -> str:
    return " ".join(w.capitalize() if (w.lower() not in {"de", "da", "do", "dos", "das", "e"}) else w.lower()
                    for w in str(s or "").strip().split())


def zeros(n: int) -> list[int]:
    return [0] * n


def afiliados(cotacoes: list | None) -> dict[str, str]:
    """placa/chassi -> afiliado (liderado) das vendas concretizadas no Power CRM."""
    af: dict[str, str] = {}
    for q in cotacoes or []:
        if str(q.get("cardStatus")) != "5" or str(q.get("isShelved") or "N").upper() == "S":
            continue
        nome = re.sub(r"\s+SGA$", "", str(q.get("nameAffiliate") or "").strip(), flags=re.I)
        if not nome:
            continue
        for k in (pl_(q.get("vehiclePlates")), pl_(q.get("vehicleChassi"))):
            if k:
                af[k] = nome
    return af


def movidas_antes(old: dict | None) -> dict[tuple, str]:
    """(mês, placa ou chassi, nome no SGA) -> liderado, das adesões que a busca anterior já tinha movido."""
    r: dict[tuple, str] = {}
    for a in (old or {}).get("ades") or []:
        if a.get("esp_sga") and a.get("esp"):
            r[(a.get("m"), pl_(a.get("pl")) or pl_(a.get("ch")), N(a["esp_sga"]))] = a["esp"]
    return r


def _nome_lid(af: str, t: str, o: dict, especialistas: list[dict]) -> str:
    """Nome do liderado: o do SGA/cadastro da mesma equipe quando o 1º (e o 2º, se houver) nome batem; senão o do Power CRM."""
    w = [x for x in N(af).split() if x not in PART]
    cands = list(((o.get("vesp") or {}).get(t) or {}).keys()) + [
        N(s["nome"]) for s in especialistas if t in [N(e) for e in (s.get("eqs") or [])]]
    for c in cands:
        cw = [x for x in c.split() if x not in PART]
        if cw and w and cw[0] == w[0] and (len(w) < 2 or w[1] in cw):
            return tc(c)
    return tc(af)


def _tamanho_base(o: dict, am: list) -> int:
    return len(o.get("meses_base") or []) or max(
        [len(z.get("base") or []) for z in (o.get("series") or {}).values()] + [len(am) + 1])


def consertar_base(o: dict) -> int:
    """Toda série precisa de base[] (a página ordena os liderados pela base). Devolve quantas foram consertadas."""
    am = o.get("meses_ad") or []
    nb = _tamanho_base(o, am)
    n = 0
    for s in (o.get("series") or {}).values():
        if isinstance(s, dict) and not isinstance(s.get("base"), list):
            s["base"] = zeros(nb)
            n += 1
    return n


def _roda(o: dict, af: dict, antes: dict, especialistas: list[dict], movidas: list | None, st: dict) -> None:
    am = o.get("meses_ad") or []
    vi = o.get("val_ate", -1)
    va_ate = am[vi] if am else ""
    nb = _tamanho_base(o, am)
    ld = {t: UK(n) for t, n in (o.get("leaders") or {}).items()}
    for a in o.get("ades") or []:
        if (a.get("m") or "") < DESDE or a.get("esp_sga") or a.get("m") not in am:
            continue
        t = a.get("t") or ""
        if not t or ld.get(t) != UK(a.get("esp")):  # só adesão no nome do líder da própria equipe
            continue
        chave = pl_(a.get("pl")) or pl_(a.get("ch"))
        nome_af = af.get(pl_(a.get("pl"))) or af.get(pl_(a.get("ch")))
        if nome_af:
            if UK(nome_af) == UK(a.get("esp")) or N(nome_af).split()[0] == N(a.get("esp")).split()[0]:
                continue
            novo = _nome_lid(nome_af, t, o, especialistas)
        else:
            novo = antes.get((a.get("m"), chave, N(a.get("esp"))))
            if not novo:
                continue
        i = am.index(a["m"])
        okv = 1 if (a.get("ok") and a["m"] <= va_ate) else 0
        ser = o.setdefault("series", {})
        for kk, d in ((t + "|propria", -1), (t + "|liderados", 1), (t + "|lid:" + N(novo), 1)):
            s = ser.get(kk)
            if s is None:
                if d < 0:
                    continue
                s = ser[kk] = dict({f: zeros(len(am)) for f in CAMPOS}, base=zeros(nb))
            s["ad"][i] = max(0, s["ad"][i] + d)
            s["va"][i] = max(0, s["va"][i] + d * okv)
        ve = o.setdefault("vesp", {}).setdefault(t, {})
        zl = ve.get(N(a["esp"]))
        if zl:
            zl["ad"][i] = max(0, zl["ad"][i] - 1)
            zl["va"][i] = max(0, zl["va"][i] - okv)
        zn = ve.setdefault(N(novo), {f: zeros(len(am)) for f in CAMPOS})
        zn["ad"][i] += 1
        zn["va"][i] += okv
        a["esp_sga"] = a["esp"]
        a["esp"] = novo
        st["movidas"] += 1
        if movidas is not None:
            movidas.append(dict(a))
    st["base_corrigida"] += consertar_base(o)


def aplicar(pacotes: dict[str, Any], cotacoes: list | None, old: dict | None, especialistas: list[dict]) -> dict:
    """Aplica a regra nos pacotes (altera no lugar). Devolve um resumo só com números."""
    especialistas = [e for e in especialistas or [] if isinstance(e, dict) and e.get("nome")]
    af = afiliados(cotacoes)
    antes = movidas_antes(old)
    st = {"movidas": 0, "base_corrigida": 0, "no_pacote_do_liderado": 0,
          "fonte": "power_crm" if cotacoes else "busca_anterior"}
    mov: list[dict] = []
    if isinstance(pacotes.get("all"), dict):
        _roda(pacotes["all"], af, antes, especialistas, mov, st)
    for chave, o in pacotes.items():
        if chave.startswith("t:") and isinstance(o, dict):
            _roda(o, af, antes, especialistas, None, st)
    for sk in especialistas:  # liderado com acesso próprio: recebe as adesões movidas
        o = pacotes.get("e:" + N(sk["nome"]))
        if not isinstance(o, dict):
            continue
        sga = {N(x) for x in (sk.get("sga") or [])}
        meus = [a for a in mov if UK(a["esp"]) == UK(sk["nome"]) or N(a["esp"]) in sga]
        if meus:
            am = o.get("meses_ad") or []
            va_ate = am[o.get("val_ate", -1)] if am else ""
            tem = {(a.get("m"), pl_(a.get("pl")) or pl_(a.get("ch"))) for a in o.get("ades") or []}
            s = o.setdefault("series", {}).setdefault("ALL|equipe", {"base": [], "ad": zeros(len(am)), "va": zeros(len(am))})
            for a in meus:
                if (a["m"], pl_(a.get("pl")) or pl_(a.get("ch"))) in tem or a["m"] not in am:
                    continue
                o.setdefault("ades", []).append(a)
                j = am.index(a["m"])
                s["ad"][j] += 1
                if a.get("ok") and a["m"] <= va_ate:
                    s["va"][j] += 1
                st["no_pacote_do_liderado"] += 1
        st["base_corrigida"] += consertar_base(o)
    return st
