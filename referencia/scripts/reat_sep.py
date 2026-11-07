# Uma vez (05/11): grava rt/rv (reativações por mês) nas séries já publicadas, sem SGA. Depois a atualização completa faz isso sozinha.
# (cabeçalho herdado do pix.py:) Comando "Pix" — atualiza SÓ os comprovantes de adesão na página (sem SGA, sem Power CRM, sem BI, sem e-mails).
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

def roda(key, b, REAT=None):
    o = dec(key, b); REAT = REAT if REAT is not None else (o.get("reat") or [])
    AM = o.get("meses_ad") or []; va_ate = AM[o.get("val_ate", -1)] if AM else ""
    for s_ in (o.get("series") or {}).values(): s_["rt"] = [0] * len(AM); s_["rv"] = [0] * len(AM)
    for t_, o_ in (o.get("vesp") or {}).items():
        for z in o_.values(): z["rt"] = [0] * len(AM); z["rv"] = [0] * len(AM)
    for r in REAT:
        k = r.get("mes")
        if k not in AM: continue
        i = AM.index(k); t_ = r.get("t"); v_ = 1 if (r.get("val") and k <= va_ate) else 0
        for kk in ["ALL|equipe", t_ + "|equipe", t_ + "|propria"]:
            s_ = (o.get("series") or {}).get(kk)
            if s_: s_["rt"][i] += 1; s_["rv"][i] += v_
        z = ((o.get("vesp") or {}).get(t_) or {}).get(N(r.get("esp_n") or r.get("esp")))
        if z: z["rt"][i] += 1; z["rv"][i] += v_
    return enc(key, o), REAT
EV["all"], RA = roda(ALLKEY, EV["all"])
for u in R:
    i = str(R[u]["ids"][0])
    if i in (EV.get("t") or {}): EV["t"][i] = roda(hashlib.sha256(b"evo1|" + rk(u)).digest(), EV["t"][i], RA)[0]
blob = '<script id="evo" type="application/json">' + json.dumps(EV, separators=(",", ":")) + "</script>"
page = re.sub(r'<script id="evo" type="application/json">.*?</script>', lambda m_: blob, page, count=1, flags=re.S)
open(OUT, "w", encoding="utf-8").write(page)
print("ok", len(RA), "reativações")
