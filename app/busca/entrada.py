"""O que o servidor entrega ao script adaptado (app/busca/retorno.py) e o que recebe de volta.

O script continua com as mesmas regras; só a entrada e a saída mudaram:
- antes lia o Kit privado e a página criptografada; agora recebe tudo aqui;
- antes gravava a página; agora devolve os pacotes para o servidor guardar no banco (app/dados.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


class ErroBusca(RuntimeError):
    """A busca parou sem gravar nada (o que no script era SystemExit)."""


@dataclass
class Entrada:
    agora: datetime  # com fuso America/Sao_Paulo
    old: dict  # o pacote "all" anterior (o que o script lia descriptografando o bloco evo da página)
    especialistas: list[dict]  # como o spec_keys.json do Kit, sem a chave "k": id, nome, sga, eqs, carteira, rot, ld
    listas: dict[str, list]  # lista do remarketing de cada especialista: nome -> rows (antes no vault da página)
    comp_marks: dict  # como o comp_marks.json: {"<mês>": documento comp/<mês>, "regras": documento comp/regras}
    comp_registro: list  # como o comp_registro.json (comprovantes enviados pelo Apps Script)
    sga: Any  # app.fontes.sga.ClienteSGA: .post(caminho, corpo) e .get(caminho)
    powercrm: Any | None  # app.fontes.powercrm.ClientePowerCRM: .pagina(de, ate, numero); None se não houver token
    http_bi: Any  # httpx2.Client para o BI Brasil Atuarial (relatório público)
    log: Callable[..., None] = print


@dataclass
class Saida:
    pacotes: dict[str, Any]  # "all", "t:<EQUIPE>", "e:<NOME>" (chaves com app.dados.N)
    novos_cancelados: dict = field(default_factory=dict)  # para os e-mails aos líderes (etapa 5)
    resumo: dict = field(default_factory=dict)  # atualizado, base_hoje, cancelados_recentes, bi
