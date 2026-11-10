# Adesão no nome do LÍDER no SGA, mas vendida por um LIDERADO (afiliado no Power CRM) -> conta para o liderado (09/11/2026).
# Ex.: um liderado fez 5 adesões em out/26; 2 foram cadastradas no SGA no nome do líder da equipe.
# Roda DEPOIS do atualizar_retorno.py e ANTES do pix.py (também roda sozinho, sem SGA). Idempotente: a adesão movida guarda
# "esp_sga" (nome original) e não é movida de novo.
# Mexe em: ades[].esp, series[t|propria/liderados/lid:<NOME>] (ad/va), vesp[t] (ad/va) nos blocos "all" e de cada líder,
# e no bloco do liderado que tem acesso próprio (spec_keys): ades e series["ALL|equipe"].
# Uso: python3 -I liderado_pc.py <kit_dir> <pagina.html> <saida.html>
import sys, os, re, json, gzip, base64, hashlib, unicodedata, time, datetime as dt
import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KIT, PAGE, OUT = sys.argv[1:4]
DESDE = "2026-09"
log = lambda *a: print(*a, file=sys.stderr, flush=True)
def N(s): return " ".join(unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper().split())
def pl_(s): return re.sub(r"[^A-Z0-9]", "", N(s))
PART = {"DE", "DA", "DO", "DOS", "DAS", "E", "DI", "DU"}
def UK(s): return " ".join([w for w in N(s).split() if w not in PART][:2])
def tc(s): return " ".join(w.capitalize() if (w.lower() not in {"de", "da", "do", "dos", "das", "e"}) else w.lower() for w in str(s or "").strip().split())
b64d = base64.b64decode; b64e = lambda x: base64.b64encode(x).decode()

page = open(PAGE, encoding="utf-8").read()
R = json.load(open(os.path.join(KIT, "leader_rings.json")))
rk = lambda u: b64d(R[u]["keys"][0])
byid = {R[u]["ids"][0]: u for u in R}
ALLKEY = hashlib.sha256(b"evo-all|" + b"".join(rk(byid[i]) for i in [38, 44, 61, 70, 71, 79, 81])).digest()
EV = json.loads(re.search(r'<script id="evo" type="application/json">(.*?)</script>', page, re.S).group(1))
def dec(key, b): return json.loads(gzip.decompress(AESGCM(key).decrypt(b64d(b["iv"]), b64d(b["c"]), None)))
def enc(key, obj):
    iv = os.urandom(12)
    return {"iv": b64e(iv), "c": b64e(AESGCM(key).encrypt(iv, gzip.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode()), None))}
SK = json.load(open(os.path.join(KIT, "spec_keys.json"), encoding="utf-8"))

# ---- Power CRM: afiliado de cada venda concretizada (placa / chassi) ----
PT = re.search(r"([A-Za-z0-9._-]{20,})", open(os.path.join(KIT, "POWERCRM.txt"), encoding="utf-8-sig").read()).group(1)
PH = {"Authorization": "Bearer " + PT, "Content-Type": "application/json"}
def pc_page(f_, t_, pg):
    for i in range(5):
        try: return requests.post("https://api.powercrm.com.br/api/report/db/paginated", headers=PH, json={"from": f_, "to": t_, "page": pg, "stringFilterTypeDate": 1}, timeout=300).json().get("items", [])
        except Exception: time.sleep(5 * (i + 1))
    raise RuntimeError("Power CRM não respondeu")
COT = {}; HOJE = dt.date.today(); d0 = dt.date(2026, 8, 1)
while d0 <= HOJE:
    d1 = min(HOJE, (d0.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)); pg = 0
    while True:
        it = pc_page(d0.isoformat(), d1.isoformat(), pg); novos = [x for x in it if x.get("quotationCode") not in COT]
        if not novos: break
        for x in novos: COT[x["quotationCode"]] = x
        pg += 1
    d0 = d1 + dt.timedelta(days=1)
AF = {}
for q in COT.values():
    if str(q.get("cardStatus")) != "5" or str(q.get("isShelved") or "N").upper() == "S": continue
    af = re.sub(r"\s+SGA$", "", str(q.get("nameAffiliate") or "").strip(), flags=re.I)
    if not af: continue
    for k_ in (pl_(q.get("vehiclePlates")), pl_(q.get("vehicleChassi"))):
        if k_: AF[k_] = af
log("Power CRM:", len(COT), "cotações,", len(AF), "vendas com afiliado")

def nome_lid(af, t, o):
    """Nome do liderado: o do SGA/cadastro da mesma equipe quando o 1º (e o 2º, se houver) nome batem; senão o do Power CRM."""
    w = [x for x in N(af).split() if x not in PART]
    cands = list(((o.get("vesp") or {}).get(t) or {}).keys()) + [N(s["nome"]) for s in SK if t in [N(e) for e in (s.get("eqs") or [])]]
    for c in cands:
        cw = [x for x in c.split() if x not in PART]
        if cw and w and cw[0] == w[0] and (len(w) < 2 or w[1] in cw): return tc(c)
    return tc(af)

