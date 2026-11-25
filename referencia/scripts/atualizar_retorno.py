# Retorno Exodus — atualiza as abas "Evolução da base", "Adesões validadas" e "Descontos" direto do SGA (+ Power CRM nos descontos).
# A lista do remarketing e os motivos dela NÃO são alterados (o Rafael atualiza pontualmente).
# Base ativa = Ativo + Ativo - pendente instalação + Aguardando instalação (+ Ativo - dispensa instalação), lida AGORA no SGA:
#   o valor de hoje entra no mês atual; meses fechados ficam com a última leitura feita naquele mês.
# Adesões = ativações do SGA (contratos do mês; sai quem foi cancelado/retirado/inativado no mesmo mês). Recalcula do mês de
#   2 meses atrás até o atual; meses anteriores ficam congelados. Validadas = 1º boleto pago (mês de 2 meses atrás e mês anterior).
# Descontos (set/26 em diante) = ativação do SGA × cotação do Power CRM (data de migração mais próxima).
# Para não estourar o limite de extração do SGA, guarda na página (criptografado) um cache de detalhes de veículos e de validadas.
# Uso: python3 -I atualizar_retorno.py <kit_dir> <pagina_atual.html> <saida.html>   (kit: SGA-REMARKETING.txt, POWERCRM.txt, leader_rings.json)
import sys, os, re, json, time, gzip, base64, hashlib, collections, unicodedata, html as _html
import datetime as dt
import requests
from concurrent.futures import ThreadPoolExecutor
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KIT, PAGE, OUT = sys.argv[1:4]
NOW = dt.datetime.now(dt.timezone(dt.timedelta(hours=-3))); HOJE = NOW.date(); MES = HOJE.strftime("%Y-%m")
B = "https://api.hinova.com.br/api/sga/v2"
log = lambda *a: print(*a, file=sys.stderr, flush=True)
def N(s): return " ".join(unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper().split())
b64d = base64.b64decode; b64e = lambda x: base64.b64encode(x).decode()

# ---------- chaves e dados atuais da página ----------
page = open(PAGE, encoding="utf-8").read()
R = json.load(open(os.path.join(KIT, "leader_rings.json")))
rk = lambda u: b64d(R[u]["keys"][0])
byid = {R[u]["ids"][0]: u for u in R}
ALLKEY = hashlib.sha256(b"evo-all|" + b"".join(rk(byid[i]) for i in [38, 44, 61, 70, 71, 79, 81])).digest()
EV = json.loads(re.search(r'<script id="evo" type="application/json">(.*?)</script>', page, re.S).group(1))
OLD = json.loads(gzip.decompress(AESGCM(ALLKEY).decrypt(b64d(EV["all"]["iv"]), b64d(EV["all"]["c"]), None)))
log("dados anteriores:", OLD["atualizado"], OLD["meses_base"][0], "→", OLD["meses_base"][-1])

