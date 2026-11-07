# Monta o e-mail de "novos cancelados na campanha de resgate" para o líder de cada equipe.
# Uso: python3 email_cancelados.py novos.json saida_dir [--teste]
import json, sys, os, html, datetime as dt
NOMES = {"ÁGUIAS": "Águias", "ELIM": "Elim", "ELITE": "Elite", "EXODUS BENEFÍCIOS": "Exodus Benefícios", "LUA": "Lua", "MAGNATAS": "Magnatas", "PÉ NO CHÃO": "Pé no Chão", "RECREIO": "Recreio", "TUBARÕES": "Tubarões"}
LINK = "https://claude.ai/artifact/S8us5UE78ZFtUAZn8R1Cr3"
import re, urllib.parse
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
import unicodedata
def N(x): return " ".join(unicodedata.normalize("NFKD", str(x or "")).encode("ascii", "ignore").decode().upper().split())
def montar(team, lider, rows, teste=False, lider_sga="", esp=False):
    e = html.escape; LS = N(lider_sga)
    def dono(c):
        if LS and c.get("vi") and N(c["vi"]) == LS: return '<b style="color:#1d4f96">Sua carteira</b> (sorteio da carteira Exodus Benefícios' + ('' if N(c.get("en")) == "EXODUS BENEFICIOS" else ' · voluntário ' + e(c.get("esp") or "—")) + ')'
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
if __name__ == "__main__":
    # uso: python3 email_cancelados.py <novos_cancelados.json> <notif_lideres.json> <pasta_saida> [--teste]
    # notif_lideres.json: {"EQUIPE": {"lider", "emails"}, ..., "_especialistas": {"NOME NO SGA": {"nome", "equipe", "emails"}}}
    # especialista com e-mail cadastrado recebe os cancelados dele; o líder deixa de receber esses e fica com o resto da equipe.
    novos = json.load(open(sys.argv[1], encoding="utf-8")); cfg = json.load(open(sys.argv[2], encoding="utf-8")); out = sys.argv[3]; teste = "--teste" in sys.argv
    ESPS = {N(k): v for k, v in (cfg.get("_especialistas") or {}).items() if [x for x in (v.get("emails") or []) if x]}
    os.makedirs(out, exist_ok=True); res = []
    ok_ = lambda c: elegivel(c) or (c.get("coord") and c.get("mp") is not None and c["mp"] >= 0.7)
    dono_ = lambda c: N(c.get("vi") or c.get("en") or c.get("esp"))   # vi = vendedora interna que ficou com o cancelado no sorteio da carteira
    por_esp = {}
    for team, o in novos.items():
        dest = [x for x in ((cfg.get(team) or {}).get("emails") or []) if x]
        rows = [c for c in o["rows"] if ok_(c)]
        for c in rows:
            if dono_(c) in ESPS and dono_(c) != N(o.get("lider_sga") or ""):
                if not any(x.get("pl") == c.get("pl") and x.get("mat") == c.get("mat") for x in por_esp.get(dono_(c), [])): por_esp.setdefault(dono_(c), []).append(c)
        rows = [c for c in rows if dono_(c) not in ESPS or dono_(c) == N(o.get("lider_sga") or "")]
        if not rows or not dest: continue
        tit, corpo, txt = montar(team, (cfg.get(team) or {}).get("lider") or o["lider"], rows, teste, o.get("lider_sga") or "")
        f = os.path.join(out, team.replace(" ", "_") + ".html"); open(f, "w", encoding="utf-8").write(corpo)
        res.append({"team": team, "to": dest, "subject": tit, "html": f, "text": txt, "n": len(rows)})
    for en, rows in por_esp.items():
        v = ESPS[en]; team = v.get("equipe") or (rows[0].get("t") or "")
        tit, corpo, txt = montar(team, v.get("nome") or en.title(), rows, teste, en, esp=True)
        f = os.path.join(out, "ESP_" + re.sub(r"[^A-Z]", "_", en) + ".html"); open(f, "w", encoding="utf-8").write(corpo)
        res.append({"team": team, "esp": v.get("nome") or en, "to": [x for x in v["emails"] if x], "subject": tit, "html": f, "text": txt, "n": len(rows)})
    json.dump(res, open(os.path.join(out, "emails.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"emails": [(r.get("esp") or r["team"], r["n"], r["to"]) for r in res], "sem_email": [t for t in novos if not (cfg.get(t) or {}).get("emails")]}, ensure_ascii=False))
