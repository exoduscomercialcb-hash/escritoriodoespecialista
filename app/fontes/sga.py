"""Cliente do SGA (Hinova), somente leitura.

Regra da Exodus: o token do SGA já foi bloqueado por excesso de extração (30/10). Por isso:
- se o SGA responder "BLOQUEADO" ou recusar o acesso duas vezes seguidas, o cliente levanta SGABloqueado e para;
  quem chamou trava o SGA até o próximo horário agendado (app/atualizacoes.py) e não tenta de novo antes disso;
- cada busca tem um limite de chamadas (limite_chamadas);
- as mensagens de erro não repetem o texto que o SGA devolveu (pode ter dados de associados).
"""
from __future__ import annotations

import time

import httpx2

BASE = "https://api.hinova.com.br/api/sga/v2"


class SGABloqueado(RuntimeError):
    """O SGA bloqueou ou recusou o acesso: parar e não insistir."""


class SGAErro(RuntimeError):
    """Falha passageira (fora do ar, tempo esgotado, resposta inesperada)."""


def _bloqueado(resposta: httpx2.Response) -> bool:
    return "bloquead" in resposta.text[:2000].lower()


class ClienteSGA:
    def __init__(self, token: str, usuario: str, senha: str, *, http: httpx2.Client | None = None,
                 limite_chamadas: int = 3000, espera=time.sleep):
        self.token, self.usuario, self.senha = token, usuario, senha
        self.http = http or httpx2.Client(base_url=BASE, timeout=180)
        self.limite_chamadas = limite_chamadas
        self.chamadas = 0
        self.espera = espera
        self._cabecalho: dict | None = None

    def _contar(self) -> None:
        self.chamadas += 1
        if self.chamadas > self.limite_chamadas:
            raise SGAErro(f"limite de {self.limite_chamadas} chamadas ao SGA nesta busca atingido")

    def autenticar(self) -> None:
        self._contar()
        try:
            r = self.http.post("/usuario/autenticar", headers={"Authorization": f"Bearer {self.token}"},
                               json={"usuario": self.usuario, "senha": self.senha})
        except httpx2.HTTPError as e:
            raise SGAErro(f"SGA não respondeu ao login ({type(e).__name__})") from None
        if _bloqueado(r):
            raise SGABloqueado("o SGA respondeu BLOQUEADO no login")
        if r.status_code in (401, 403):
            raise SGABloqueado(f"o SGA recusou o login (código {r.status_code})")
        token_usuario = None
        if r.is_success:
            try:
                token_usuario = r.json().get("token_usuario")
            except ValueError:
                token_usuario = None
        if not token_usuario:
            raise SGAErro(f"o SGA não devolveu o token de acesso (código {r.status_code})")
        self._cabecalho = {"Authorization": f"Bearer {token_usuario}"}

    def post(self, caminho: str, corpo: dict) -> dict:
        """Consulta (as consultas do SGA usam POST, mas só leem). Devolve o JSON; {} quando não há resultado."""
        if self._cabecalho is None:
            self.autenticar()
        recusas = 0
        for tentativa in range(3):
            self._contar()
            try:
                r = self.http.post(caminho, headers=self._cabecalho, json=corpo)
            except httpx2.HTTPError:
                self.espera(5 * (tentativa + 1))
                continue
            if _bloqueado(r):
                raise SGABloqueado(f"o SGA respondeu BLOQUEADO em {caminho}")
            if r.status_code in (401, 403):
                recusas += 1
                if recusas >= 2:
                    raise SGABloqueado(f"o SGA recusou o acesso duas vezes seguidas em {caminho}")
                self.autenticar()  # o token de acesso expira depois de alguns minutos
                continue
            if r.status_code == 406 and "encontrad" in r.text[:500].lower():
                return {}  # nenhum resultado para esse filtro
            if r.is_success:
                try:
                    return r.json()
                except ValueError:
                    pass  # o SGA às vezes oscila e devolve resposta quebrada: tenta de novo
            self.espera(5 * (tentativa + 1))
        raise SGAErro(f"o SGA não respondeu em {caminho} depois de 3 tentativas")

    def get(self, caminho: str):
        """Consulta por GET (motivos, detalhes de um veículo). Devolve o JSON; None se o SGA disser que não achou."""
        if self._cabecalho is None:
            self.autenticar()
        recusas = 0
        for tentativa in range(3):
            self._contar()
            try:
                r = self.http.get(caminho, headers=self._cabecalho)
            except httpx2.HTTPError:
                self.espera(5 * (tentativa + 1))
                continue
            if _bloqueado(r):
                raise SGABloqueado(f"o SGA respondeu BLOQUEADO em {caminho.split('/')[1] if '/' in caminho else caminho}")
            if r.status_code in (401, 403):
                recusas += 1
                if recusas >= 2:
                    raise SGABloqueado("o SGA recusou o acesso duas vezes seguidas")
                self.autenticar()
                continue
            if r.status_code in (404, 406):
                return None
            if r.is_success:
                try:
                    return r.json()
                except ValueError:
                    pass
            self.espera(5 * (tentativa + 1))
        raise SGAErro("o SGA não respondeu a uma consulta depois de 3 tentativas")

    def fechar(self) -> None:
        self.http.close()