# ---------- SGA ----------
def auth():
    t = open(os.path.join(KIT, "SGA-REMARKETING.txt"), encoding="utf-8-sig").read()
    m = re.search(r"TOKEN SGA:\s*(\S+)", t); tok = m.group(1) if m else t.split()[0]
    usr = re.search(r"usuario=\s*(.+)", t).group(1).strip(); pwd = re.search(r"senha=\s*(.+)", t).group(1).strip()
    ult = ""
    for i in range(6):         # o SGA bloqueia o token quando há muita extração: espera 3 min entre tentativas (até ~18 min), sem insistir
        try:
            r = requests.post(B + "/usuario/autenticar", headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"}, json={"usuario": usr, "senha": pwd}, timeout=90)
            ut = r.json().get("token_usuario")
            if ut: return {"Authorization": "Bearer " + ut, "Content-Type": "application/json"}
            ult = "%s %s" % (r.status_code, r.text[:160])
            if "BLOQUEADO" in r.text.upper(): raise SystemExit("SGA BLOQUEADO (excesso de extração) — parado na hora, sem insistir: " + r.text[:120])   # 18/11
        except Exception as e: ult = type(e).__name__
        log("  SGA login recusado:", ult[:90], "— nova tentativa em 3 min")
        time.sleep(180)
    raise SystemExit("Falha ao autenticar no SGA: " + ult)
H = auth(); log("SGA autenticado")
import threading
_RL = threading.Lock(); _ULT = [0.0]; NCALL = collections.Counter()
def ritmo(ep=""):
    """18/11: espaça as chamadas ao SGA (0,35 s entre elas, somando todas as threads) para não estourar o limite de extração"""
    with _RL:
        w = 0.35 - (time.time() - _ULT[0])
        if w > 0: time.sleep(w)
        _ULT[0] = time.time(); NCALL[ep.split("/")[2] if ep.count("/") >= 2 else ep] += 1
def bloqueado(r):
    if r is not None and "BLOQUEADO" in r.text[:400].upper(): raise SystemExit("SGA BLOQUEADO (excesso de extração) — parado na hora, sem insistir")
def reauth(r):
    """renova o login quando o SGA recusa o token (expira depois de alguns minutos)"""
    global H
    if r is not None and (r.status_code in (401, 403) or "token" in r.text[:300].lower()):
        H.clear(); H.update(auth()); log("  login do SGA renovado")
def post(ep, body):
    for i in range(6):
        r = None
        try:
            ritmo(ep); r = requests.post(B + ep, headers=H, json=body, timeout=300)
            if r.ok: return r.json()
            bloqueado(r)
            if r.status_code == 406 and "encontrad" in r.text: return {"veiculos": [], "total_veiculos": 0}   # nenhum veículo nesse filtro
            log("  SGA", ep, r.status_code, r.text[:120]); reauth(r)
        except Exception as e: log("  SGA", ep, type(e).__name__)
        time.sleep(5 * (i + 1))
    raise SystemExit("SGA não respondeu em " + ep)

# páginas de 100 em paralelo (o SGA responde páginas grandes muito devagar); inicio_paginacao = deslocamento
PG = 100
def pagina(arg):
    s, off = arg
    r = post("/listar/veiculo", {"codigo_situacao": s, "inicio_paginacao": off, "quantidade_por_pagina": PG})
    return r.get("veiculos", []) if isinstance(r, dict) else []
ATVD = {}
for s in ["1", "18", "16", "19"]:
    r = post("/listar/veiculo", {"codigo_situacao": s, "inicio_paginacao": 0, "quantidade_por_pagina": PG})
    tot = int(r.get("total_veiculos") or 0) if isinstance(r, dict) else 0
    for x in (r.get("veiculos", []) if isinstance(r, dict) else []): ATVD[x["codigo_veiculo"]] = x
    with ThreadPoolExecutor(3) as ex:
        for vv in ex.map(pagina, [(s, off) for off in range(PG, tot, PG)]):
            for x in vv: ATVD[x["codigo_veiculo"]] = x
    got = sum(1 for x in ATVD.values() if x.get("codigo_situacao") == s)
    log("  situação", s, "total SGA", tot, "lidos", got)
    if got < tot: raise SystemExit("Leitura incompleta da situação %s (%d de %d) — tente de novo" % (s, got, tot))
ATV = list(ATVD.values())
log("base ativa hoje:", len(ATV))

COOP = {"1": "EXODUS BENEFÍCIOS", "2": "LUA", "3": "PÉ NO CHÃO", "4": "ÁGUIAS", "5": "MAGNATAS", "6": "TUBARÕES", "7": "ELIM", "8": "ELITE", "9": "RECREIO"}
NOMES = {"ÁGUIAS": "Águias", "ELIM": "Elim", "ELITE": "Elite", "EXODUS BENEFÍCIOS": "Exodus Benefícios", "LUA": "Lua", "MAGNATAS": "Magnatas", "PÉ NO CHÃO": "Pé no Chão", "RECREIO": "Recreio", "TUBARÕES": "Tubarões"}
LEAD = {"RECREIO": ("RAFAEL VEIGA", "Rafael Veiga", "RAFAEL VEIGA"), "LUA": ("PAULO SERGIO DE OLIVEIRA COSTA", "Paulo Sergio", "PAULO SERGIO"),
        "ELITE": ("RENAN ARAUJO", "Renan Araújo", "RENAN ARAUJO"), "ÁGUIAS": ("JOAO VITOR DE LIMA MENEZES", "João Vitor", "JOAO VITOR"),
        "PÉ NO CHÃO": ("MARCO AURELIO EVARISTO DE OLIVEIRA", "Marco Aurélio", "MARCO AURELIO"), "TUBARÕES": ("PEDRO GABRIEL DIAS VIEIRA DE OLIVEIRA", "Pedro Gabriel", "PEDRO GABRIEL"),
        "MAGNATAS": ("GUILHERME VASCONCELLOS DE SOUZA JUNIOR", "Guilherme Vasconcellos", "GUILHERME VASCONCELLOS"),
        "ELIM": ("VINICIUS FILEMO", "Vinícius Filemo", "VINICIUS FILEMO")}
LNAMES = {N(nm): t for t, (nm, _, _) in LEAD.items()}
cur = collections.Counter()
for v in ATV:
    team = COOP.get(v.get("codigo_cooperativa")); en = N(v.get("nome_voluntario")) or "SEM ESPECIALISTA"
    cur["ALL|equipe"] += 1
    if team: cur[team + "|equipe"] += 1
    lt = LNAMES.get(en)
    if lt: cur[lt + "|propria"] += 1
    if team in LEAD and lt != team:
        cur[team + "|liderados"] += 1; cur[team + "|lid:" + en] += 1
    cur["ESP|" + en] += 1                                 # base própria de cada especialista

# ---------- série da base: hoje no mês atual; meses fechados mantidos ----------
mb = list(OLD["meses_base"]); S0 = OLD["series"]
if mb[-1] != MES:
    mb.append(MES)
    for k in S0: S0[k]["base"].append(0)
SERIES = {}
for k in set(S0) | set(cur):
    old = (list(S0.get(k, {}).get("base", [])) + [0] * len(mb))[:len(mb)]
    if len(S0.get(k, {}).get("base", [])) < len(mb):   # chave nova: completa o começo com zeros
        old = [0] * (len(mb) - len(S0.get(k, {}).get("base", []))) + list(S0.get(k, {}).get("base", []))
    old[-1] = cur.get(k, 0)
    SERIES[k] = {"base": old}

# ---------- histórico de situações (SGA): serve p/ ativações que saíram no mesmo mês e p/ os cancelados ----------
CMAP = {N(n): n for n in COOP.values()}; CMAP["INSIDE SALES"] = "EXODUS BENEFÍCIOS"
AM = list(mb[1:])                                # base[j] = mês anterior, base[j+1] = mês da adesão
cut = ((HOJE.replace(day=1) - dt.timedelta(days=1)).replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")   # validadas só até 2 meses atrás
LIVE = [k for k in AM if k >= cut]               # meses recalculados no SGA; os anteriores ficam congelados
prevm = (HOJE.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
VALMS = [k for k in (cut, prevm) if k in AM]     # validação do 1º boleto: mês de 2 meses atrás e o mês anterior
VALMA = VALMS + ([MES] if MES in AM and MES not in VALMS else [])   # + mês atual (parcial: muitos 1º boletos ainda vão vencer)
MOT = {x["codigo"]: x["descricao"] for x in requests.get(B + "/listar/situacaomotivo/ativo", headers=H, timeout=60).json()}
ini = (HOJE.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
d = (min(ini, dt.date.fromisoformat(cut + "-01")) - dt.timedelta(days=120)).replace(day=1)
HIST = collections.defaultdict(list)
while d <= HOJE:
    f = min(d + dt.timedelta(days=29), HOJE); p = 0
    while True:
        it = post("/listar/alteracao-veiculos", {"data_inicial": d.strftime("%d/%m/%Y"), "data_final": f.strftime("%d/%m/%Y"), "campos": ["codigo_situacao"], "quantidade_por_pagina": 1000, "inicio_paginacao": p})
        if not isinstance(it, list): it = []
        for x in it:
            HIST[x["codigo_veiculo"]].append((x["data_alteracao"][:10] + " " + x["hora_alteracao"], x["valor_anterior"], x["valor_posterior"], str(x.get("codigo_situacaomotivo") or ""), (x.get("observacao") or "").strip()))
        if len(it) < 1000: break
        p += 1
    log("  histórico", d, "ok")
    d = f + dt.timedelta(days=1)
for k in HIST: HIST[k].sort()
if not HIST: raise SystemExit("Histórico de situações do SGA veio vazio — nada foi publicado")

# detalhes de veículos (cache guardado na própria página: o que já foi consultado não é consultado de novo)
DET = dict(OLD.get("det") or {})
DKEEP = ("nome", "nome_associado", "ddd_celular", "telefone_celular", "placa", "chassi", "modelo", "ano_modelo", "tipo", "categoria", "codigo_associado", "nome_voluntario", "codigo_cooperativa", "codigo_situacao", "descricao_situacao", "cpf")
def busca(cv):
    for i in range(4):
        try:
            ritmo("/veiculo/buscar"); r = requests.get(B + f"/veiculo/buscar/{cv}/codigo", headers=H, timeout=120)
            if r.ok:
                j = r.json(); j = j[0] if isinstance(j, list) and j else None
                return {k: j.get(k) for k in DKEEP} if j else None
            if r.status_code in (404, 406): return None
            reauth(r)
        except Exception: pass
        time.sleep(5 * (i + 1))
    return None
FICHAS_MAX = [150]   # 18/11: no máximo 150 fichas novas por atualização (as fichas eram a maior causa dos bloqueios do SGA)
def detalhes(cvs):
    falta = [cv for cv in dict.fromkeys(cvs) if str(cv) not in DET]
    if len(falta) > FICHAS_MAX[0]: log("  fichas novas limitadas:", len(falta), "→", FICHAS_MAX[0], "(o resto entra nas próximas atualizações)"); falta = falta[:FICHAS_MAX[0]]
    FICHAS_MAX[0] -= len(falta)
    if falta:
        with ThreadPoolExecutor(2) as ex:
            for cv, x in zip(falta, ex.map(busca, falta)):
                if x: DET[str(cv)] = x
    log("  detalhes de veículos:", len(falta), "consultados no SGA,", len(set(map(str, cvs))) - len(falta), "do cache")

# ---------- ativações (adesões) dos meses abertos, direto do SGA ----------
# regra: contratos do mês; se o veículo foi cancelado/retirado/inativado no mesmo mês do contrato, não entra
SAIU = {"6", "10", "2"}
def saiu_no_mes(x, k):
    if str(x.get("codigo_situacao")) not in SAIU: return False
    c = str(x.get("data_contrato") or "")[:10]
    for h in HIST.get(x["codigo_veiculo"], []):
        if h[0][:10] >= c and h[2] in SAIU: return h[0][:7] == k
    return str(x.get("data_alteracao") or "")[:7] == k
ACT_S = {"1", "18", "16", "19"}                    # Ativo, Ativo - Pendente Instalação, Aguardando instalação, Ativo - Dispensa Instalação
def sit_fim(x, k):
    """situação do veículo no fim do mês k (no mês atual, a situação de agora) — mesma regra do KPI COMERCIAL"""
    y_, m_ = map(int, k.split("-")); fim = (dt.date(y_, m_, 1).replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    corte = fim.strftime("%Y-%m-%d") + " 00:00:00"
    for h in HIST.get(x["codigo_veiculo"], []):
        if h[0] >= corte: return str(h[1])
    return str(x.get("codigo_situacao"))
ATIV = {}
for k in LIVE:
    y_, mo_ = map(int, k.split("-"))
    d0 = dt.date(y_, mo_, 1); d1 = min(HOJE, (d0.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1))
    base_q = {"data_contrato": d0.strftime("%d/%m/%Y"), "data_contrato_final": d1.strftime("%d/%m/%Y"), "quantidade_por_pagina": PG}
    r0 = post("/listar/veiculo", dict(base_q, inicio_paginacao=0))
    tot = int(r0.get("total_veiculos") or 0) if isinstance(r0, dict) else 0
    vs = {x["codigo_veiculo"]: x for x in (r0.get("veiculos", []) if isinstance(r0, dict) else [])}
    def pag_c(off):
        r_ = post("/listar/veiculo", dict(base_q, inicio_paginacao=off))
        return r_.get("veiculos", []) if isinstance(r_, dict) else []
    with ThreadPoolExecutor(3) as ex:
        for vv in ex.map(pag_c, range(PG, tot, PG)):
            for x in vv: vs[x["codigo_veiculo"]] = x
    if len(vs) < tot: raise SystemExit("Leitura incompleta dos contratos de %s (%d de %d) — tente de novo" % (k, len(vs), tot))
    ativa = lambda x: k < "2026-10" or sit_fim(x, k) in ACT_S or str(x.get("codigo_situacao")) in ACT_S   # a partir de out/26 (regra do KPI COMERCIAL): ativo no fim do mês ou hoje; fica fora quem nunca ficou ativo (inadimplente, pendente, recusado...)
    lst = [x for x in vs.values() if str(x.get("data_contrato") or "")[:7] == k and not saiu_no_mes(x, k) and ativa(x)]
    fora = collections.Counter(str(x.get("descricao_situacao") or x.get("codigo_situacao")) for x in vs.values() if str(x.get("data_contrato") or "")[:7] == k and not saiu_no_mes(x, k) and not ativa(x))
    if fora: log("  fora da contagem em", k, "(não ativos no fim do mês):", dict(fora))
    ATIV[k] = lst
    log("  ativações do SGA em", k, ":", len(lst), "de", tot, "contratos")

def chaves(x):
    team = COOP.get(str(x.get("codigo_cooperativa"))); e = N(x.get("nome_voluntario")) or "SEM ESPECIALISTA"
    ks = ["ALL|equipe"] + ([team + "|equipe"] if team else [])
    lt = LNAMES.get(e)
    if lt: ks.append(lt + "|propria")
    if team in LEAD and lt != team: ks += [team + "|liderados", team + "|lid:" + e]
    ks.append("ESP|" + e)
    return team, e, ks

# ---------- validação do mês de 2 meses atrás: 1º boleto da adesão pago no SGA ----------
def pl_(s): return re.sub(r"[^A-Z0-9]", "", N(s))
def dia(v):
    s = str(v or "").strip()
    try:
        m_ = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
        if m_: return dt.date(int(m_[1]), int(m_[2]), int(m_[3]))
        m_ = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
        return dt.date(int(m_[3]), int(m_[2]), int(m_[1])) if m_ else None
    except ValueError: return None                 # datas vazias do SGA (0000-00-00)
VC = OLD.get("vcache") if isinstance(OLD.get("vcache"), dict) else {}   # adesões já validadas (pago não volta atrás)
VC = dict(VC)
VP = {k: v for k, v in (OLD.get("vpend") or {}).items() if isinstance(v, dict) and str(v.get("venc", "")) > HOJE.isoformat()}   # 18/11: 1º boleto ainda não vencido
ultimo = {}
for k in LIVE:
    for x in ATIV[k]:
        p_ = pl_(x.get("placa"))
        if p_: ultimo[p_] = max(ultimo.get(p_, ""), str(x.get("data_contrato"))[:10])
def boletos(body):
    for i in range(4):
        r = None
        try:
            ritmo("/listar/boleto-associado-veiculo"); r = requests.post(B + "/listar/boleto-associado-veiculo", headers=H, json=body, timeout=120)
            if r.ok: j = r.json(); return j if isinstance(j, list) else []
            bloqueado(r)
            if r.status_code in (404, 406) and ("encontrad" in r.text.lower() or "nenhum" in r.text.lower()): return []
            reauth(r)
        except Exception: pass
        time.sleep(5 * (i + 1))
    return None
def valida(x):
    cv = str(x["codigo_veiculo"]); c = dia(x.get("data_contrato")); pl = pl_(x.get("placa"))
    ck = cv + "|" + c.isoformat()
    if ck in VC: return dict(VC[ck], cache=True)
    vp_ = VP.get(ck)
    if vp_ and str(vp_.get("venc", "")) > HOJE.isoformat() and str(vp_.get("at", "")) >= (HOJE - dt.timedelta(days=3)).isoformat():
        return dict({k_: v_ for k_, v_ in vp_.items() if k_ != "at"}, cache=True)   # ainda não venceu e foi conferido há pouco: não consulta o SGA
    if pl and ultimo.get(pl, "") > c.isoformat(): return {"ok": False, "mot": "nova adesão do mesmo veículo"}
    fim = c + dt.timedelta(days=150)          # o 1º boleto pode vencer depois de hoje (ex.: contrato do fim do mês passado)
    body = {"data_vencimento_inicial": c.strftime("%d/%m/%Y"), "data_vencimento_final": fim.strftime("%d/%m/%Y")}
    if pl: body["placa"] = pl
    else:
        de = DET.get(cv) or {}
        if not de.get("codigo_associado"): return {"ok": False, "mot": "sem placa e sem associado no SGA"}
        body["codigo_associado"] = str(de["codigo_associado"])
    bs = boletos(body)
    if bs is None: return {"ok": False, "mot": "erro SGA"}
    def meu(b):
        vs = b.get("veiculos") or []
        if not vs: return True
        return any((pl and pl_(v.get("placa")) == pl) or str(v.get("codigo_veiculo")) == cv for v in vs)
    Nn = None
    for b in bs:
        for v in (b.get("veiculos") or []):
            if (pl and pl_(v.get("placa")) == pl) or str(v.get("codigo_veiculo")) == cv:
                i_ = dia(v.get("data_inicio_contrato_veiculo"))
                if i_ and i_ > c + dt.timedelta(days=5): Nn = max(Nn or i_, i_)
    cand = []
    for b in bs:
        if not meu(b): continue
        vo = dia(b.get("data_vencimento_original")) or dia(b.get("data_vencimento"))
        if vo and vo >= c and (Nn is None or vo < Nn): cand.append((vo, dia(b.get("data_emissao")) or vo, b))
    if not cand: return {"ok": False, "mot": "nova adesão do mesmo veículo" if Nn else "sem boleto após o contrato", "sb": "1º boleto não emitido"}
    cand.sort(key=lambda t: (t[0], t[1]))
    sit_ = lambda b: N(b.get("situacao_boleto") or b.get("descricao_situacao_boleto"))
    vivos = [t for t in cand if sit_(t[2]) != "CANCELADO"]          # boleto cancelado é reemitido: o novo é que vale
    if not vivos: return {"ok": False, "mot": "boleto cancelado, sem outro emitido", "sb": "Cancelado (sem novo boleto)", "venc": cand[0][0].isoformat()}
    vo, _, b = vivos[0]; pg = dia(b.get("data_pagamento")); s_ = sit_(b)
    if s_ == "BAIXADO" and pg and pg >= c: return {"ok": True, "pg": pg.isoformat()}
    return {"ok": False, "mot": "1º boleto não pago", "sb": "Em aberto" if s_ in ("ABERTO", "") else s_.capitalize(), "venc": vo.isoformat()}
VALR = {}
try: REGV = (json.load(open(os.path.join(KIT, "comp_marks.json"), encoding="utf-8")) or {}).get("regras") or {}   # validação manual do coordenador: {"val": true, "forma": "cartão de crédito"}
except Exception: REGV = {}
for vm in VALMA:
    alvo = ATIV.get(vm, [])
    detalhes([x["codigo_veiculo"] for x in alvo if not pl_(x.get("placa"))])
    with ThreadPoolExecutor(2) as ex:
        for x, r_ in zip(alvo, ex.map(valida, alvo)): VALR[str(x["codigo_veiculo"])] = r_
    for x in alvo:                                # pago fora do boleto (ex.: cartão de crédito com comprovante): conta como validada
        rg_ = REGV.get(pl_(x.get("placa"))) or {}
        if rg_.get("val") and not VALR[str(x["codigo_veiculo"])]["ok"] and (not rg_.get("mes") or rg_["mes"] == vm):
            VALR[str(x["codigo_veiculo"])] = {"ok": True, "pg": rg_.get("pgd") or "", "forma": rg_.get("forma") or "cartão de crédito", "man": True}
    for x in alvo:
        r_ = VALR[str(x["codigo_veiculo"])]
        if r_["ok"] and not r_.get("man"): VC[str(x["codigo_veiculo"]) + "|" + str(x.get("data_contrato"))[:10]] = {"ok": True, "pg": r_["pg"]}
        elif not r_["ok"] and str(r_.get("venc", "")) > HOJE.isoformat() and not r_.get("cache"):
            VP[str(x["codigo_veiculo"]) + "|" + str(x.get("data_contrato"))[:10]] = {k_: v_ for k_, v_ in r_.items() if k_ in ("ok", "mot", "sb", "venc")} | {"at": HOJE.isoformat()}
    log("  validação", vm, ":", sum(1 for x in alvo if VALR[str(x["codigo_veiculo"])]["ok"]), "de", len(alvo), "validadas |", dict(collections.Counter(VALR[str(x["codigo_veiculo"])].get("mot", "1º boleto pago") for x in alvo)))

# ---------- séries de adesões / validadas: meses abertos do SGA, anteriores congelados ----------
OAM = OLD.get("meses_ad") or []
def realinha(arr):
    m_ = dict(zip(OAM, arr or [])); return [m_.get(k, 0) if k not in LIVE else 0 for k in AM]
for k_, s_ in SERIES.items():
    o_ = S0.get(k_, {}); s_["ad"] = realinha(o_.get("ad")); s_["va"] = realinha(o_.get("va"))
VESP = collections.defaultdict(dict)
for t_, o_ in (OLD.get("vesp") or {}).items():
    for e_, z in o_.items(): VESP[t_][e_] = {"ad": realinha(z.get("ad")), "va": realinha(z.get("va"))}
for k in LIVE:
    i = AM.index(k)
    for x in ATIV[k]:
        team, e, ks = chaves(x); ok = k in VALMA and VALR.get(str(x["codigo_veiculo"]), {}).get("ok")
        for kk in ks:
            s_ = SERIES.setdefault(kk, {"base": [0] * len(mb), "ad": [0] * len(AM), "va": [0] * len(AM)})
            s_["ad"][i] += 1
            if ok: s_["va"][i] += 1
        if team:
            z = VESP[team].setdefault(e, {"ad": [0] * len(AM), "va": [0] * len(AM)}); z["ad"][i] += 1
            if ok: z["va"][i] += 1
for s_ in SERIES.values():
    s_.setdefault("ad", [0] * len(AM)); s_.setdefault("va", [0] * len(AM))
# ---------- reativações (lista do financeiro × print do líder): somam nas adesões do líder no mês da lista ----------
REAT = list(OLD.get("reat") or [])
# 14/11: a reativação é validada quando o boleto SEGUINTE (vencimento a partir do mês depois do mês da lista) é pago no SGA.
# Antes a lista só era copiada da atualização anterior e ficava parada em "Aguardando 2º boleto" mesmo com o boleto pago.
def reat_confere(r):
    br_ = lambda s: "/".join(reversed(s.split("-"))) if s else ""
    k = r.get("mes") or ""; pl = pl_(r.get("pl"))
    if not pl or not re.match(r"\d{4}-\d{2}$", k): return
    y_, m_ = map(int, k.split("-")); d0 = dt.date(y_ + (m_ == 12), m_ % 12 + 1, 1)
    if d0 > HOJE: return
    bs = boletos({"placa": pl, "data_vencimento_inicial": d0.strftime("%d/%m/%Y"), "data_vencimento_final": (d0 + dt.timedelta(days=150)).strftime("%d/%m/%Y")})
    if bs is None: return                                  # SGA falhou: fica como estava
    sit_ = lambda b: N(b.get("situacao_boleto") or b.get("descricao_situacao_boleto"))
    vivos = sorted([((dia(b.get("data_vencimento_original")) or dia(b.get("data_vencimento"))), b) for b in bs if sit_(b) != "CANCELADO"], key=lambda t: (t[0] or HOJE))
    pagos = [(v, b) for v, b in vivos if sit_(b) == "BAIXADO" and dia(b.get("data_pagamento"))]
    if pagos:
        v, b = pagos[0]; r.update(val=True, venc=br_(v.isoformat()) if v else "", sb="Pago em " + br_(dia(b.get("data_pagamento")).isoformat()))
    elif vivos:
        v, b = vivos[0]; r.update(venc=br_(v.isoformat()) if v else "", sb=("Vencido" if v and v < HOJE else "Em aberto"))
for r in REAT:
    if not r.get("val") and r.get("mes") in LIVE:
        try: reat_confere(r)
        except Exception as e_: log("  reativação", r.get("pl"), "não conferida:", type(e_).__name__)
log("reativações conferidas no SGA:", sum(1 for r in REAT if r.get("mes") in LIVE), "| validadas:", sum(1 for r in REAT if r.get("val")))
for r in REAT:
    k = r.get("mes")
    if k not in LIVE or k not in AM: continue            # meses congelados já carregam a soma
    i = AM.index(k); t_ = r.get("t"); ok = bool(r.get("val")) and k in VALMA
    for kk in ["ALL|equipe", t_ + "|equipe", t_ + "|propria"]:
        s_ = SERIES.setdefault(kk, {"base": [0] * len(mb), "ad": [0] * len(AM), "va": [0] * len(AM)})
        s_["ad"][i] += 1
        if ok: s_["va"][i] += 1
    z = VESP[t_].setdefault(N(r.get("esp_n") or r.get("esp")), {"ad": [0] * len(AM), "va": [0] * len(AM)}); z["ad"][i] += 1
    if ok: z["va"][i] += 1
# regra do Rafael (05/11): reativação NÃO entra em adesões nem na taxa de validação; só soma no bônus.
# ad/va continuam com a soma (meses fechados já vêm assim); rt/rv = reativações (e validadas) por mês, a página desconta.
for s_ in SERIES.values(): s_["rt"] = [0] * len(AM); s_["rv"] = [0] * len(AM)
for t_, o_ in VESP.items():
    for z in o_.values(): z["rt"] = [0] * len(AM); z["rv"] = [0] * len(AM)
for r in REAT:
    k = r.get("mes")
    if k not in AM: continue
    i = AM.index(k); t_ = r.get("t"); v_ = 1 if (r.get("val") and (k not in LIVE or k in VALMA)) else 0
    for kk in ["ALL|equipe", t_ + "|equipe", t_ + "|propria"]:
        if kk in SERIES: SERIES[kk]["rt"][i] += 1; SERIES[kk]["rv"][i] += v_
    z = VESP.get(t_, {}).get(N(r.get("esp_n") or r.get("esp")))
    if z: z["rt"][i] += 1; z["rv"][i] += v_
if REAT: log("reativações lançadas:", len(REAT))
log("adesões", AM[0], "→", AM[-1], "| recalculados no SGA:", LIVE, "| validadas até", VALMS[-1] if VALMS else cut)

LIDB = {t: n for t, (_, n, _) in LEAD.items()}; LIDB["ELIM"] = "Vinícius Filemo"   # bônus do líder
# lista do 1º boleto pendente (mês de 2 meses atrás)
PEND = OLD.get("pend")
if VALMS:
    pend = [x for vm in VALMS for x in ATIV.get(vm, []) if not VALR[str(x["codigo_veiculo"])]["ok"] and VALR[str(x["codigo_veiculo"])].get("mot") != "nova adesão do mesmo veículo"]
    detalhes([x["codigo_veiculo"] for x in pend])
    def tc(x): return " ".join(w if w.lower() in ("de", "da", "do", "dos", "das", "e") else w.capitalize() for w in str(x or "").lower().split())
    rows_ = []
    for x in pend:
        r_ = VALR[str(x["codigo_veiculo"])]; de = DET.get(str(x["codigo_veiculo"])) or {}
        dig = "".join(c for c in str(de.get("ddd_celular") or "") + str(de.get("telefone_celular") or "") if c.isdigit())
        tel = "(%s) %s-%s" % (dig[:2], dig[2:-4], dig[-4:]) if len(dig) in (10, 11) else ""
        br_ = lambda s: "/".join(reversed(s.split("-"))) if s else ""
        rows_.append({"n": tc(de.get("nome") or de.get("nome_associado")), "tel": tel, "esp": tc(x.get("nome_voluntario")), "t": COOP.get(str(x.get("codigo_cooperativa")), ""),
                      "pl": x.get("placa") or "", "dc": br_(str(x.get("data_contrato"))[:10]), "venc": br_(r_.get("venc", "")), "sb": r_.get("sb") or r_.get("mot", ""),
                      "ss": tc(x.get("descricao_situacao") or de.get("descricao_situacao"))})
    rows_ += [dict(r, tipo="reat") for r in REAT if r.get("mes") in VALMS + LIVE]
    PEND = {"mes": VALMS[-1], "meses": VALMS, "at": int(time.time() * 1000), "fora": "", "rows": rows_}
    log("1º boleto pendente:", VALMS, len(rows_), "adesões")

# ---------- descontos (set/26 em diante): ativações do SGA × cotação do Power CRM ----------
PLANTAO = {"2026-09": [("2026-09-26", "2026-09-30")]}   # meses sem regra informada = tudo fora do plantão
try: REGRAS = (json.load(open(os.path.join(KIT, "comp_marks.json"), encoding="utf-8")) or {}).get("regras") or {}   # lista do coordenador por placa: plt = desconto conta como plantão; nc/obs = instalação não cobrada
except Exception: REGRAS = {}
def plt_(x):   # lista do coordenador: plantão por placa; sem placa, pelo chassi ou NOME:<nome> (plantão 30-31/10/2026 tinha veículos sem placa)
    de = (globals().get("DET") or {}).get(str(x.get("codigo_veiculo"))) or {}
    nm = N(x.get("nome") or x.get("nome_associado") or de.get("nome") or de.get("nome_associado"))
    for kk in (pl_(x.get("placa")), pl_(x.get("chassi") or de.get("chassi")), "NOME:" + nm if nm else ""):
        if kk and (REGRAS.get(kk) or {}).get("plt"): return True
    return False
# Plantão por condição (Rafael, 14/11): quando a equipe tem "min" ativações ou mais no mês, o desconto destes associados
# conta como plantão (não entra na meta). Nome do associado no SGA ou no Power CRM; vale o começo do nome.
PLT_COND = [{"t": "MAGNATAS", "min": 25, "desde": "2026-10", "nomes": ["<NOME DO ASSOCIADO 1>", "<NOME DO ASSOCIADO 2>"]}]   # cópia: nomes tirados (dado pessoal); no sistema novo vêm do pacote plt_cond
def plt_cond(x, k, nome_extra=""):
    t_ = COOP.get(str(x.get("codigo_cooperativa")), "")
    de = (globals().get("DET") or {}).get(str(x.get("codigo_veiculo"))) or {}
    nomes = {N(x.get("nome") or x.get("nome_associado") or de.get("nome") or de.get("nome_associado")), N(nome_extra)}
    for c in PLT_COND:
        if t_ != c["t"] or k < c.get("desde", ""): continue
        if sum(1 for y in ATIV.get(k, []) if COOP.get(str(y.get("codigo_cooperativa")), "") == t_) < c["min"]: continue
        if any(n and any(n.startswith(p) for p in c["nomes"]) for n in nomes): return True
    return False
DESDE = "2026-09"
DESC = OLD.get("desc") or {"d": {}, "tk": {}}
QM = {}
try: LDC = [x["ld"] for x in json.load(open(os.path.join(KIT, "spec_keys.json"), encoding="utf-8")) if (x.get("ld") or {}).get("pc")]
except Exception: LDC = []
# 19/11 (Rafael): aba "CRÉDITOS FIXADOS" da planilha Ativação Inside Sales = venda fechada pela Camila/Nalva e transferida a outro especialista
# a pedido da diretoria. Fica com o especialista de destino E é duplicada para a vendedora interna (adesões, validadas, comprovantes, gráficos).
def _fixc():
    try: L_ = json.load(open(os.path.join(KIT, "creditos_fixados.json"), encoding="utf-8"))
    except Exception: return {}
    d_ = {}
    for f_ in L_:
        for key_ in (["cv:" + str(f_["cv"])] if f_.get("cv") else []) + (["pl:" + pl_(f_["placa"])] if f_.get("placa") else []) + (["n:" + N(f_["nome"])] if f_.get("nome") else []): d_[key_] = f_
    return d_
FIXC = _fixc()
VI_CART = {N(x["cart"]) for x in LDC}          # voluntário da carteira das vendedoras internas (Power CRM diz quem fechou)
VIMAP = dict(OLD.get("vimap") or {})            # veículo da carteira -> vendedor no Power CRM ("" = sem cotação)
ATVD_CV = {str(x["codigo_veiculo"]) for x in ATV}
dlive = [k for k in LIVE if k >= DESDE]
try:
    PT = re.search(r"([A-Za-z0-9._-]{20,})", open(os.path.join(KIT, "POWERCRM.txt"), encoding="utf-8-sig").read()).group(1)
    PH = {"Authorization": "Bearer " + PT, "Content-Type": "application/json"}
    def pc_page(f_, t_, pg):
        for i in range(5):
            try:
                r = requests.post("https://api.powercrm.com.br/api/report/db/paginated", headers=PH, json={"from": f_, "to": t_, "page": pg, "stringFilterTypeDate": 1}, timeout=300)
                return r.json().get("items", [])
            except Exception: time.sleep(5 * (i + 1))
        raise RuntimeError("Power CRM não respondeu")
    COT = {}
    y_, mo_ = map(int, min(dlive).split("-")); mo_ -= 6
    while mo_ < 1: mo_ += 12; y_ -= 1
    d0 = dt.date(y_, mo_, 1)
    if VI_CART and not OLD.get("vimap"): d0 = dt.date(2024, 7, 1)     # 1ª vez: histórico todo do Power CRM p/ saber de quem é a base da carteira
    while d0 <= HOJE:
        d1 = min(HOJE, (d0.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)); pg = 0
        while True:
            it = pc_page(d0.isoformat(), d1.isoformat(), pg)
            novos = [x for x in it if x.get("quotationCode") not in COT]
            if not novos: break
            for x in novos: COT[x["quotationCode"]] = x
            pg += 1
        d0 = d1 + dt.timedelta(days=1)
    log("  Power CRM:", len(COT), "cotações")
    # 16/11: o Power CRM respondeu erro 500 e a atualização saiu com 0 cotações (descontos e cotações zerados). Sem cotação, nada é publicado.
    if len(COT) < 100: raise SystemExit("Power CRM não respondeu (só %d cotações) — nada foi publicado; tente mais tarde" % len(COT))
    def dbr(s):
        m_ = re.match(r"(\d{2})/(\d{2})/(\d{4})", str(s or "")); return dt.date(int(m_[3]), int(m_[2]), int(m_[1])) if m_ else None
    def brl(s):
        s = str(s or "").replace("R$", "").replace("\xa0", "").strip()
        if not s or s in ("-", "None"): return 0.0
        try: return float(s.replace(".", "").replace(",", ".")) if "," in s else float(s)
        except ValueError: return 0.0
    porP, porC, porN = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    # regra do Rafael (01/11): só valem as cotações em VENDA CONCRETIZADA (cardStatus 5); arquivadas e as das outras etapas ficam fora
    VCOT = [q for q in COT.values() if str(q.get("cardStatus")) == "5" and str(q.get("isShelved") or "N").upper() != "S"]   # (não usar o nome VC: é o cache das validadas)
    log("  Power CRM: vendas concretizadas", len(VCOT), "de", len(COT), "cotações")
    for q in VCOT:
        if pl_(q.get("vehiclePlates")): porP[pl_(q.get("vehiclePlates"))].append(q)
        if pl_(q.get("vehicleChassi")): porC[pl_(q.get("vehicleChassi"))].append(q)
        if N(q.get("clientName")): porN[N(q.get("clientName"))].append(q)
    def cotacao(x):
        c = dia(x.get("data_contrato")); cv = str(x["codigo_veiculo"]); qs = porP.get(pl_(x.get("placa")), [])
        if not qs:
            de = DET.get(cv) or {}
            qs = porC.get(pl_(de.get("chassi")), []) or porN.get(N(de.get("nome") or de.get("nome_associado")), [])
        if not qs: return None
        def dist(q):
            mg = dbr(q.get("sentToHinovaDate")) or dbr(q.get("hinovaSentDate"))
            return (0 if mg else 1, abs((mg - c).days) if mg else abs(((dbr(q.get("createdDate")) or c) - c).days))
        return min(qs, key=dist)
    RXP = re.compile(r"(\d{1,2}(?:[.,]\d+)?)\s*%\s*(?:de\s+)?desconto|desconto\s+(?:aplicado\s+)?(?:de\s+)?(\d{1,2}(?:[.,]\d+)?)\s*%", re.I)
    def desconto(q):
        cota = brl(q.get("monthlyPaymentsPrice")); obs = str(q.get("observationsDatabase") or "")
        if "GUZZI" in N(q.get("vehicleBrand")) + N(q.get("vehicleModel")) and "CALIFORNIA" in N(q.get("vehicleModel")):
            m_ = re.search(r"desconto[^0-9R$]*(?:R\$\s*)?(\d+(?:[.,]\d{1,2})?)", obs, re.I)
            return cota, (float(m_[1].replace(",", ".")) if m_ else 0.0)
        dv = brl(q.get("monthlyPaymentDiscount"))
        if dv > 0: return cota, dv
        for m_ in RXP.finditer(obs):
            ctx = N(obs[max(0, m_.start() - 40):m_.end() + 40])
            if re.search(r"BOLETO|INDICA|PRIMEIR|1\s*O\b|1º|PARCELA|ADESAO", ctx): continue
            pct = float((m_[1] or m_[2]).replace(",", ".")) / 100
            if 0 < pct < 1: return cota, round(cota * pct, 2)
        return cota, 0.0
    def plantao(c):
        return any(a <= c.isoformat() <= b for a, b in PLANTAO.get(c.strftime("%Y-%m"), []))
    sem = 0
    for k in dlive:
        dd, tk = {}, {}
        for x in ATIV[k]:
            t_ = COOP.get(str(x.get("codigo_cooperativa")), "SEM EQUIPE"); v_ = dd.setdefault(t_, [0, 0, 0, 0]); v_[0] += 1
            q = cotacao(x)
            if not q: sem += 1; continue
            cota, dv = desconto(q)
            if dv > 0: v_[1 if plantao(dia(x.get("data_contrato"))) or plt_(x) or plt_cond(x, k, q.get("clientName")) else 2] += 1
            if cota > 0: z = tk.setdefault(t_, [0.0, 0]); z[0] = round(z[0] + cota - dv, 2); z[1] += 1
        DESC["d"][k] = dd; DESC["tk"][k] = tk
        log("  descontos", k, ":", sum(v[0] for v in dd.values()), "ativações,", sum(v[1] + v[2] for v in dd.values()), "com desconto")
    DESC.update(ate=HOJE.strftime("%d/%m/%Y"), desde=DESDE)
    log("descontos:", dlive, "| ativações sem cotação no Power CRM:", sem)
    for k in LIVE:                                   # cotação de cada ativação (nome, telefone, mensalidade e desconto p/ as listas)
        for x in ATIV[k]:
            q = cotacao(x)
            if q:
                cota, dv = desconto(q)
                QM[str(x["codigo_veiculo"])] = {"n": q.get("clientName"), "tel": q.get("clientMobile"), "cota": cota, "dv": dv, "vs": N(q.get("responsibleSalesman")), "cid": q.get("clientCity") or ""}
    if VI_CART:                                      # base da carteira por vendedora: cotação mais recente enviada ao SGA (placa ou chassi)
        def ult(qs):
            def kk(q):
                d_ = dbr(q.get("sentToHinovaDate")) or dbr(q.get("hinovaSentDate"))
                return (1 if d_ else 0, d_ or dt.date(1900, 1, 1))
            return max(qs, key=kk) if qs else None
        for x in ATV:
            cv = str(x["codigo_veiculo"])
            if N(x.get("nome_voluntario")) not in VI_CART or VIMAP.get(cv): continue
            de = DET.get(cv) or {}
            q = ult(porP.get(pl_(x.get("placa")), []) or porC.get(pl_(x.get("chassi") or de.get("chassi")), []))
            VIMAP[cv] = N(q.get("responsibleSalesman")) if q else ""
        VIMAP = {k_: v_ for k_, v_ in VIMAP.items() if k_ in ATVD_CV}
        log("  carteira das vendedoras internas:", collections.Counter(VIMAP.values()).most_common(6))
except Exception as e_:
    log("AVISO: descontos não recalculados (mantidos os anteriores):", type(e_).__name__, e_)

# ---------- lista de todas as adesões dos meses abertos (abas Adesões validadas e Descontos) ----------
def tc2(x): return " ".join(w if w.lower() in ("de", "da", "do", "dos", "das", "e") else w.capitalize() for w in str(x or "").lower().split())
def fone(s):
    dg = re.sub(r"\D", "", str(s or ""))
    if dg.startswith("55") and len(dg) > 11: dg = dg[2:]
    return "(%s) %s-%s" % (dg[:2], dg[2:-4], dg[-4:]) if len(dg) in (10, 11) else ""
detalhes([x["codigo_veiculo"] for k in LIVE for x in ATIV[k] if not (QM.get(str(x["codigo_veiculo"])) or {}).get("n")])

# ---------- aba Comprovante de adesões (a partir de out/26): instalação do rastreador nos atendimentos do SGA ----------
COMP_DESDE = "2026-10"
TIPO_INST = {"100030": "B", "100029": "R"}          # INSTALAÇÃO NA BASE (R$ 50) · INSTALAÇÃO EXTERNA = residência (R$ 100)
ST_CANC = {"15", "18"}                              # atendimento CANCELADO / CANCELAR INSTALAÇÃO: não conta
INST = {}
CMS = [k for k in LIVE if k >= COMP_DESDE]
if CMS:
    d0 = dt.date.fromisoformat(CMS[0] + "-01") - dt.timedelta(days=45)
    STA = {}
    try: STA = {x["codigo_statusatendimentoassociado"]: x["descricao"] for x in requests.get(B + "/listar/status-atendimento/todos", headers=H, timeout=60).json()}
    except Exception: pass
    for tp in TIPO_INST:
      pg = 0
      try:
        while True:
            it = post("/listar/historico-atendimento-associado", {"codigo_tipo_atendimento": tp, "data_cadastro_inicial": d0.strftime("%d/%m/%Y"), "data_cadastro_final": HOJE.strftime("%d/%m/%Y"), "quantidade_por_pagina": 5000, "inicio_paginacao": pg})
            it = it if isinstance(it, list) else []
            for a in it:
                if str(a.get("codigo_status_atendimento")) in ST_CANC: continue
                quando = str(a.get("data_cadastro") or "")[:10] + " " + str(a.get("hora_cadastro") or "")
                reg = {"i": TIPO_INST[tp], "d": quando, "st": tc2(STA.get(str(a.get("codigo_status_atendimento")), ""))}
                for kk in ([pl_(a.get("placa"))] if pl_(a.get("placa")) else []) + (["cv" + str(a.get("codigo_veiculo"))] if a.get("codigo_veiculo") else []):
                    if kk not in INST or INST[kk]["d"] < quando: INST[kk] = reg      # vale o lançamento mais recente
            if len(it) < 5000: break
            pg += 1
      except (Exception, SystemExit) as e_: log("  atendimentos de instalação não lidos:", tp, str(e_)[:80])   # não derruba a atualização
    log("  instalações (atendimentos do SGA):", len(INST), "veículos")
# comprovantes enviados (planilha de registro do Apps Script, baixada pela tarefa agendada) e marcações da coordenação/financeiro (banco do Retorno)
def _jl(nm, dflt):
    try: return json.load(open(os.path.join(KIT, nm), encoding="utf-8"))
    except Exception: return dflt
CREG = _jl("comp_registro.json", [])
CMARK = _jl("comp_marks.json", {})
CMP = {}
for c in CREG:
    kk = (c.get("mes") or "") + "|" + (pl_(c.get("pl")) or pl_(c.get("ch")))
    if kk.endswith("|"): continue
    if kk not in CMP or str(CMP[kk].get("enviado")) < str(c.get("enviado")): CMP[kk] = c
ADES = []
for k in LIVE:
    for x in ATIV[k]:
        cv = str(x["codigo_veiculo"]); q = QM.get(cv) or {}; de = DET.get(cv) or {}
        r_ = VALR.get(cv) if k in VALMA else None
        c_ = dia(x.get("data_contrato")); br_ = lambda s: "/".join(reversed(s.split("-"))) if s else ""
        if r_ is None: bol, venc = ("Em validação" if k not in VALMS else ""), ""
        elif r_.get("ok") and r_.get("forma"): bol, venc = "Pago no " + r_["forma"] + (" em " + br_(r_["pg"]) if r_.get("pg") else ""), ""
        elif r_.get("ok"): bol, venc = "Pago em " + br_(r_.get("pg", "")), ""
        else: bol, venc = (r_.get("sb") or r_.get("mot", "")), br_(r_.get("venc", ""))
        dv = q.get("dv")
        ADES.append({"m": k, "n": tc2(q.get("n") or de.get("nome") or de.get("nome_associado")), "tel": fone(q.get("tel")) or fone(str(de.get("ddd_celular") or "") + str(de.get("telefone_celular") or "")),
                     "esp": tc2(x.get("nome_voluntario")), "t": COOP.get(str(x.get("codigo_cooperativa")), ""), "pl": x.get("placa") or "", "dc": br_(str(x.get("data_contrato"))[:10]),
                     "ok": bool(r_ and r_.get("ok")), "bol": bol, "venc": venc, "ss": tc2(x.get("descricao_situacao")),
                     "cota": q.get("cota"), "dv": dv, "pt": ("P" if (c_ and any(a <= c_.isoformat() <= b for a, b in PLANTAO.get(k, []))) or plt_(x) or plt_cond(x, k, q.get("n")) else "F") if dv else "", "cot": bool(q)})
        if VI_CART and N(x.get("nome_voluntario")) in VI_CART and q.get("vs"): ADES[-1]["vs"] = q["vs"]
        fx_ = FIXC.get("cv:" + cv) or FIXC.get("pl:" + pl_(x.get("placa") or "")) or FIXC.get("n:" + N(ADES[-1]["n"]))
        if fx_: ADES[-1]["vf"] = fx_["resp"]; ADES[-1]["vfm"] = fx_.get("comp") or k   # 19/11: crédito fixado (aba CRÉDITOS FIXADOS) também conta para a vendedora interna
        if k >= COMP_DESDE:
            a_ = ADES[-1]; plx = pl_(x.get("placa")); chx = pl_(x.get("chassi") or de.get("chassi"))
            if not plx and chx: a_["ch"] = chx
            if q.get("cid"): a_["cid"] = tc2(q["cid"])                         # cidade do associado (Power CRM): Região dos Lagos desconta R$ 50 do rastreador
            ins = INST.get(plx) if plx else None
            ins = ins or INST.get("cv" + cv)
            if ins: a_["inst"], a_["instd"], a_["instst"] = ins["i"], "/".join(reversed(ins["d"][:10].split("-"))), ins["st"]
            ck = plx or chx or ("SP" + re.sub(r"[^A-Z]", "", N(a_["n"]))[:10] + re.sub(r"\D", "", a_["dc"])[:4])   # mesma chave da página
            c0 = CMP.get(k + "|" + ck) if ck else None
            if c0: a_["cp"] = {"v": c0.get("valor"), "url": c0.get("url") or "", "at": c0.get("enviado") or "", "vc": c0.get("conferido"), "vi": c0.get("vi")}
            rg_ = (REGRAS.get(ck) if ck else None) or (REGRAS.get("NOME:" + N(a_["n"])) if not plx else None) or {}   # lista do coordenador por placa (ou nome, sem placa)
            if rg_.get("mes") and rg_["mes"] != k: rg_ = {}                                                        # regra só vale na ativação do mês indicado
            mk = dict({x_: v_ for x_, v_ in rg_.items() if x_ in ("nc", "obs")}, **(((CMARK.get(k) or {}).get(ck) or {}) if ck else {}))
            if mk: a_["mk"] = {x_: mk.get(x_) for x_ in ("ok", "nc", "obs", "okby", "okat", "pg", "pgby", "pgat", "pgl") if mk.get(x_) not in (None, "")}
log("lista de adesões:", len(ADES), "| sem cotação:", sum(1 for a in ADES if not a["cot"]))
META = {"meses_ad": AM, "val_ate": max([i for i, k in enumerate(AM) if k <= (VALMS[-1] if VALMS else cut)], default=-1), "meses_base": mb, "atualizado": NOW.isoformat(timespec="minutes")}

# ---------- cancelados do mês anterior e do atual que continuam cancelados ----------
cd = {}
for cv, hs in HIST.items():
    for h in hs:
        if h[2] == "6" and h[0][:10] >= ini.isoformat(): cd[cv] = max(cd.get(cv, ""), h[0][:10])
RESG_DESDE = "2026-10-01"                                                  # remarketing realizado: conta a partir de out/26
def _reat(cv): return max((h[0][:10] for h in HIST.get(cv, []) if str(h[1]) == "6" and str(h[2]) in ACT_S), default="")
cd = {cv: dc for cv, dc in cd.items() if HIST[cv][-1][2] == "6" or (str(HIST[cv][-1][2]) in ACT_S and _reat(cv) >= max(RESG_DESDE, dc))}   # continua cancelado, ou foi reativado (resgate) a partir de out/26
# inadimplentes e inativos (Rafael, 16/11): passaram para a situação no mês anterior ou no atual e continuam nela hoje.
# Aparecem junto com os cancelados (inadimplente = cinza-escuro, inativo = cinza-claro), sem promoção e sem aviso por e-mail.
# Se voltou a ficar ativo depois (16/11), continua na lista em verde-escuro, como o cancelado reativado (campo rs).
SIT_X = {"4": "inad", "2": "inat", "10": "ret"}   # 18/11: retirada também entra (com a situação do rastreador)
SIT_NM = {"1": "Ativo", "18": "Ativo - Pendente Instalação", "16": "Aguardando Instalação", "19": "Ativo - Dispensa Instalação"}
CX_ = {}
for cv, hs in HIST.items():
    if cv in cd: continue
    ul_ = str(hs[-1][2])
    ix_ = [i for i, h in enumerate(hs) if str(h[2]) in SIT_X and h[0][:10] >= ini.isoformat()]
    if not ix_: continue
    i_ = ix_[-1]; d_ = hs[i_][0][:10]; s_ = SIT_X[str(hs[i_][2])]
    if ul_ in SIT_X: CX_[cv] = (d_, s_, None)                                   # continua inadimplente/inativo
    elif ul_ in ACT_S:                                                         # voltou a ficar ativo depois
        v_ = next((h for h in hs[i_ + 1:] if str(h[2]) in ACT_S), None)
        if v_ and v_[0][:10] >= (HOJE - dt.timedelta(days=7)).isoformat():   # 18/11: só quem voltou nos últimos 7 dias (eram 429 cards e centenas de fichas no SGA)
            CX_[cv] = (d_, s_, {"dc": v_[0][:10], "tp": "reativado", "sit": SIT_NM.get(ul_, "Ativo")})
ACT = {"1", "18", "16", "19"}; GEN = {"removido", "desconsiderado", "desvinculado", "", "operação realizada através da apiv2"}
def cap(s): s = s.strip().lower(); return s[:1].upper() + s[1:]
def limpa(o): return " ".join(_html.unescape(re.sub(r"<[^>]+>", " ", (o or "").replace('\\"', '"'))).replace("\xa0", " ").split())[:160]
def motivo(cv, alvo="6"):
    hs = HIST.get(cv, []); ci = max([i for i, h in enumerate(hs) if str(h[2]) == alvo], default=None)
    if ci is None: return "", ""
    m_ = o_ = ""
    for h in reversed(hs[:ci + 1]):
        if h[2] in ACT: break
        md = MOT.get(h[3], "")
        if md and md != "OUTROS" and not h[4].upper().startswith("TASK"): m_, o_ = md, h[4]; break
    if not m_:
        m_ = MOT.get(hs[ci][3], ""); o_ = hs[ci][4]
        if o_.strip().lower() in GEN:
            for h in reversed(hs[:ci]):
                if h[2] in ACT: break
                if h[4].strip().lower() not in GEN and not h[4].upper().startswith("TASK"): o_ = h[4]; break
    o_ = "" if o_.strip().lower() in GEN or o_.upper().startswith("TASK") else limpa(o_)
    return (cap(m_) if m_ else ""), o_
# 19/11: com o limite de fichas, primeiro quem continua em retirada/inadimplente/inativo (mais recentes antes); quem voltou a ficar ativo fica por último
detalhes(list(cd) + sorted(CX_, key=lambda cv: (CX_[cv][2] is not None, {"ret": 0, "inad": 1, "inat": 2}[CX_[cv][1]], [-ord(c) for c in CX_[cv][0]])))
# ---------- retirada (18/11): rastreador desvinculado? atendimento REMOÇÃO DE RASTREADOR (100014) do SGA, o mais recente do veículo ----------
# Desvinculado/removido = verde (já pode fazer nova adesão); qualquer outro status ou sem atendimento = vermelho (ainda vinculado).
# 19/11 (Rafael): pode fazer nova adesão quando o atendimento de REMOÇÃO DE RASTREADOR está Desvinculado, Removido ou Desconsiderado
# (inclui variações: Desvinculado pago/negativado, Removido com boleto, Concluído removido, Concluído desconsiderado). Qualquer outro status = ainda vinculado.
import unicodedata as _ud
def rr_ok(desc):
    w = set(_ud.normalize("NFKD", str(desc or "")).encode("ascii", "ignore").decode().upper().replace("-", " ").split())
    return bool(w & {"DESVINCULADO", "REMOVIDO", "DESCONSIDERADO"})
REM = {}
if any(v_[1] == "ret" for v_ in CX_.values()):
    try:
        STA2 = {x["codigo_statusatendimentoassociado"]: x["descricao"] for x in requests.get(B + "/listar/status-atendimento/todos", headers=H, timeout=60).json()}
        d0r = (HOJE.replace(day=1) - dt.timedelta(days=200)).replace(day=1); pg = 0
        while True:
            it = post("/listar/historico-atendimento-associado", {"codigo_tipo_atendimento": "100014", "data_cadastro_inicial": d0r.strftime("%d/%m/%Y"), "data_cadastro_final": HOJE.strftime("%d/%m/%Y"), "quantidade_por_pagina": 5000, "inicio_paginacao": pg})
            it = it if isinstance(it, list) else []
            for a in it:
                k_ = str(a.get("codigo_veiculo")); q_ = (a.get("data_cadastro") or "") + " " + (a.get("hora_cadastro") or "")
                if k_ not in REM or q_ > REM[k_][0]:
                    stc = str(a.get("codigo_status_atendimento"))
                    REM[k_] = (q_, {"ok": rr_ok(STA2.get(stc, stc)), "st": " ".join(w.capitalize() for w in str(STA2.get(stc, stc)).lower().split()), "d": "/".join(reversed((a.get("data_cadastro") or "")[:10].split("-")))})
            if len(it) < 5000: break
            pg += 1
        log("  remoção de rastreador (atendimentos do SGA):", len(REM), "veículos")
    except (Exception, SystemExit) as e_: log("  atendimentos de remoção de rastreador não lidos:", str(e_)[:80])
def tc(x): return " ".join(w if w.lower() in ("de", "da", "do", "dos", "das", "e") else w.capitalize() for w in str(x or "").lower().split())
CANC = []
for cv, dc, st_ in [(cv, dc, "") for cv, dc in cd.items()] + [(cv, d_, s_) for cv, (d_, s_, _) in CX_.items()]:
    x = DET.get(str(cv))
    if not x: continue
    dig = "".join(c for c in (x.get("ddd_celular") or "") + (x.get("telefone_celular") or "") if c.isdigit())
    en = N(x.get("nome_voluntario")) or "SEM ESPECIALISTA"
    m_, o_ = motivo(cv, {"inad": "4", "inat": "2", "ret": "10"}.get(st_, "6"))
    CANC.append({"n": tc(x.get("nome") or x.get("nome_associado")), "pl": x.get("placa") or "", "mod": (x.get("modelo") or "").strip(), "ano": str(x.get("ano_modelo") or ""),
                 "moto": "MOTO" in N(x.get("tipo")) or "MOTO" in N(x.get("categoria")), "cel": "", "wa": ("55" + dig) if len(dig) in (10, 11) else "",
                 "mat": str(x.get("codigo_associado")), "esp": tc(x.get("nome_voluntario")), "en": en, "t": COOP.get(str(x.get("codigo_cooperativa")), ""),
                 "lt": LNAMES.get(en, ""), "dc": dc, "mp": None, "b": None, "mot": m_ or "Sem motivo registrado", "obs": o_, "_cpf": x.get("cpf") or ""})
    if st_:
        CANC[-1]["st"] = st_
        if st_ == "ret": CANC[-1]["rr"] = REM.get(str(cv), ("", {"ok": False, "st": "", "d": ""}))[1]
        if CX_[cv][2]: CANC[-1]["rs"] = dict(CX_[cv][2], pl=CANC[-1]["pl"])
log("cancelados recentes:", sum(1 for c_ in CANC if not c_.get("st")), "de", len(cd), "que passaram para cancelado | inadimplentes:", sum(1 for c_ in CANC if c_.get("st") == "inad" and not c_.get("rs")), "| inativos:", sum(1 for c_ in CANC if c_.get("st") == "inat" and not c_.get("rs")), "| retirada:", sum(1 for c_ in CANC if c_.get("st") == "ret" and not c_.get("rs")), "(rastreador desvinculado:", sum(1 for c_ in CANC if c_.get("st") == "ret" and not c_.get("rs") and (c_.get("rr") or {}).get("ok")), ") | voltaram a ficar ativos:", sum(1 for c_ in CANC if c_.get("st") and c_.get("rs")))
# outros veículos do mesmo associado que continuam ativos na base (para o aviso por e-mail)
VASSOC = collections.defaultdict(list)
for v_ in ATV:
    if v_.get("codigo_associado"): VASSOC[str(v_["codigo_associado"])].append(((v_.get("placa") or "").strip(), (v_.get("modelo") or "").strip()))
for c_ in CANC:
    c_["ov"] = [pl_ + (" · " + md_ if md_ else "") for pl_, md_ in VASSOC.get(c_["mat"], []) if pl_ != c_["pl"]]
log("cancelados que continuam com outro veículo ativo:", sum(1 for c_ in CANC if c_["ov"]))

# ---------- remarketing realizado: quem está na lista do remarketing ou nos cancelados recentes e voltou ----------
# Vale: contrato a partir de out/26 (veículo novo ou o mesmo) ou veículo cancelado reativado a partir de out/26, hoje Ativo,
# Ativo - Pendente Instalação, Aguardando instalação ou Ativo - Dispensa Instalação. Reconhece pelo associado (matrícula) e pelo CPF.
def _dg(s): return re.sub(r"\D", "", str(s or ""))
RSV = collections.defaultdict(list)
for v_ in ATV:
    dc_ = str(v_.get("data_contrato") or "")[:10]; ra_ = _reat(v_["codigo_veiculo"])
    # contrato e reativação contam os dois (bug 16/11: um veículo com contrato de 30/10, cancelado em 03/11 e reativado depois
    # continuava "cancelado", porque com contrato a partir de out/26 a reativação era ignorada)
    for e_ in ([{"dc": dc_, "tp": "novo"}] if dc_ >= RESG_DESDE else []) + ([{"dc": ra_, "tp": "reativado"}] if ra_ >= RESG_DESDE and ra_ > dc_ else []):
        e_.update(pl=(v_.get("placa") or v_.get("chassi") or "").strip(), sit=tc(v_.get("descricao_situacao")))
        if v_.get("codigo_associado"): RSV["m:" + str(v_["codigo_associado"])].append(e_)
        if len(_dg(v_.get("cpf_associado"))) >= 11: RSV["c:" + _dg(v_.get("cpf_associado"))].append(e_)
def resg_de(mat, cpf="", desde=""):
    for e_ in sorted(RSV.get("m:" + str(mat), []) + (RSV.get("c:" + _dg(cpf), []) if len(_dg(cpf)) >= 11 else []), key=lambda e: e["dc"]):
        if e_["dc"] >= desde: return dict(e_)
    return None
for c_ in CANC:
    if c_.get("st"): c_.pop("_cpf", ""); continue                     # inadimplente/inativo: não é resgate
    r_ = resg_de(c_["mat"], c_.pop("_cpf", ""), c_["dc"])
    if r_: c_["rs"] = r_
LRS = {}                                                  # lista do remarketing (no cofre da página): matrícula -> resgate
try:
    VLT = json.loads(re.search(r'<script id="vault" type="application/json">(.*?)</script>', page, re.S).group(1))
    for sk in json.load(open(os.path.join(KIT, "spec_keys.json"), encoding="utf-8")):
        bl = VLT["specs"][sk["id"]] if sk["id"] < len(VLT["specs"]) else None
        if not bl: continue
        try: rows_ = json.loads(gzip.decompress(AESGCM(b64d(sk["k"])).decrypt(b64d(bl["iv"]), b64d(bl["c"]), None))).get("rows") or []
        except Exception: continue
        for r0 in rows_:
            m0 = str(r0.get("mat") or "")
            if m0 and m0 not in LRS:
                z_ = resg_de(m0)
                if z_: LRS[m0] = z_
except Exception as e_: log("  lista do remarketing não lida para o resgate:", type(e_).__name__)
log("remarketing realizado (a partir de out/26): lista", len(LRS), "| cancelados recentes", sum(1 for c_ in CANC if c_.get("rs")))
META["resg"] = LRS                                       # vai para todos os acessos (só matrícula, data, placa e situação)

# margem % e boletos pagos do associado — BI Brasil Atuarial (relatório "Publicar na Web")
BK = "38d2c1f1-2c44-4d3c-9cd9-cd3d4b856148"; PB = "https://wabi-brazil-south-b-primary-api.analysis.windows.net/public/reports"
BI_OK = False
try:
    mae = requests.get(f"{PB}/{BK}/modelsAndExploration?preferReadOnlySession=true", headers={"X-PowerBI-ResourceKey": BK}, timeout=120).json()
    MD = mae["models"][0]; RID = mae["exploration"]["report"]["objectId"]; bi = {}
    mats = sorted({c["mat"] for c in CANC if c["mat"].isdigit()}, key=int)
    for i in range(0, len(mats), 200):
        q = {"Version": 2, "From": [{"Name": "d", "Entity": "dim_associados", "Type": 0}, {"Name": "_", "Entity": "_Medidas_Base", "Type": 0}],
             "Select": [{"Column": {"Expression": {"SourceRef": {"Source": "d"}}, "Property": "matricula"}, "Name": "mat"},
                        {"Measure": {"Expression": {"SourceRef": {"Source": "_"}}, "Property": "classificacao_margem%"}, "Name": "mp"},
                        {"Measure": {"Expression": {"SourceRef": {"Source": "_"}}, "Property": "classificacao_count_boletos_pagos"}, "Name": "b"}],
             "Where": [{"Condition": {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "d"}}, "Property": "matricula"}}],
                                              "Values": [[{"Literal": {"Value": "%sL" % m_}}] for m_ in mats[i:i + 200]]}}}]}
        body = {"version": "1.0.0", "queries": [{"Query": {"Commands": [{"SemanticQueryDataShapeCommand": {"Query": q, "Binding": {"Primary": {"Groupings": [{"Projections": [0, 1, 2]}]},
                "DataReduction": {"DataVolume": 4, "Primary": {"Window": {"Count": 30000}}}, "Version": 1}}}]}, "QueryId": "",
                "ApplicationContext": {"DatasetId": MD["dbName"], "Sources": [{"ReportId": RID}]}}], "cancelQueries": [], "modelId": MD["id"]}
        res = requests.post(f"{PB}/querydata?synchronous=true", headers={"X-PowerBI-ResourceKey": BK, "Content-Type": "application/json"}, json=body, timeout=300).json()
        ds = res["results"][0]["result"]["data"]["dsr"]["DS"][0]; prev = [None] * 3
        for row in ds["PH"][0].get("DM0", []):
            c = row.get("C", []); R_ = row.get("R", 0); Z = row.get("Ø", 0); vals = []; ci = 0
            for k in range(3):
                if R_ & (1 << k): vals.append(prev[k])
                elif Z & (1 << k): vals.append(None)
                else: vals.append(c[ci]); ci += 1
            prev = vals; bi[str(vals[0])] = (None if vals[1] is None else float(vals[1]), vals[2])
    for c in CANC: c["mp"], c["b"] = bi.get(c["mat"], (None, None))
    BI_OK = True
