"""Cliente do Google (Drive e Planilhas) pela conta de serviço, somente leitura.

A chave da conta de serviço fica só no Render (GOOGLE_SERVICE_ACCOUNT_JSON). Ela nunca aparece em mensagem de erro nem
no registro: os erros dizem só o que fazer (ex.: "compartilhe a pasta com a conta de serviço").
A conta de serviço enxerga só o que foi compartilhado com ela (pastas dos comprovantes e dos prints, planilha do
Inside Sales).
"""
from __future__ import annotations

import base64
import json
import time
from urllib.parse import quote

import httpx2
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE = "https://www.googleapis.com/drive/v3"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
ESCOPOS = "https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/spreadsheets.readonly"
LIMITE_DOWNLOAD = 20 * 1024 * 1024  # 20 MB: um print tem poucas centenas de KB
LIMITE_ZIP = 100 * 1024 * 1024  # 100 MB: só para o .zip dos prints antigos (o de 25/11 tem uns 40 MB)


class GoogleErro(RuntimeError):
    pass


class ArquivoGrande(GoogleErro):
    """O arquivo passa do limite: o download para no limite (não guarda o resto na memória)."""


def _b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).rstrip(b"=").decode()


def ler_credencial(texto: str) -> dict:
    """Confere o JSON da conta de serviço sem nunca repetir o conteúdo dele."""
    try:
        c = json.loads(texto or "")
    except ValueError:
        raise GoogleErro("a chave do Google no Render (GOOGLE_SERVICE_ACCOUNT_JSON) não é um JSON válido: "
                         "cole de novo o conteúdo inteiro do arquivo .json") from None
    if not isinstance(c, dict) or c.get("type") != "service_account" or not c.get("private_key") \
            or not c.get("client_email"):
        raise GoogleErro("a chave do Google no Render não é de uma conta de serviço (falta client_email ou private_key)")
    return c


