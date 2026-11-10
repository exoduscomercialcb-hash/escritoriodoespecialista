"""Link curto da campanha (10/11): /bf abre o WhatsApp do especialista com a mensagem do lead já escrita."""
from urllib.parse import parse_qs, urlparse


def test_bf_abre_o_whatsapp_com_a_mensagem(novo_cliente):
    c = novo_cliente()
    r = c.get("/bf", follow_redirects=False)
    assert r.status_code == 302
    u = urlparse(r.headers["location"])
    q = parse_qs(u.query)
    assert u.netloc == "api.whatsapp.com" and u.path == "/send"
    assert q["phone"] == ["5521967950692"]
    assert q["text"] == ["Recebi uma mensagem do Miguelzinho sobre condições especiais para proteger meu veículo "
                         "e gostaria de saber mais sobre essa oportunidade!"]


def test_bf_funciona_sem_login(novo_cliente):
    r = novo_cliente().get("/bf", follow_redirects=False)
    assert r.status_code == 302 and "set-cookie" not in {k.lower() for k in r.headers}