except Exception as e:
    log("AVISO: BI Brasil Atuarial não respondeu:", type(e).__name__)
    antes = {(c["mat"], c["pl"]): c for c in OLD.get("canc", [])}    # mantém margem/boletos da leitura anterior
    for c in CANC:
        o = antes.get((c["mat"], c["pl"]))
        if o: c["mp"], c["b"] = o.get("mp"), o.get("b")

# ---------- criptografa e grava ----------
def enc(key, obj):
    iv = os.urandom(12)
    return {"iv": b64e(iv), "c": b64e(AESGCM(key).encrypt(iv, gzip.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()), None))}
# ---------- carteira com "visão de líder" (ex.: Camila e Nalva na carteira Exodus Benefícios) ----------
# spec_keys: "ld": {"team": equipe, "cart": voluntário da carteira (= "minha base"), "excl": voluntários fora da conta, "div": voluntários cujos cancelados são divididos, "par": [ids que dividem]}
DIVEX = dict(OLD.get("div_ex") or {})            # cancelado -> id de quem ficou com ele (fixo entre atualizações)
def _sub(a, b): return [x - y for x, y in zip(a, b)]
def dividir(cfgs):                               # sorteio fixo dos cancelados da carteira entre as vendedoras (novo = quem estiver com menos)
    feitos = set()
    for ld in cfgs:
        par = tuple(str(i) for i in ld.get("par") or [])
        if not par or par in feitos: continue
        feitos.add(par); T = ld["team"]; DV = {N(x) for x in ld.get("div") or []}
        pool = [c_ for c_ in CANC if N(c_.get("t")) == N(T) and c_["en"] in DV and not c_.get("st")]   # inadimplente/inativo fora do sorteio
        cnt = collections.Counter(DIVEX.get(ckey(c_)) for c_ in pool if DIVEX.get(ckey(c_)) in par)
        for c_ in sorted(pool, key=lambda c_: (c_.get("dc") or "", ckey(c_))):
            if DIVEX.get(ckey(c_)) not in par:
                m_ = min(cnt[p] for p in par); esc_ = [p for p in par if cnt[p] == m_]
                p_ = esc_[int(hashlib.sha256(ckey(c_).encode()).hexdigest(), 16) % len(esc_)]
                DIVEX[ckey(c_)] = p_; cnt[p_] += 1
            c_["vid"] = DIVEX[ckey(c_)]; c_["vi"] = SKNAME.get(c_["vid"], "")