class ClienteGoogle:
    def __init__(self, credencial_json: str, *, http: httpx2.Client | None = None, relogio=time.time):
        self.cred = ler_credencial(credencial_json)
        self.email = self.cred["client_email"]
        self.http = http or httpx2.Client(timeout=120)
        self.relogio = relogio
        self._token: str | None = None
        self._vence = 0.0

    # ------------------------------------------------------------ login da conta de serviço

    def _assinatura(self) -> str:
        agora = int(self.relogio())
        cab = {"alg": "RS256", "typ": "JWT"}
        corpo = {"iss": self.email, "scope": ESCOPOS, "aud": TOKEN_URL, "iat": agora, "exp": agora + 3600}
        base = _b64(json.dumps(cab).encode()) + "." + _b64(json.dumps(corpo).encode())
        try:
            chave = serialization.load_pem_private_key(self.cred["private_key"].encode(), password=None)
        except (ValueError, TypeError):
            raise GoogleErro("a chave privada da conta de serviço está danificada: gere uma chave nova") from None
        return base + "." + _b64(chave.sign(base.encode(), padding.PKCS1v15(), hashes.SHA256()))

    def token(self) -> str:
        if self._token and self.relogio() < self._vence - 60:
            return self._token
        try:
            r = self.http.post(TOKEN_URL, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                                "assertion": self._assinatura()})
        except httpx2.HTTPError as e:
            raise GoogleErro(f"o Google não respondeu ao login da conta de serviço ({type(e).__name__})") from None
        if r.status_code in (400, 401):
            raise GoogleErro("o Google recusou a chave da conta de serviço (chave apagada ou de outro projeto): "
                             "gere uma chave nova e cole no Render")
        if not r.is_success:
            raise GoogleErro(f"o Google recusou o login da conta de serviço (código {r.status_code})")
        dados = r.json()
        self._token, self._vence = dados["access_token"], self.relogio() + int(dados.get("expires_in", 3600))
        return self._token

    def _get(self, url: str, params: dict | None = None, o_que: str = "a consulta") -> dict:
        return self._pedir(url, params, o_que).json()

    def _pedir(self, url: str, params: dict | None, o_que: str) -> httpx2.Response:
        try:
            r = self.http.get(url, params=params, headers={"Authorization": "Bearer " + self.token()})
        except httpx2.HTTPError as e:
            raise GoogleErro(f"o Google não respondeu a {o_que} ({type(e).__name__})") from None
        self._conferir(r, o_que)
        return r

    def _conferir(self, r: httpx2.Response, o_que: str) -> None:
        if r.status_code == 404:
            raise GoogleErro(f"{o_que}: não encontrado. Confira se foi compartilhado com {self.email}")
        if r.status_code == 403:
            texto = r.text[:2000]
            if "has not been used" in texto or "is disabled" in texto or "SERVICE_DISABLED" in texto:
                raise GoogleErro(f"{o_que}: a API do Google não está ativada no projeto (Biblioteca de APIs)")
            raise GoogleErro(f"{o_que}: sem permissão. Compartilhe com {self.email}")
        if not r.is_success:
            raise GoogleErro(f"{o_que}: o Google respondeu com erro (código {r.status_code})")

    # ------------------------------------------------------------ Drive e Planilhas (só leitura)

    def pasta(self, pasta_id: str) -> dict:
        return self._get(f"{DRIVE}/files/{pasta_id}", {"fields": "id,name,mimeType", "supportsAllDrives": "true"},
                         "a pasta do Drive")

    def arquivos(self, consulta: str, campos: str = "id,name,description,createdTime,mimeType,parents,webViewLink",
                 limite: int = 5000) -> list[dict]:
        """Lista arquivos pela consulta do Drive (ex.: "'<pasta>' in parents and trashed = false")."""
        saida, pagina = [], None
        while len(saida) < limite:
            params = {"q": consulta, "fields": f"nextPageToken,files({campos})", "pageSize": 1000,
                      "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}
            if pagina:
                params["pageToken"] = pagina
            dados = self._get(f"{DRIVE}/files", params, "a lista de arquivos do Drive")
            saida += dados.get("files") or []
            pagina = dados.get("nextPageToken")
            if not pagina:
                break
        return saida[:limite]

    def baixar(self, arquivo_id: str, limite: int = LIMITE_DOWNLOAD) -> bytes:
        """O conteúdo de um arquivo do Drive (alt=media; o escopo drive.readonly permite). Só leitura.
        Lido em pedaços: passou do limite, para na hora (ArquivoGrande), sem baixar o resto."""
        o_que = "o arquivo do Drive"
        try:
            with self.http.stream("GET", f"{DRIVE}/files/{arquivo_id}",
                                  params={"alt": "media", "supportsAllDrives": "true"},
                                  headers={"Authorization": "Bearer " + self.token()}) as r:
                if not r.is_success:
                    r.read()  # resposta de erro: curta, e o texto diz se a API está desligada
                    self._conferir(r, o_que)
                try:
                    declarado = int(r.headers.get("Content-Length") or 0)
                except ValueError:
                    declarado = 0
                if declarado > limite:
                    raise ArquivoGrande("o arquivo do Drive é grande demais")
                partes, total = [], 0
                for parte in r.iter_bytes():
                    total += len(parte)
                    if total > limite:
                        raise ArquivoGrande("o arquivo do Drive é grande demais")
                    partes.append(parte)
                return b"".join(partes)
        except httpx2.HTTPError as e:
            raise GoogleErro(f"o Google não respondeu a {o_que} ({type(e).__name__})") from None

    def planilha(self, planilha_id: str) -> dict:
        return self._get(f"{SHEETS}/{planilha_id}", {"fields": "properties.title,sheets.properties.title"},
                         "a planilha")

    def valores(self, planilha_id: str, intervalo: str) -> list[list]:
        dados = self._get(f"{SHEETS}/{planilha_id}/values/{quote(intervalo, safe='!:')}", None, "a aba da planilha")
        return dados.get("values") or []

    def fechar(self) -> None:
        self.http.close()
