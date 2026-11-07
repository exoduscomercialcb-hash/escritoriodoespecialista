# Cidade do associado (Power CRM, sem SGA) nas adesões — usada na regra da Região dos Lagos (rastreador R$ 50). Baseado no pix.py; mexe só em ades[].cid.
# (cabeçalho herdado:) atualiza SÓ os comprovantes de adesão na página (sem SGA, sem Power CRM, sem BI, sem e-mails).
# Lê comp_registro.json + comp_marks.json (regras do coordenador + marcas do mês) e regrava cp/mk nas adesões dos blocos
# criptografados (líderes, especialistas e "all"), mantendo todo o resto como está.
# Uso: python3 -I pix.py <kit_dir> <pagina_atual.html> <saida.html>   (kit: leader_rings.json, spec_keys.json, comp_registro.json, comp_marks.json)
import sys, os, re, json, gzip, base64, hashlib, unicodedata, datetime as dt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KIT, PAGE, OUT = sys.argv[1:4]
log = lambda *a: print(*a, file=sys.stderr, flush=True)
def N(s): return " ".join(unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().upper().split())
def pl_(s): return re.sub(r"[^A-Z0-9]", "", N(s))
b64d = base64.b64decode; b64e = lambda x: base64.b64encode(x).decode()
def _jl(nm, d):
    try: return json.load(open(os.path.join(KIT, nm), encoding="utf-8"))
    except Exception: return d

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

import requests, time
PT = re.search(r"([A-Za-z0-9._-]{20,})", open(os.path.join(KIT, "POWERCRM.txt"), encoding="utf-8-sig").read()).group(1)
PH = {"Authorization": "Bearer " + PT, "Content-Type": "application/json"}
def pc_page(f_, t_, pg):
    for i in range(5):
        try: return requests.post("https://api.powercrm.com.br/api/report/db/paginated", headers=PH, json={"from": f_, "to": t_, "page": pg, "stringFilterTypeDate": 1}, timeout=300).json().get("items", [])
        except Exception: time.sleep(5 * (i + 1))
    raise RuntimeError("Power CRM não respondeu")
COT = {}; HOJE = dt.date.today(); d0 = dt.date(2026, 4, 1)
while d0 <= HOJE:
    d1 = min(HOJE, (d0.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)); pg = 0
    while True:
        it = pc_page(d0.isoformat(), d1.isoformat(), pg); novos = [x for x in it if x.get("quotationCode") not in COT]
        if not novos: break
        for x in novos: COT[x["quotationCode"]] = x
        pg += 1
    d0 = d1 + dt.timedelta(days=1)
def dbr(s):
    m_ = re.match(r"(\d{2})/(\d{2})/(\d{4})", str(s or "")); return (m_[3] + m_[2] + m_[1]) if m_ else ""
CID = {}
for q in sorted(COT.values(), key=lambda q: dbr(q.get("sentToHinovaDate")) or dbr(q.get("createdDate"))):
    if str(q.get("cardStatus")) != "5" or str(q.get("isShelved") or "N").upper() == "S" or not q.get("clientCity"): continue
    for k_ in (pl_(q.get("vehiclePlates")), pl_(q.get("vehicleChassi")), "N:" + N(q.get("clientName"))):
        if k_ and k_ != "N:": CID[k_] = " ".join(w.capitalize() if len(w) > 2 else w.lower() for w in str(q["clientCity"]).strip().split())
log("Power CRM:", len(COT), "cotações,", len(CID), "chaves com cidade")
st = {"ades": 0, "cid": 0}
def roda(key, b):
    o = dec(key, b)
    for a_ in o.get("ades") or []:
        if (a_.get("m") or "") < "2026-10": continue
        st["ades"] += 1
        c_ = CID.get(pl_(a_.get("pl"))) or CID.get(pl_(a_.get("ch"))) or CID.get("N:" + N(a_.get("n")))
        if c_: a_["cid"] = c_; st["cid"] += 1
    return enc(key, o)
EV["all"] = roda(ALLKEY, EV["all"])
for u in R:
    i = str(R[u]["ids"][0])
    if i in (EV.get("t") or {}): EV["t"][i] = roda(hashlib.sha256(b"evo1|" + rk(u)).digest(), EV["t"][i])
for sk in _jl("spec_keys.json", []):
    i = str(sk["id"])
    if i in (EV.get("e") or {}): EV["e"][i] = roda(hashlib.sha256(b"evo-esp|" + b64d(sk["k"])).digest(), EV["e"][i])
blob = '<script id="evo" type="application/json">' + json.dumps(EV, separators=(",", ":")) + "</script>"
page = re.sub(r'<script id="evo" type="application/json">.*?</script>', lambda m_: blob, page, count=1, flags=re.S)
open(OUT, "w", encoding="utf-8").write(page)
print(json.dumps(st, ensure_ascii=False))