def cart_lider(obj, sk, team_of):
    ld = sk["ld"]; T = ld["team"]; CART = N(ld["cart"]); EX = {N(x) for x in ld.get("excl") or []}; DV = {N(x) for x in ld.get("div") or []}
    z0 = lambda f, n: [0] * n
    eqs = SERIES.get(T + "|equipe") or {}
    eq_ = {f: list(eqs.get(f) or z0(f, len(mb) if f == "base" else len(AM))) for f in ("base", "ad", "va")}
    for n_ in EX:
        z = SERIES.get("ESP|" + n_)
        if z: eq_ = {f: _sub(eq_[f], z.get(f) or [0] * len(eq_[f])) for f in eq_}
    pr_ = SERIES.get("ESP|" + CART) or {f: [0] * len(eq_[f]) for f in eq_}
    pr_ = {f: list(pr_.get(f) or [0] * len(eq_[f])) for f in eq_}
    ser = {T + "|equipe": eq_, T + "|propria": pr_, T + "|liderados": {f: _sub(eq_[f], pr_[f]) for f in eq_}}
    for k_, z in SERIES.items():
        if not k_.startswith("ESP|"): continue
        n_ = k_[4:]
        if n_ in EX or n_ == CART or n_ == "SEM ESPECIALISTA" or team_of(n_) != T: continue
        ser[T + "|lid:" + n_] = {f: list(z.get(f) or [0] * len(eq_[f])) for f in eq_}
    canc_ = [dict(c_, t=T, lt=(T if c_["en"] == CART else "")) for c_ in CANC if c_.get("vi") and c_.get("vid") == str(sk["id"])]
    obj.update(ld=True, ldx=", ".join(dict.fromkeys(" ".join(x.title().split()[:2]) for x in ld.get("excl") or [])), team=T, leaders={T: ld.get("nome") or "Carteira " + NOMES.get(T, T)}, teams=[T], series=ser, canc=canc_)
    return obj
