# AGENTS.md — manual da obra do Escritório do Especialista

Arquivo para quem vai trabalhar neste repositório (pessoa ou agente de IA). Lendo só ele, dá para saber
onde está cada coisa, o que não pode, como testar e publicar, e o que já deu errado.
Dono: **Rafael Veiga** (coordenador, Exodus Benefícios). Tudo em português do Brasil.

## Onde estamos (atualize esta seção a cada entrega)

- **Etapa 1 concluída e no ar** em https://escritorio-do-especialista.onrender.com (PR #1 aprovado em 08/11).
  O Render publica a `main`, só depois dos testes passarem ("After CI Checks Pass").
- **Etapa 2 em andamento** na branch `etapa-2-sincronizacao`: o servidor busca SGA, Power CRM e BI sozinho
  (seção 3 e etapa 2 da seção 10 de `docs/ESPECIFICACAO.md`). Enquanto o sistema atual estiver no ar, a busca completa
  do SGA roda **1 vez por dia, de madrugada** (os dois sistemas usam o mesmo token, que já foi bloqueado por excesso).
- **Pendente do Rafael:** "Verify" do domínio `escritorio.exodusbeneficios.com.br` no Render; cadastrar no Render
  `SGA_TOKEN`, `SGA_USUARIO`, `SGA_SENHA` e `POWERCRM_TOKEN`; exportar do sistema atual o que só existe na página
  (histórico dos meses fechados, lista do remarketing, marcações e reativações).
- **Depois:** etapa 3, os cards (as 6 telas de hoje lendo da API).

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
| Para **apagar coluna** do banco: publicar primeiro o código que não usa a coluna; só na publicação seguinte colocar a coluna em `COLUNAS_REMOVIDAS`. | Na troca de versão, a versão antiga ainda atende por alguns segundos (08/11). |

## Mapa da obra

| Peça | Onde | O que saber |
|---|---|---|
| Código | GitHub `exoduscomercialcb-hash/escritoriodoespecialista` | Branch de trabalho: `etapa-1-esqueleto-login` (PR #1). |
| Servidor | Render, serviço `escritorio-do-especialista` (`srv-dbnqb0rrjlhs739ikqog`), workspace "Exodus's workspace", plano Starter, região Virginia | Publica sozinho a cada push na branch configurada. Verificação de saúde: `/saude`. |
| Banco | Supabase, projeto `qrgoeoquwqdpwsxgdrzx` (região us-east-1), numa **organização separada** do projeto `monitoramento-painel` | O conector do Supabase desta conta só enxerga a outra organização: não dá para consultar o banco do escritório por ele. As tabelas são criadas e migradas pelo próprio servidor ao ligar. RLS ligada em todas. |
| Login | Google Cloud, cliente OAuth "Escritório no Render" | URIs de retorno: `https://escritorio-do-especialista.onrender.com/auth/callback` e `https://escritorio.exodusbeneficios.com.br/auth/callback`. |
| Domínio | Hostinger: CNAME `escritorio` → `escritorio-do-especialista.onrender.com` | O código já aceita o domínio (`HOSTS_ESCRITORIO` tem esse padrão). |
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
| `app/static/` | Página única (visual copiado de `referencia/pagina_atual.html`) e página neutra. |
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
