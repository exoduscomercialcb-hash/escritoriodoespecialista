# Plano das etapas 2 e 3: dados no servidor e os cards de hoje

Situação em 08/11/2026: etapa 1 no ar (PR #1). Etapa 2, parte 1 no PR #2 e partes 2.2, 3.1 e 3.2 no PR #3, esperando
a aprovação do Rafael. Este documento é o plano e a ordem de entrega.

## Decisão de arquitetura: reaproveitar o que já funciona

O sistema atual tem duas peças que já estão certas e testadas:

1. **`referencia/scripts/atualizar_retorno.py`** busca SGA, Power CRM e BI e monta, para cada acesso, um "pacote" JSON
   (o mesmo formato para coordenação, para cada líder e para cada especialista). Hoje esse pacote vai criptografado
   dentro da página (bloco `evo`: `all`, `t[<id do líder>]`, `e[<id do especialista>]`).
2. **`referencia/pagina_atual.html`** desenha os 6 cards a partir desse pacote (`E.data`) e da lista do remarketing
   (`specs[].rows`), depois do login antigo (`startApp` e `setupEvo`).

No sistema novo:

- O **servidor** produz os mesmos pacotes e guarda no banco (uma linha por acesso). A busca é o mesmo script,
  adaptado para ler o estado anterior do banco (e não da página) e para usar os clientes de `app/fontes/` (trava do SGA).
- A **página** é a página atual, com o login trocado pelo Google: em vez de descriptografar, ela pede o pacote da pessoa
  logada em `/api/dados`. O desenho e as regras dos cards não mudam.

Por quê: as regras de negócio (meses congelados, quem saiu no mesmo mês, regra do KPI comercial a partir de out/26,
reativações fora das adesões, Região dos Lagos, remarketing realizado) estão espalhadas pelo script e pela página.
Reescrever do zero arrisca mudar uma regra sem querer.

## Ordem de entrega (cada parte depende da anterior)

| Parte | O quê | Depende de | Situação |
|---|---|---|---|
| 2.1 | Trava do SGA, registro das buscas, teste de conexão | — | PR #2 |
| 2.2 | Importar os dados do sistema atual (pacotes, lista do remarketing, marcações) e guardar no banco | Exportação feita pelo Claude que tem o Kit (abaixo) | pronta (PR #3); falta o arquivo |
| 3.1 | `/api/dados`: o pacote da pessoa logada (coordenação/financeiro/cadastro: geral; líder: a equipe; especialista e vendedora: o dele) | 2.2 | pronta (PR #3) |
| 3.2 | A página atual com os 6 cards, lendo `/api/dados` e gravando as marcações em `/api/banco` | 3.1 | pronta (PR #3); conferir com os dados reais. Envio de comprovantes e prints fica para a etapa 4 |
| 2.3 | A busca automática (o script adaptado) regenerando os pacotes; 1 vez por dia, de madrugada, enquanto o sistema atual estiver no ar | 2.1 aprovada e testada no Render; 2.2 (estado anterior) | pronta (branch `etapa-2-busca`); roda depois da importação |
| 2.4 | Botão "Atualizar meus dados" (busca pequena por pessoa, fila, 15 minutos) | 2.3 | a fazer |

Com 2.2, 3.1 e 3.2 prontas, os cards já mostram os dados de hoje (os da última atualização do sistema atual), antes
da busca automática. A busca automática (2.3) só liga depois de o teste de conexão do PR #2 passar no Render.

## Ligação de cada pessoa com o SGA

O Rafael tirou "Nome no SGA" e "Matrícula SGA" do cadastro (08/11). A ligação passa a ser pelo **nome completo do
cadastro**, comparado sem acento e sem maiúscula com `nome_voluntario` do SGA (os nomes da planilha de acessos já são
os nomes do SGA, como "JOAO VITOR DE LIMA MENEZES"). Quem não casar com ninguém aparece no painel como "sem vendas no
SGA com este nome", para o Rafael corrigir o nome no cadastro. Não usar as duas primeiras palavras do nome: foi o que
confundiu "Rodrigo Moraes Luiz" e "Rodrigo Moraes Venâncio" (03/11).

## Exportação do sistema atual (o Rafael pede ao Claude que tem o Kit)

Cole o texto abaixo na conversa do Claude que cuida do Escritório atual (a que tem o Kit privado):

> Preciso exportar os dados do Escritório do Especialista para o sistema novo no Render. Leia o MANUAL do Kit antes.
> Gere UM arquivo JSON chamado `exportacao_escritorio.json`, para eu baixar (não publique em lugar nenhum, não mande
> para o GitHub), com estas chaves:
> - `gerado_em`: data e hora.
> - `evo`: o bloco `evo` da página atual **descriptografado**: `all` (objeto inteiro), `t` (objeto de cada líder, com a
>   chave = equipe, por exemplo `"LUA"`) e `e` (objeto de cada especialista, com a chave = o `nome` do `spec_keys.json`).
> - `especialistas`: para cada item do `spec_keys.json`: `id`, `nome`, `sga` (lista de nomes no SGA), `eqs`, `carteira`,
>   `rot`, `ld` (se tiver) e `rows` (a lista do remarketing dele, descriptografada do `vault`). Sem as chaves (`k`) e
>   sem senhas.
> - `comp_registro`: o conteúdo do `comp_registro.json` (registro dos comprovantes enviados), como está.
> - `motivos` e `rtcfg`: os blocos da página, descriptografados se forem criptografados.
> - `banco`: o conteúdo atual das coleções do banco da página, no formato `{coleção: {id do documento: dados}}`:
>   `enviados`, `comp` (todos os documentos, inclusive `regras`), `compconf`, `reativ` e `cancenv`.
> Confira no fim: quantos especialistas, quantas linhas no remarketing e quais meses em `evo.all.meses_base`.

O arquivo tem dados pessoais de associados: entra no sistema novo pelo painel (Importar dados do sistema atual, parte
2.2), nunca pelo GitHub nem colado em conversa.

## Decisões pendentes do Rafael

1. Quando desligar as tarefas agendadas do sistema atual e passar a busca completa para 2 vezes ao dia (5:52 e 15:52)
   mais a leve de hora em hora (seção 3 da especificação). Até lá (decisão de 10/11): 2 vezes por dia, às 06:00 e às 16:00.
2. Se a coordenação também vê o painel do administrador (`PAINEL_COORDENACAO=1` no Render).