# ---------- vendedora interna (Inside Sales): no SGA a venda fica no voluntário da carteira; quem fechou vem do Power CRM ----------
# spec_keys "ld.pc": nomes do vendedor no Power CRM (responsibleSalesman). Adesões, validadas, descontos, comprovantes e reativações só dela;
# meta própria (ld.meta validadas + reativações validadas no mês); o bônus é calculado na página (metade dos comprovantes anexados, sem a instalação).
VIH = dict(OLD.get("vi_hist") or {})              # id -> {"ad": {mês: n}, "va": {mês: n}, "base": {mês: n}} (meses fechados ficam congelados)
def vend_interna(obj, sk, base_now=None):
    ld = sk["ld"]; PCN = {N(x) for x in ld.get("pc") or []}; sid = str(sk["id"]); VT = "VI"
    nomes_ = PCN | {N(sk["nome"])}
    fxn = lambda a_: a_.get("vf") and not (a_.get("vs") in PCN) and (N(a_["vf"]) in PCN or N(a_["vf"]) == N(sk["nome"]).split()[0] or N(a_["vf"]) == N(sk["nome"]))
    mine = [dict(a_, t=VT) for a_ in ADES if a_.get("vs") in PCN] + [dict(a_, t=VT, m=a_.get("vfm") or a_["m"], fx=True) for a_ in ADES if fxn(a_)]   # + créditos fixados (19/11)
    h_ = VIH.setdefault(sid, {"ad": {}, "va": {}, "base": {}})
    for k_ in LIVE:
        rt_ = [r_ for r_ in REAT if r_.get("mes") == k_ and N(r_.get("esp_n") or r_.get("esp")) in nomes_]   # reativações contam como nos líderes
        h_["ad"][k_] = sum(1 for a_ in mine if a_["m"] == k_) + len(rt_)
        h_["va"][k_] = (sum(1 for a_ in mine if a_["m"] == k_ and a_.get("ok")) + sum(1 for r_ in rt_ if r_.get("val"))) if k_ in VALMA else 0
    if base_now is not None: h_["base"][mb[-1]] = base_now
    ad_ = [h_["ad"].get(k_, 0) for k_ in AM]; va_ = [h_["va"].get(k_, 0) for k_ in AM]; bs_ = [h_["base"].get(k_) for k_ in mb]
    ser = dict(obj.get("series") or {}); ser[VT + "|equipe"] = {"base": [x or 0 for x in bs_], "ad": ad_, "va": va_, "bk": [k_ for k_, x in zip(mb, bs_) if x is not None]}
    pls = {pl_(a_["pl"]) for a_ in mine if a_.get("pl")}
    pr_ = None
    if PEND:
        rows_ = [dict(r_, t=VT) for r_ in PEND["rows"] if (r_.get("tipo") == "reat" and N(r_.get("esp_n") or r_.get("esp")) in nomes_) or (r_.get("tipo") != "reat" and pl_(r_.get("pl")) in pls)]
        pr_ = dict(PEND, rows=rows_)
    ds_ = None
    if DESC and DESC.get("d"):
        dd_, tk_ = {}, {}
        for k_ in sorted(DESC["d"]):
            if k_ not in LIVE and k_ not in ((OLD.get("desc_vi") or {}).get(sid) or {}).get("d", {}): continue   # só meses com a venda cruzada no Power CRM
            L_ = [a_ for a_ in mine if a_["m"] == k_]
            if k_ not in LIVE and k_ in ((OLD.get("desc_vi") or {}).get(sid) or {}).get("d", {}):
                dd_[k_] = OLD["desc_vi"][sid]["d"][k_]; tk_[k_] = OLD["desc_vi"][sid]["tk"].get(k_); continue
            dd_[k_] = {VT: [len(L_), sum(1 for a_ in L_ if (a_.get("dv") or 0) > 0 and a_.get("pt") == "P"), sum(1 for a_ in L_ if (a_.get("dv") or 0) > 0 and a_.get("pt") != "P"), 0]}
            c_ = [a_ for a_ in L_ if (a_.get("cota") or 0) > 0]
            tk_[k_] = {VT: [round(sum(a_["cota"] - (a_.get("dv") or 0) for a_ in c_), 2), len(c_)]} if c_ else {}
        ds_ = dict(DESC, d=dd_, tk=tk_)
        DESCVI[sid] = {"d": {k_: v_ for k_, v_ in dd_.items()}, "tk": tk_}
    fxa = [sum(1 for a_ in mine if a_.get("fx") and a_["m"] == k_) for k_ in AM]; fxv = [sum(1 for a_ in mine if a_.get("fx") and a_["m"] == k_ and a_.get("ok")) for k_ in AM]
    VILID[N(sk["nome"])] = {"base": [x or 0 for x in bs_], "ad": ad_, "va": va_, "fx": {"ad": fxa, "va": fxv}}
    nm_ = dict(obj.get("nomes") or {}); nm_[VT] = sk["nome"]
    obj.update(vi={"meta": ld.get("meta", 15), "nome": sk["nome"], "t": VT}, ades=mine, series=ser, pend=pr_, desc=ds_, nomes=nm_,
               vesp={VT: {N(sk["nome"]): {"ad": ad_, "va": va_}}}, lidb={})
    return obj
