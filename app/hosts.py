"""Escolha da página pelo endereço de entrada (host).

Hoje só existe o escritório (escritorio.exodusbeneficios.com.br e o endereço .onrender.com do serviço).
Qualquer outro endereço recebe uma página neutra, sem login e sem dados.
Para uma página nova no futuro: acrescentar o nome dela aqui e os endereços na configuração.
"""
from __future__ import annotations

from .config import Config

ESCRITORIO = "escritorio"
NEUTRA = "neutra"


def nome_do_host(host: str | None) -> str:
    """'Escritorio.ExodusBeneficios.com.br:443' -> 'escritorio.exodusbeneficios.com.br'."""
    host = (host or "").strip().lower()
    if host.startswith("["):  # IPv6 entre colchetes: [::1]:8000
        return host.split("]")[0] + "]"
    return host.split(":")[0].rstrip(".")


def pagina_do_host(host: str | None, cfg: Config) -> str:
    return ESCRITORIO if nome_do_host(host) in cfg.hosts_escritorio else NEUTRA
