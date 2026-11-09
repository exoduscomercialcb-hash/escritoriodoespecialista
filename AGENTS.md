# AGENTS.md — manual da obra do Escritório do Especialista

Arquivo para quem vai trabalhar neste repositório (pessoa ou agente de IA). Lendo só ele, dá para saber
onde está cada coisa, o que não pode, como testar e publicar, e o que já deu errado.
Dono: **Rafael Veiga** (coordenador, Exodus Benefícios). Tudo em português do Brasil.

## Onde estamos (atualize esta seção a cada entrega)

- **No ar** em https://escritorio.exodusbeneficios.com.br (e no endereço `.onrender.com`), publicando a `main` só
  depois dos testes ("After CI Checks Pass"). PRs #1 a #4 aprovados em 08/11.
- **Etapa 1** concluída: login com Google, cadastro pela coordenação, entrada com CPF + WhatsApp, painel do
  administrador (Cadastros, Acessos, Atualizações).
- **Etapa 2, parte 1** no ar: trava do SGA, registro das buscas e teste de conexão. **Teste de 08/11, 02:33: SGA e
  Power CRM conectaram.**
- **Cards (partes 2.2, 3.1 e 3.2)** no ar em `/escritorio`, ainda **sem dados**: falta o Rafael pedir a exportação ao
  Claude que tem o Kit e importar em Painel > Atualizações > Dados do sistema atual.
- **Parte 2.3 (busca automática)** pronta no PR da branch `etapa-2-busca`, esperando a aprovação do Rafael. Depois de
  aprovada, roda sozinha às 03:52 (só se os dados do sistema atual já tiverem sido importados) e pelo botão do painel.
- **Próximo:** parte 2.4, o botão "Atualizar meus dados". Plano e ordem: `docs/PLANO_ETAPAS_2_E_3.md`.

## Antes de mexer em qualquer coisa

1. Leia esta página inteira. Pronto quando você souber responder: onde está o banco, como publicar e qual é a
   próxima etapa.
2. Leia a seção da `docs/ESPECIFICACAO.md` da etapa em que vai trabalhar, incluindo as **decisões do Rafael de
   08/11** (bloco citado na seção 4): elas mudaram o cadastro e o login e valem mais que o texto original.
3. Para regras de negócio (adesões, validação, bônus, cores, Região dos Lagos), use `docs/MANUAL_SISTEMA_ATUAL.md`,
   seção 5. Elas não mudam no sistema novo.
4. Rode os testes (ver "Como trabalhar") antes de mudar código. Pronto quando todos passarem na sua máquina.

## Regras obrigatórias

| Regra | Por quê |
|---|---|
| Escrever e responder em português do Brasil. Termos: "especialista" (não voluntário), "equipe" (não cooperativa), "liderado" (não afiliado). A Exodus é **Proteção Veicular**, nunca "seguradora" nem "empresa". | Linguagem da Exodus. |
| SGA, Power CRM e BI são **somente leitura**. Se o SGA responder `BLOQUEADO` ou 401 seguido: parar, registrar no painel e só tentar no próximo horário agendado. | O token do SGA já foi bloqueado por excesso de extração (30/10). |
| Senhas, tokens e chaves só em variáveis de ambiente do Render. No repositório, `.env.example` com os **nomes**. | O repositório é público. |
| Dados pessoais (nome, CPF, telefone, e-mail, placa) de associados **e da equipe** nunca entram no repositório, nem em testes. Nos testes, use `cpf_inventado()` e nomes como "Especialista Inventado". Planilhas recebidas do Rafael ficam fora do repositório e são apagadas depois do uso. | LGPD e repositório público. |
| Todo erro corrigido ganha um **teste** e uma **linha no Kit de erros** (abaixo). | Não redescobrir o que já foi resolvido. |
| Nada entra na `main` sem todos os testes passarem (GitHub Actions `Testes`). | O Render publica a partir do que estiver na branch configurada. |
| Fuso horário: `America/Sao_Paulo`. No banco, datas em UTC; na tela, no horário de Brasília (`app/tempo.py`). | Todas as datas da Exodus são de Brasília. |
| Não mostrar na conversa nem no código valores de variáveis secretas, nem trechos do registro do Render que contenham senha. | Um pedaço da senha do banco já vazou no registro (07/11). |
| A página dos cards foi gerada uma vez (08/11) da página atual por `scripts/gerar_pagina_cards.py`. Daqui em diante, edite `app/static/cards.js` e `cards.css` direto; não rode o gerador de novo (ele apagaria as edições). | O gerador fica só como registro do que foi trocado. |
| Para **apagar coluna** do banco: publicar primeiro o código que não usa a coluna; só na publicação seguinte colocar a coluna em `COLUNAS_REMOVIDAS`. | Na troca de versão, a versão antiga ainda atende por alguns segundos (08/11). |