DESCVI = dict(OLD.get("desc_vi") or {})
# ---------- filtros da carteira na visão geral (coordenação/cadastro): "Base de" = voluntário da carteira; liderados = resto da equipe + vendedoras internas (Power CRM) ----------
VILID = {}                                        # nome da vendedora -> série dela (preenchida em vend_interna)
def _skn():
    try: return {str(x["id"]): N(x["nome"]) for x in json.load(open(os.path.join(KIT, "spec_keys.json"), encoding="utf-8"))}
    except Exception: return {}
SKNAME = _skn()
def cart_all(o, team_of, cfgs):
    ser = dict(o.get("series") or {}); cartl = {}; cartv = {}
    for ld in cfgs:
        T = ld["team"]; CART = N(ld["cart"]); eqs = ser.get(T + "|equipe")
        if not eqs or T in (o.get("leaders") or {}): continue
        nb, na = len(eqs.get("base") or []), len(eqs.get("ad") or [])
        pr_ = ser.get("ESP|" + CART) or {}
        pr_ = {"base": list(pr_.get("base") or [0] * nb), "ad": list(pr_.get("ad") or [0] * na), "va": list(pr_.get("va") or [0] * na)}
        ser[T + "|propria"] = pr_
        ser[T + "|liderados"] = {f: _sub(eqs.get(f) or [0] * len(pr_[f]), pr_[f]) for f in pr_}
        for k_, z in list(ser.items()):
            if k_.startswith("ESP|") and k_[4:] not in (CART, "SEM ESPECIALISTA") and team_of(k_[4:]) == T: ser[T + "|lid:" + k_[4:]] = z
        for n_, z in VILID.items(): ser[T + "|lid:" + n_] = z
        cartl[T] = ld.get("nomev") or "Exodus Benefícios"; cartv[T] = CART
    o.update(series=ser, cartl=cartl, cartv=cartv, vin=sorted(VILID))
    return o
