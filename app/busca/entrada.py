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
    # Arquivos novos do Kit (24/11). Vazio = arquivo ausente no Kit (o script segue sem a regra, como lá).
    # creditos_fixados.json (19/11): aba "CRÉDITOS FIXADOS" da planilha Ativação Inside Sales. Cada item:
    #   {"cv": código do veículo, "placa": ..., "nome": associado, "resp": vendedora interna, "comp": "AAAA-MM" (opcional)};
    #   basta um de cv/placa/nome. A adesão fica com o especialista do SGA e também conta para a vendedora (campos vf/vfm).
    creditos_fixados: list = field(default_factory=list)
    # plantão por condição (14/11), o PLT_COND do script, que lá está escrito no código (com nomes de associado, que não
    # entram no repositório): [{"t": "MAGNATAS", "min": 25, "desde": "2026-10", "nomes": ["<começo do nome>", ...]}].
    plt_cond: list = field(default_factory=list)


@dataclass
class Saida:
    pacotes: dict[str, Any]  # "all", "t:<EQUIPE>", "e:<NOME>" (chaves com app.dados.N)
    novos_cancelados: dict = field(default_factory=dict)  # para os e-mails aos líderes (etapa 5)
    resumo: dict = field(default_factory=dict)  # atualizado, base_hoje, cancelados_recentes, bi
    cotacoes: list | None = None  # cotações do Power CRM que o script leu (regra do liderado); None = Power CRM falhou
