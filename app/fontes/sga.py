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
    """Aviso de bloqueio do SGA: só numa resposta de ERRO. Numa resposta boa, "bloqueado" é dado (ex.: a lista de
    situações de atendimento tem um status com esse nome) e não pode parar a busca (alarme falso de 10/11)."""
    return not resposta.is_success and "bloquead" in resposta.text[:2000].lower()


class ClienteSGA:
    def __init__(self, token: str, usuario: str, senha: str, *, http: httpx2.Client | None = None,
                 limite_chamadas: int = 3000, espera=time.sleep):
        self.token, self.usuario, self.senha = token, usuario, senha
        self.http = http or httpx2.Client(base_url=BASE, timeout=180)
        self.limite_chamadas = limite_chamadas
        self.chamadas = 0
        self.espera = espera
        self._cabecalho: dict | None = None
        # Compartilhado entre as linhas de execução da busca: depois de um bloqueio, nenhuma outra consulta sai,
        # nem a que estava esperando para tentar de novo, nem a renovação do login.
        self.bloqueio: str | None = None

    def _bloquear(self, motivo: str) -> SGABloqueado:
        self.bloqueio = self.bloqueio or motivo
        return SGABloqueado(motivo)

    def _contar(self) -> None:
        """Roda antes de toda chamada (login, consulta e cada nova tentativa)."""
        if self.bloqueio is not None:
            raise SGABloqueado(self.bloqueio)
        self.chamadas += 1
        if self.chamadas > self.limite_chamadas:
            raise SGAErro(f"limite de {self.limite_chamadas} chamadas ao SGA nesta busca atingido")

    def _conferir_bloqueio(self, r: httpx2.Response, caminho: str) -> None:
        """Uma consulta voltou com erro dizendo "bloqueado". Confere com um login novo (1 chamada):
        - login recusado ou BLOQUEADO: é o bloqueio do acesso (autenticar levanta SGABloqueado e tudo para);
        - login aceito: o acesso está bom; o SGA recusou só esta consulta (SGAErro, como uma falha comum).
        Caso de 10/11: /listar/status-atendimento/todos era recusada assim e a busca parava toda vez nela."""
        rota = "/".join(caminho.split("?")[0].strip("/").split("/")[:2])  # ex.: listar/status-atendimento (sem códigos)
        self.autenticar()
        raise SGAErro(f"o SGA recusou a consulta {rota} (código {r.status_code}); o login continua aceito")

    def autenticar(self) -> None:
        self._contar()
        try:
            r = self.http.post("/usuario/autenticar", headers={"Authorization": f"Bearer {self.token}"},
                               json={"usuario": self.usuario, "senha": self.senha})
        except httpx2.HTTPError as e:
            raise SGAErro(f"SGA não respondeu ao login ({type(e).__name__})") from None
        if _bloqueado(r):
            raise self._bloquear("o SGA respondeu BLOQUEADO no login")
        if r.status_code in (401, 403):
            raise self._bloquear(f"o SGA recusou o login (código {r.status_code})")
        token_usuario = None
        if r.is_success:
            try:
                token_usuario = r.json().get("token_usuario")
            except ValueError:
                token_usuario = None
        if not token_usuario and "bloquead" in r.text[:2000].lower():
            raise self._bloquear("o SGA respondeu BLOQUEADO no login")
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
                self._conferir_bloqueio(r, caminho)
            if r.status_code in (401, 403):
                recusas += 1
                if recusas >= 2:
                    raise self._bloquear(f"o SGA recusou o acesso duas vezes seguidas em {caminho}")
                self.autenticar()  # o token de acesso expira depois de alguns minutos
                continue
            texto = r.text[:500].lower()
            if r.status_code in (404, 406) and ("encontrad" in texto or "nenhum" in texto):
                return {}  # nenhum resultado para esse filtro (ex.: "nenhum boleto"): resposta definitiva, sem repetir
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
                self._conferir_bloqueio(r, caminho)
            if r.status_code in (401, 403):
                recusas += 1
                if recusas >= 2:
                    raise self._bloquear("o SGA recusou o acesso duas vezes seguidas")
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