def vi_all(o, cfgs):
    """visão geral (coordenação): adesões da carteira passam a mostrar a vendedora do Power CRM como especialista, e as barras por especialista separam Nalva/Camila do resto da carteira"""
    try: SKL = json.load(open(os.path.join(KIT, "spec_keys.json"), encoding="utf-8"))
    except Exception: SKL = []
    for x in SKL:
        ld = x.get("ld") or {}
        if not ld.get("pc"): continue
        T = ld["team"]; CART = N(ld["cart"]); PC = {N(p) for p in ld["pc"]}; nm = x["nome"]; key = N(nm)
        o.setdefault("vib", []).append({"nome": nm, "key": key, "first": N(nm).split()[0], "t": T, "meta": ld.get("meta") or 15})   # 20/11: bônus nominal do Inside Sales na coordenação
        o["ades"] = [dict(a_, esp=nm, vesp_cart=a_.get("esp")) if a_.get("vs") in PC and N(a_.get("esp")) == CART else a_ for a_ in o.get("ades") or []]
        z = (o.get("series") or {}).get(T + "|lid:" + key)
        ve = (o.get("vesp") or {}).get(T)
        if z and ve is not None:
            ve[key] = {"ad": list(z.get("ad") or []), "va": list(z.get("va") or [])}
            c_ = ve.get(CART)
            fx_ = (VILID.get(key) or {}).get("fx") or {}   # crédito fixado não saiu da carteira: não desconta dela
            if c_: ve[CART] = dict({f: [max(0, a - b + d) for a, b, d in zip(c_.get(f) or [], z.get(f) or [0] * len(c_.get(f) or []), (fx_.get(f) or []) + [0] * 99)] for f in ("ad", "va")}, **{f: c_[f] for f in ("rt", "rv") if f in c_})
    return o
