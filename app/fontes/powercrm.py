"""Cliente do Power CRM, somente leitura (relatório de cotações)."""
from __future__ import annotations

import time

import httpx2

URL = "https://api.powercrm.com.br/api/report/db/paginated"


class PowerCRMErro(RuntimeError):
    pass


class ClientePowerCRM:
    def __init__(self, token: str, *, http: httpx2.Client | None = None, espera=time.sleep):
        self.http = http or httpx2.Client(timeout=300)
        self.cabecalho = {"Authorization": f"Bearer {token}"}
        self.espera = espera

    def pagina(self, de: str, ate: str, numero: int) -> list[dict]:
        """Uma página de cotações entre duas datas (AAAA-MM-DD)."""
        for tentativa in range(3):
            try:
                r = self.http.post(URL, headers=self.cabecalho,
                                   json={"from": de, "to": ate, "page": numero, "stringFilterTypeDate": 1})
            except httpx2.HTTPError:
                self.espera(5 * (tentativa + 1))
                continue
            if r.status_code in (401, 403):
                raise PowerCRMErro(f"o Power CRM recusou o token (código {r.status_code})")
            if r.is_success:
                try:
                    dados = r.json()
                except ValueError:
                    dados = None
                if isinstance(dados, dict):  # sem "items": fim das páginas (igual ao script atual)
                    return dados["items"] if isinstance(dados.get("items"), list) else []
            self.espera(5 * (tentativa + 1))
        raise PowerCRMErro("o Power CRM não respondeu depois de 3 tentativas")

    def fechar(self) -> None:
        self.http.close()