## Mapa da obra

| Peça | Onde | O que saber |
|---|---|---|
| Código | GitHub `exoduscomercialcb-hash/escritoriodoespecialista` | Branch de trabalho: `etapa-1-esqueleto-login` (PR #1). |
| Servidor | Render, serviço `escritorio-do-especialista` (`srv-dbnqb0rrjlhs739ikqog`), workspace "Exodus's workspace", plano Starter, região Virginia | Publica sozinho a cada push na branch configurada. Verificação de saúde: `/saude`. |
| Banco | Supabase, projeto `qrgoeoquwqdpwsxgdrzx` (região us-east-1), numa **organização separada** do projeto `monitoramento-painel` | O conector do Supabase desta conta só enxerga a outra organização: não dá para consultar o banco do escritório por ele. As tabelas são criadas e migradas pelo próprio servidor ao ligar. RLS ligada em todas. |
| Login | Google Cloud, cliente OAuth "Escritório no Render" | URIs de retorno: `https://escritorio-do-especialista.onrender.com/auth/callback` e `https://escritorio.exodusbeneficios.com.br/auth/callback`. |
| Domínio | Hostinger: CNAME `escritorio` → `escritorio-do-especialista.onrender.com`; verificado no Render (08/11) | O código já aceita o domínio (`HOSTS_ESCRITORIO` tem esse padrão). |
| Variáveis no Render | `DATABASE_URL` (endereço do Session pooler, colado com `[YOUR-PASSWORD]`), `DATABASE_PASSWORD`, `SESSION_SECRET`, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `ADMIN_EMAILS` (hoje: `exoduscomercialcb@gmail.com` e `rafaelveiga.exodus@gmail.com`), `TZ` | Lista completa e comentada em `.env.example`. |
| Sistema atual (antigo) | Artefatos no Claude (página e Kit privado), ver `docs/MANUAL_SISTEMA_ATUAL.md`, seção 2 | Continua no ar até o Rafael aprovar o novo. |
| Referência do sistema atual | `referencia/`: página (`pagina_atual.html`, sem dados), scripts Python que montam os dados e testes de regressão | É de onde se porta a lógica (etapas 2 a 5) e o visual. Não roda no servidor. |

### Código (o que cada parte decide)

| Arquivo | Responsável por |
|---|---|
| `app/main.py` | Monta o app, escolhe a página pelo host (desconhecido → página neutra), cabeçalhos de segurança, mensagem clara se o banco não conecta. |
| `app/config.py` | Lê as variáveis de ambiente; no Render (variável `RENDER`) exige as obrigatórias e desliga a rota de teste. |
| `app/db.py` | Tabelas `pessoas`, `acessos` (e `links_cadastro`, hoje sem uso) e as migrações automáticas (`COLUNAS_NOVAS`, `COLUNAS_REMOVIDAS`, `AJUSTES_POSTGRES`). |
| `app/servicos.py` | Regras de login, entrada por CPF + WhatsApp, edição/aprovação/bloqueio, registro de acessos. |
| `app/cadastro.py` | Cadastro pela coordenação: um por um, importação da planilha (tipos e títulos aceitos) e a planilha para baixar. |
| `app/rotas.py`, `app/rotas_admin.py` | Endereços da API; tudo em `/api/admin` exige o painel. |
| `app/static/escritorio.*` | Tela de entrada (CPF + WhatsApp + Google) e painel do administrador (`/#painel`). |
| `app/paginas/cards.html`, `app/static/cards.js`, `app/static/cards.css` | Os cards (`/escritorio`): a página atual com o login trocado. Pede o pacote da pessoa em `/api/dados`. |
| `app/static/claude_banco.js` | Faz o `window.claude.use('db')` da página atual conversar com `/api/banco` (marcações). |
| `app/dados.py` | Importação dos dados do sistema atual e o pacote de cada pessoa (geral, equipe ou especialista). |
| `app/banco_pagina.py` | Banco de marcações (enviados, comp, compconf, reativ, cancenv) e quem pode gravar em cada coleção. |
| `app/atualizacoes.py`, `app/fontes/` | Clientes do SGA e do Power CRM (somente leitura), trava do SGA, registro das buscas, teste de conexão. |
| `app/busca/` | A busca completa. `retorno.py` é o script do sistema atual adaptado (regras intactas; só a entrada e a saída mudaram, ver `entrada.py`). `completa.py` monta a entrada a partir do banco, roda, grava os pacotes e agenda (03:52; `BUSCA_AUTOMATICA=0` desliga). |
| `tests/` | Testes de API, Postgres de verdade (`test_postgres.py`) e navegador (`test_interface.py`). |

### Como o acesso funciona hoje (decisões de 08/11)

1. A coordenação cadastra antes: nome, tipo de conta e CPF (equipe, líder, WhatsApp e e-mail se tiver).
2. A pessoa abre o endereço, informa **CPF e WhatsApp** (o botão só libera com os dois) e clica em **Entrar com Google**.
3. No primeiro acesso, a conta Google fica ligada ao CPF; depois, só essa conta entra. O WhatsApp informado atualiza o
   cadastro. Se a coordenação já colocou o e-mail, só esse e-mail entra.
4. E-mails em `ADMIN_EMAILS` entram sempre como administrador. O link "Acesso do administrador" leva direto ao Google;
   quem não tem conta ligada recebe o pedido de CPF e WhatsApp depois.

## Como trabalhar

### Rodar os testes na sua máquina
1. `pip install -r requirements-dev.txt` e `python -m playwright install chromium`.
2. `python -m pytest -q`. Pronto quando aparecer "passed" sem "failed".
3. Para incluir o Postgres de verdade, suba um Postgres local descartável e rode com
   `TESTE_POSTGRES_URL=postgresql://postgres@127.0.0.1:PORTA/postgres?sslmode=disable` (o teste apaga as tabelas e
   recusa endereço que não seja local). No GitHub Actions isso já roda sempre.

Na sessão de nuvem do Claude Code: o Chromium já instalado é usado com `NAVEGADOR_CHROMIUM=/opt/pw-browsers/chromium`,
e o Postgres local costuma desligar entre uma mensagem e outra (religar antes de rodar).

### Publicar
1. Commit e push na branch configurada no Render (hoje `etapa-1-esqueleto-login`).
2. Espere o GitHub Actions `Testes` terminar com sucesso.
3. Confira no Render (conector `list_deploys` / `list_logs`) que a publicação ficou `live` e que o registro mostra
   `Application startup complete`. Pronto quando os dois aparecerem.

A sessão de nuvem do Claude Code **não alcança** o endereço `.onrender.com` nem o banco do Supabase (rede bloqueada):
confira sempre pelo registro do Render, não com `curl`.

### Mudar o banco
1. Coluna nova: acrescente no modelo (`app/db.py`) **e** em `COLUNAS_NOVAS` (o `create_all` não mexe em tabela que já
   existe no Supabase).
2. Coluna a apagar: veja a regra das duas publicações acima e use `COLUNAS_REMOVIDAS`.
3. Teste a migração a partir do formato anterior (`tests/test_banco_config.py`). Pronto quando o teste passar no SQLite
   e no Postgres.

## Kit de erros (sistema novo)

Erros do sistema atual (artefato no Claude): `docs/MANUAL_SISTEMA_ATUAL.md`, seção 6.

| Data | Sintoma | Causa | Correção | Teste |
|---|---|---|---|---|
| 07/11 | Servidor no Render não ligava: "failed to resolve host" e depois "password authentication failed"; um pedaço da senha do banco apareceu no registro | Senha do banco escrita à mão no meio do `DATABASE_URL` (com `@`, colchete e quebra de linha); depois, colchetes `[ ]` em volta da senha | Senha em variável separada (`DATABASE_PASSWORD`), encaixada pelo servidor no lugar de `[YOUR-PASSWORD]`; falha de conexão explicada em português, com o tamanho da senha recebida e nunca a senha; senha do banco trocada | `tests/test_banco_config.py` |
| 08/11 | Link de cadastro aberto já logado ia para o menu; ao trocar de conta, voltava "acesso não liberado" | O link se perdia ao sair e entrar de novo | Links de cadastro substituídos pela entrada única com CPF + WhatsApp (decisão do Rafael) | `tests/test_cadastro.py`, `tests/test_interface.py` |
| 08/11 | Importação da planilha de acessos "não gravava" | Títulos (`Equipe(s)`), tipos (`SENHA MASTER`, `INSIDE SALES`, `SENHA FINANCEIRO`) e várias equipes por pessoa que o importador não conhecia; uma linha com CPF de 13 números | Importador aceita esse formato; a lista de erros por linha diz o que corrigir | `test_planilha_no_formato_do_sistema_atual` |
| 08/11 | Um erro 500 em `/api/eu` durante a publicação que tirou Matrícula e Nome no SGA | A versão nova apagou as colunas enquanto a antiga ainda atendia | Passou sozinho; virou a regra das duas publicações | `tests/test_banco_config.py` (migração) |
| 08/11 | Rafael informou o CPF de master, entrou com a conta rafaelveiga.exodus e viu "acesso não liberado" | O CPF de master está ligado à conta exoduscomercialcb; a outra conta tinha um cadastro de líder pendente que sobrou de teste | As duas contas em `ADMIN_EMAILS`; a tela diz com qual conta Google o CPF entra (e-mail parcialmente escondido) | `test_cpf_de_outra_conta_mostra_qual_conta_usar` |
| 09/11 | (pego antes de publicar) No script adaptado, "nenhum boleto" do SGA virava "erro SGA" e página do Power CRM sem `items` parava a busca de descontos | Os clientes de `app/fontes/` só aceitavam o 406 "encontrad" e exigiam `items`; o script atual aceitava 404/406 "nenhum" e `items` ausente como "sem resultado" | Clientes iguais ao script nesses dois casos. Regra: ao trocar um pedaço de I/O do script, comparar o tratamento de cada código de resposta | `test_consultas_do_sga_renovam_o_login_e_param_no_segundo_recusado`, `test_teste_do_powercrm` |
| 09/11 | (apontado na revisão do PR #5) Na busca em paralelo, depois de um BLOQUEADO, uma consulta que estava esperando para tentar de novo ainda chamava o SGA | A trava só era conferida na entrada de cada consulta, não antes de cada nova tentativa e da renovação do login | O cliente do SGA guarda o bloqueio e confere antes de toda chamada (`ClienteSGA.bloqueio`) | `test_bloqueio_para_a_consulta_que_esperava_nova_tentativa` |

### Armadilhas de configuração (não são erros do código)

| Situação | O que fazer |
|---|---|
| Painel do Supabase dá erro "removeChild" ou cliques não funcionam | É o tradutor do Chrome: mostrar a página original (inglês) e marcar "Nunca traduzir este site". |
| Render não conecta no banco ("Network is unreachable") | Usar o endereço do **Session pooler**, não o da conexão direta (o Render não tem IPv6). |
| Hostinger recusa o CNAME ("content is not valid") | No "Aponta para", só `escritorio-do-especialista.onrender.com`, sem `https://` e sem `/`. |
| Pessoa vê "acesso não liberado" mesmo cadastrada | Ver na tabela de Cadastros com qual e-mail ela está ligada; se trocou de conta, mudar o e-mail pelo **Editar**. |

## Próximo passo

Confirme com o Rafael se os pendentes da seção "Onde estamos" foram feitos; depois abra a seção 3 e a etapa 2 da
seção 10 de `docs/ESPECIFICACAO.md` e o script `referencia/scripts/atualizar_retorno.py` (a lógica a portar).