MOV = []   # (m, t, pl, ch, novo nome, ok)
st = {"movidas": 0}
def zeros(n): return [0] * n
def roda(key, b):
    o = dec(key, b); AM = o.get("meses_ad") or []; vi = o.get("val_ate", -1); VA = AM[vi] if AM else ""
    NB = len(o.get("meses_base") or []) or max([len(z.get("base") or []) for z in (o.get("series") or {}).values()] + [len(AM) + 1])
    LD = {t: UK(n) for t, n in (o.get("leaders") or {}).items()}
    for a_ in o.get("ades") or []:
        if (a_.get("m") or "") < DESDE or a_.get("esp_sga") or a_.get("m") not in AM: continue
        t = a_.get("t") or ""
        if not t or LD.get(t) != UK(a_.get("esp")): continue          # só adesão no nome do líder da própria equipe
        af = AF.get(pl_(a_.get("pl"))) or AF.get(pl_(a_.get("ch")))
        if not af or UK(af) == UK(a_.get("esp")) or N(af).split()[0] == N(a_.get("esp")).split()[0]: continue
        novo = nome_lid(af, t, o); i = AM.index(a_["m"]); okv = 1 if (a_.get("ok") and a_["m"] <= VA) else 0
        ser = o.setdefault("series", {})
        for kk, d in ((t + "|propria", -1), (t + "|liderados", 1), (t + "|lid:" + N(novo), 1)):
            s_ = ser.get(kk)
            if s_ is None:
                if d < 0: continue
                s_ = ser[kk] = dict({f: zeros(len(AM)) for f in ("ad", "va", "rt", "rv")}, base=zeros(NB))   # a página usa base[] em toda série (erro de 09/11)
            s_["ad"][i] = max(0, s_["ad"][i] + d); s_["va"][i] = max(0, s_["va"][i] + d * okv)
        ve = (o.setdefault("vesp", {})).setdefault(t, {})
        zl = ve.get(N(a_["esp"]))
        if zl: zl["ad"][i] = max(0, zl["ad"][i] - 1); zl["va"][i] = max(0, zl["va"][i] - okv)
        zn = ve.setdefault(N(novo), {f: zeros(len(AM)) for f in ("ad", "va", "rt", "rv")})
        zn["ad"][i] += 1; zn["va"][i] += okv
        a_["esp_sga"] = a_["esp"]; a_["esp"] = novo; st["movidas"] += 1
        if key == ALLKEY: MOV.append(dict(a_))
    for s_ in (o.get("series") or {}).values():          # conserto: série sem base[] travava a tela do líder (09/11)
        if not isinstance(s_.get("base"), list): s_["base"] = zeros(NB); st["base_corrigida"] = st.get("base_corrigida", 0) + 1
    return enc(key, o)

EV["all"] = roda(ALLKEY, EV["all"])
for u in R:
    i = str(R[u]["ids"][0])
    if i in (EV.get("t") or {}): EV["t"][i] = roda(hashlib.sha256(b"evo1|" + rk(u)).digest(), EV["t"][i])
# liderado com acesso próprio: recebe as adesões movidas
ne = 0
for sk in SK:
    i = str(sk["id"])
    if i not in (EV.get("e") or {}): continue
    meus = [a_ for a_ in MOV if UK(a_["esp"]) == UK(sk["nome"]) or N(a_["esp"]) in {N(x) for x in (sk.get("sga") or [])}]
    if not meus: continue
    key = hashlib.sha256(b"evo-esp|" + b64d(sk["k"])).digest(); o = dec(key, EV["e"][i])
    AM = o.get("meses_ad") or []; VA = AM[o.get("val_ate", -1)] if AM else ""
    tem = {(a_.get("m"), pl_(a_.get("pl")) or pl_(a_.get("ch"))) for a_ in o.get("ades") or []}
    s_ = (o.setdefault("series", {})).setdefault("ALL|equipe", {"base": [], "ad": zeros(len(AM)), "va": zeros(len(AM))})
    for a_ in meus:
        if (a_["m"], pl_(a_.get("pl")) or pl_(a_.get("ch"))) in tem or a_["m"] not in AM: continue
        o.setdefault("ades", []).append(a_); j = AM.index(a_["m"])
        s_["ad"][j] += 1
        if a_.get("ok") and a_["m"] <= VA: s_["va"][j] += 1
        ne += 1
    EV["e"][i] = enc(key, o)
blob = '<script id="evo" type="application/json">' + json.dumps(EV, separators=(",", ":")) + "</script>"
page = re.sub(r'<script id="evo" type="application/json">.*?</script>', lambda m_: blob, page, count=1, flags=re.S)
open(OUT, "w", encoding="utf-8").write(page)
print(json.dumps(dict(st, no_bloco_do_liderado=ne, lista=[(a_["m"], a_["t"], a_.get("pl") or a_.get("ch"), a_["esp_sga"], "→", a_["esp"]) for a_ in MOV]), ensure_ascii=False))