out = {"t": {}}
for team, (_, nome, u) in LEAD.items():
    obj = dict(META, team=team, nomes={team: NOMES[team]}, leaders={team: nome}, teams=[team],
               series={k: v for k, v in SERIES.items() if k.split("|")[0] == team}, canc=[c for c in CANC if c["t"] == team or c["lt"] == team],
               vesp={team: VESP.get(team, {})}, lidb={team: LIDB[team]}, pend=dict(PEND, rows=[x for x in PEND["rows"] if x["t"] == team]) if PEND else None, ades=[a for a in ADES if a["t"] == team],
               desc=dict(DESC, d={m_: {team: o_[team]} for m_, o_ in DESC["d"].items() if team in o_}, tk={m_: {team: o_[team]} for m_, o_ in DESC["tk"].items() if team in o_}) if DESC else None)
    out["t"][str(R[u]["ids"][0])] = enc(hashlib.sha256(b"evo1|" + rk(u)).digest(), obj)
# ---------- aviso aos líderes: cancelados novos aprovados para a campanha de resgate (margem >= 70% e 3+ boletos) ----------
ckey = lambda c_: str(c_.get("mat")) + "|" + (c_.get("pl") or "")
try: LDALL = [x["ld"] for x in json.load(open(os.path.join(KIT, "spec_keys.json"), encoding="utf-8")) if x.get("ld")]
except Exception: LDALL = []
dividir(LDALL)
CARTT = {ld["team"] for ld in LDALL}             # equipes sem líder com carteira dividida: avisos vão para as vendedoras (campo vi)
def _dest(c_): return ({c_.get("t"), c_.get("lt")} - {"", None}) & (set(LEAD) | (CARTT if c_.get("vi") else set()))
def _nov(t_): return NOVOS.setdefault(t_, {"lider": LEAD[t_][1], "lider_sga": LEAD[t_][0], "rows": []} if t_ in LEAD else {"lider": "", "lider_sga": "", "rows": []})
ELEG = [c_ for c_ in CANC if not c_.get("rs") and not c_.get("st") and c_.get("mp") is not None and c_["mp"] >= 0.7 and c_.get("b") is not None and c_["b"] >= 3]
VISTOS0 = OLD.get("notif_vistos")
NOVOS = {}
if VISTOS0 is not None:                                   # na 1ª vez só marca o que já existe (sem e-mail)
    vs_ = set(VISTOS0)
    for c_ in ELEG:
        if ckey(c_) in vs_: continue
        for t_ in _dest(c_): _nov(t_)["rows"].append(c_)
NOTIF_VISTOS = sorted({ckey(c_) for c_ in ELEG} | (set(VISTOS0 or []) & {ckey(c_) for c_ in CANC}))
# perfil bom (margem >= 70%) mas menos de 3 boletos: "negociar com o coordenador" (avisado a partir de 20/10/26)
COORDL = [c_ for c_ in CANC if not c_.get("rs") and not c_.get("st") and c_.get("mp") is not None and c_["mp"] >= 0.7 and c_.get("b") is not None and c_["b"] < 3]
VISTOSC0 = OLD.get("notif_vistos_coord")
vc_ = set(VISTOSC0) if VISTOSC0 is not None else {ckey(c_) for c_ in COORDL if (c_.get("dc") or "") < "2026-10-20"}   # 1ª vez: só os cancelados a partir de 20/10/26
if VISTOS0 is not None:
    for c_ in COORDL:
        if ckey(c_) in vc_: continue
        for t_ in _dest(c_): _nov(t_)["rows"].append(dict(c_, coord=True))
NOTIF_VISTOS_C = sorted({ckey(c_) for c_ in COORDL} | (set(VISTOSC0 or []) & {ckey(c_) for c_ in CANC}))
json.dump(NOVOS, open(os.path.join(os.path.dirname(os.path.abspath(OUT)), "novos_cancelados.json"), "w", encoding="utf-8"), ensure_ascii=False)
log("cancelados novos na campanha:", {t_: "%d promoção + %d coordenador" % (sum(1 for r_ in o_["rows"] if not r_.get("coord")), sum(1 for r_ in o_["rows"] if r_.get("coord"))) for t_, o_ in NOVOS.items()} or "nenhum")
# ---------- acesso de cada especialista (não líder): só a base própria, os cancelados e as adesões dele ----------
SKF = os.path.join(KIT, "spec_keys.json")
if os.path.exists(SKF):
    PART_ = {"DE", "DA", "DO", "DOS", "DAS", "E", "DI", "DU"}
    def UK(s_): return " ".join([w for w in N(s_).split() if w not in PART_][:2])
    def tokf(kb): return hashlib.sha256(b"rt-tok|" + kb).hexdigest()[:16]
    LEADIDS = {R[u]["ids"][0] for u in R}
    LTOK = {t: tokf(rk(u)) for t, (_, _, u) in LEAD.items() if u in R}
    UKN = collections.defaultdict(set)
    for k_ in SERIES:
        if k_.startswith("ESP|"): UKN[UK(k_[4:])].add(k_[4:])
    for a_ in ADES: UKN[UK(a_["esp"])].add(N(a_["esp"]))
    for c_ in CANC: UKN[UK(c_["en"])].add(c_["en"])
    TEAMOF = collections.defaultdict(collections.Counter)
    for v in ATV: TEAMOF[N(v.get("nome_voluntario"))][COOP.get(v.get("codigo_cooperativa"), "")] += 1
    out["e"] = {}; nesp = 0; LDOBJ = []
    for sk in json.load(open(SKF, encoding="utf-8")):
        if sk["id"] in LEADIDS: continue
        nm_ = set(sk.get("sga") or []) or UKN.get(UK(sk["nome"]), set()); ct = sk.get("carteira")
        ser = {"base": [0] * len(mb), "ad": [0] * len(AM), "va": [0] * len(AM)}
        for n_ in nm_:
            z = SERIES.get("ESP|" + n_)
            if not z: continue
            for f_ in ser: ser[f_] = [x + y for x, y in zip(ser[f_], z.get(f_) or [0] * len(ser[f_]))]
        tm = sum((TEAMOF[n_] for n_ in nm_), collections.Counter()).most_common(1)
        team_ = ct or (tm[0][0] if tm else "") or ((sk.get("eqs") or [""])[0] if sk.get("sga") else "")   # sem vendas no SGA ainda: equipe do cadastro
        if ct: ser = SERIES.get(ct + "|equipe", ser)     # carteira inteira (ex.: Nalva e Camila com a carteira Exodus Benefícios)
        obj = dict(META, esp=sk["nome"], eq=team_, cart=bool(ct), rot=sk.get("rot") or "", team="", nomes=NOMES, leaders={}, teams=[], series={"ALL|equipe": ser},
                   canc=[c_ for c_ in CANC if (c_["t"] == ct if ct else c_["en"] in nm_)], ades=[a_ for a_ in ADES if (a_["t"] == ct if ct else N(a_["esp"]) in nm_)],
                   cptok=LTOK.get(team_) or LTOK.get("RECREIO"))
        if sk.get("ld"): cart_lider(obj, sk, lambda n_: (TEAMOF[n_].most_common(1) or [("", 0)])[0][0])
        if sk.get("ld", {}).get("pc"): vend_interna(obj, sk, sum(1 for cv_, v_ in VIMAP.items() if v_ in {N(x) for x in sk["ld"]["pc"]} and cv_ in ATVD_CV) if VIMAP else None)
        if sk.get("ld"): LDOBJ.append((sk, obj)); continue         # vendedoras: fecha depois, com o filtro das duas
        out["e"][str(sk["id"])] = enc(hashlib.sha256(b"evo-esp|" + b64d(sk["k"])).digest(), obj); nesp += 1
    for sk, obj in LDOBJ:
        T_ = sk["ld"]["team"]
        for n_, z in VILID.items(): obj["series"][T_ + "|lid:" + n_] = z
        obj.update(cartv={T_: N(sk["ld"]["cart"])}, vin=sorted(VILID))
        out["e"][str(sk["id"])] = enc(hashlib.sha256(b"evo-esp|" + b64d(sk["k"])).digest(), obj); nesp += 1
    log("acessos de especialista:", nesp)
assert isinstance(VC, dict) and all(isinstance(v_, dict) for v_ in VC.values()), "vcache corrompido (bug 03/11)"
out["all"] = enc(ALLKEY, vi_all(cart_all(dict(META, notif_vistos=NOTIF_VISTOS, notif_vistos_coord=NOTIF_VISTOS_C, div_ex=DIVEX, vi_hist=VIH, desc_vi=DESCVI, vimap=VIMAP, nomes=NOMES, leaders={t: n for t, (_, n, _) in LEAD.items()}, teams=sorted(NOMES, key=lambda t: NOMES[t]), series=SERIES, canc=CANC, vesp=VESP, lidb=LIDB, pend=PEND, desc=DESC, reat=REAT, ades=ADES,
                              det={k: v for k, v in DET.items() if k in {str(c) for c in cd} or k in {str(c) for c in CX_} or k in {str(x["codigo_veiculo"]) for k_ in LIVE for x in ATIV[k_]}}, vcache=VC, vpend=VP), lambda n_: (TEAMOF[n_].most_common(1) or [("", 0)])[0][0], LDALL), LDALL))
blob = '<script id="evo" type="application/json">' + json.dumps(out, separators=(",", ":")) + "</script>"
page = re.sub(r'<script id="evo" type="application/json">.*?</script>', lambda m_: blob, page, count=1, flags=re.S)
open(OUT, "w", encoding="utf-8").write(page)
log("chamadas ao SGA nesta atualização:", sum(NCALL.values()), dict(NCALL.most_common()))
print(json.dumps({"ok": True, "chamadas_sga": sum(NCALL.values()), "atualizado": META["atualizado"], "base_hoje": len(ATV), "cancelados_recentes": sum(1 for c_ in CANC if not c_.get("st")), "inadimplentes": sum(1 for c_ in CANC if c_.get("st") == "inad" and not c_.get("rs")), "inativos": sum(1 for c_ in CANC if c_.get("st") == "inat" and not c_.get("rs")), "retirada": sum(1 for c_ in CANC if c_.get("st") == "ret" and not c_.get("rs")), "voltaram_ativos": sum(1 for c_ in CANC if c_.get("st") and c_.get("rs")), "bi": BI_OK}, ensure_ascii=False))
