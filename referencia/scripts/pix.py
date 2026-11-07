# Comando "Pix" — atualiza SÓ os comprovantes de adesão na página (sem SGA, sem Power CRM, sem BI, sem e-mails).
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

CREG = _jl("comp_registro.json", []); CMARK = _jl("comp_marks.json", {}); REGRAS = (CMARK.get("regras") if isinstance(CMARK, dict) else None) or {}
CMP = {}
for c in CREG:
    kk = (c.get("mes") or "") + "|" + (pl_(c.get("pl")) or pl_(c.get("ch")))
    if kk.endswith("|"): continue
    if kk not in CMP or str(CMP[kk].get("enviado")) < str(c.get("enviado")): CMP[kk] = c
COMP_DESDE = "2026-10"
st = {"ades": 0, "cp": 0, "mk": 0, "mud": 0}
def fix(a_):
    k = a_.get("m") or ""
    if k < COMP_DESDE: return
    st["ades"] += 1; antes = json.dumps([a_.get("cp"), a_.get("mk")], sort_keys=True)
    plx = pl_(a_.get("pl")); chx = a_.get("ch") or ""
    ck = plx or chx or ("SP" + re.sub(r"[^A-Z]", "", N(a_.get("n")))[:10] + re.sub(r"\D", "", a_.get("dc") or "")[:4])
    c0 = CMP.get(k + "|" + ck)
    if c0: a_["cp"] = {"v": c0.get("valor"), "url": c0.get("url") or "", "at": c0.get("enviado") or "", "vc": c0.get("conferido"), "vi": c0.get("vi")}; st["cp"] += 1
    rg_ = REGRAS.get(ck) or (REGRAS.get("NOME:" + N(a_.get("n"))) if not plx else None) or {}
    if rg_.get("mes") and rg_["mes"] != k: rg_ = {}
    mk = dict({x_: v_ for x_, v_ in rg_.items() if x_ in ("nc", "obs")}, **((CMARK.get(k) or {}).get(ck) or {}))
    mk = {x_: mk.get(x_) for x_ in ("ok", "nc", "obs", "okby", "okat", "pg", "pgby", "pgat", "pgl") if mk.get(x_) not in (None, "")}
    if mk: a_["mk"] = mk; st["mk"] += 1
    else: a_.pop("mk", None)
    if json.dumps([a_.get("cp"), a_.get("mk")], sort_keys=True) != antes: st["mud"] += 1

def roda(key, b):
    o = dec(key, b)
    for a_ in o.get("ades") or []: fix(a_)
    return enc(key, o)
EV["all"] = roda(ALLKEY, EV["all"])
for u in R:
    i = str(R[u]["ids"][0])
    if i in (EV.get("t") or {}): EV["t"][i] = roda(hashlib.sha256(b"evo1|" + rk(u)).digest(), EV["t"][i])
ne = 0
for sk in _jl("spec_keys.json", []):
    i = str(sk["id"])
    if i in (EV.get("e") or {}): EV["e"][i] = roda(hashlib.sha256(b"evo-esp|" + b64d(sk["k"])).digest(), EV["e"][i]); ne += 1
blob = '<script id="evo" type="application/json">' + json.dumps(EV, separators=(",", ":")) + "</script>"
page = re.sub(r'<script id="evo" type="application/json">.*?</script>', lambda m_: blob, page, count=1, flags=re.S)
open(OUT, "w", encoding="utf-8").write(page)
print(json.dumps(dict(st, especialistas=ne, registro=len(CREG)), ensure_ascii=False))
