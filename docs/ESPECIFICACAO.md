# Escritório do Especialista no Render: especificação

Dono: Rafael Veiga (coordenador, Exodus Benefícios). Documento de partida para construir a versão nova do sistema, hospedada no Render, no endereço **https://escritorio.exodusbeneficios.com.br**.

Hoje o sistema é uma página publicada no Claude (artefato). Uma IA roda os scripts de atualização duas vezes ao dia e republica a página inteira. Na versão nova, **o próprio servidor busca os dados nas APIs, sem IA**, guarda no banco e a página mostra o dado mais novo sempre que abrir ou apertar **F5**.

Tudo o que o sistema faz hoje continua igual: telas, regras de negócio, cores e textos. Referências:
- `docs/MANUAL_SISTEMA_ATUAL.md`: regras de negócio, histórico de erros e comandos.
- `referencia/pagina_atual.html`: a página atual (telas, CSS, JavaScript), sem os dados.
- `referencia/scripts/`: os scripts Python que montam os dados hoje.
- `referencia/testes/rodar_testes.py`: os testes de regressão atuais.

---

## 1. Princípios
1. **SGA, Power CRM e BI são somente leitura.** Nunca gravar nada neles.
2. **Respeitar o limite do SGA.** O token do SGA já foi bloqueado por excesso de extração ("BLOQUEADO"). Se o SGA responder BLOQUEADO ou 401 seguido, o sistema para de consultar, registra o erro no painel do administrador e só tenta de novo no próximo horário agendado. Nunca insistir em loop.
3. **Sem IA no dia a dia.** As atualizações são código agendado dentro do servidor.
4. **Nenhuma senha no código nem no GitHub.** Tudo vai em variáveis de ambiente no Render (seção 9).
5. **Todo erro corrigido ganha um teste.** Nada vai para produção sem todos os testes passarem.
6. Linguagem da Exodus: "especialista" (nunca "voluntário"), "equipe" (nunca "cooperativa"), "liderado" (nunca "afiliado"). A Exodus é **Proteção Veicular**: nunca "seguradora" nem "empresa".
7. Tudo em português do Brasil.

## 2. Arquitetura
- **Um serviço web no Render**, plano Starter, sempre ligado. Python (os scripts atuais já são Python), por exemplo FastAPI ou Flask, com gunicorn/uvicorn.
- **Agendador dentro do próprio serviço** (APScheduler ou similar), para não pagar serviço de tarefas à parte. Garantir que só uma instância rode as tarefas, com trava no banco.
- **Banco de dados:** Postgres no Supabase (plano gratuito). Prints de reativação no Supabase Storage.
- **Front-end:** a página atual adaptada. Em vez de dados criptografados embutidos no HTML, ela chama a API (`/api/...`) depois do login. Mantém o visual, os cards do menu principal e as abas.
- **Escolha da página pelo endereço (host):** o servidor olha o nome do endereço de entrada e serve a página certa. Hoje só existe o escritório (`escritorio.exodusbeneficios.com.br` e o endereço `.onrender.com`). Endereço desconhecido mostra uma página neutra. Ter teste automático para isso.
- Fuso horário de todas as datas: America/Sao_Paulo.

## 3. Atualização dos dados sem IA ("tempo real")
O servidor busca e grava no banco. A página lê do banco: F5 mostra o último dado salvo, e a página também pode se atualizar sozinha a cada 5 minutos.

| Fonte | O que | Frequência sugerida |
|---|---|---|
| SGA | veículos, situações, histórico, contratos, boletos (mesma lógica de `atualizar_retorno.py`) | completo 2x ao dia (5:52 e 15:52) + leve (só contratos e situações do mês) a cada 60 min, das 7h às 22h |
| Power CRM | cotações (só vendas concretizadas para descontos), cidade do associado | a cada 30 min |
| BI Brasil Atuarial | margem e boletos pagos dos cancelados | 2x ao dia |
| Google Drive | comprovantes de adesão e prints de reativação (pasta "Comprovantes de adesões") | a cada 10 min |

O painel do administrador mostra o horário da última atualização bem-sucedida de cada fonte e o último erro.

**Botão "Atualizar meus dados" (cada pessoa atualiza os próprios dados do SGA):**
- Fica no topo da tela de cada pessoa. Busca no SGA **só** os contratos, situações e boletos daquela pessoa (no líder, da equipe dele; na coordenação, de todos, com a mesma trava). É consulta pequena, nunca a base inteira, e **somente leitura**.
- **Intervalo por pessoa:** no máximo 1 vez a cada 15 minutos. Antes disso, o botão fica desligado mostrando "Atualizado há X min".
- **Limite geral:** os pedidos entram numa fila e o servidor faz poucos por minuto (configurável), mesmo com muita gente clicando ao mesmo tempo.
- **SGA bloqueado:** o botão fica desligado para todos, com "Atualização do SGA pausada. Os dados voltam a atualizar automaticamente." O motivo só aparece no painel do administrador.
- **Texto curto perto do botão** (obrigatório), por exemplo: "Puxa do SGA os seus contratos e boletos mais recentes. Pode usar 1 vez a cada 15 minutos. O sistema também atualiza sozinho de hora em hora." Embaixo, em letra menor: "Última atualização: hoje às 10:42".
- O painel do administrador registra quem clicou, quando e quantas vezes.
- Testes: intervalo de 15 min respeitado, fila limitando as consultas, botão desligado quando o SGA está bloqueado, e o especialista só recebe os dados dele.

**Leitura do valor dos comprovantes sem IA:** usar o texto que o próprio Google extrai da imagem (OCR do Google Drive, convertendo a imagem para Google Docs pela API, ou Google Cloud Vision) e achar o valor com regras (R$, "Valor", "Valor pago"). Se não conseguir ler, ou se o mesmo Pix aparecer em duas adesões (mesmo ID de transação), o comprovante fica **amarelo** e vai para uma fila "conferir manualmente" no painel da coordenação, onde alguém digita o valor lido. Regra de valor: vale o valor do comprovante, e se divergir do informado, vale o do comprovante.

**E-mails dos cancelados para os líderes:** enviados pelo servidor depois de cada atualização completa (Gmail API com a conta da Exodus, ou SMTP), com o mesmo modelo de `email_cancelados.py`. Guardar no banco quem já foi avisado para não repetir.

## 4. Login com Google e acessos
- **Um único link de acesso para todo mundo:** https://escritorio.exodusbeneficios.com.br. A pessoa clica em "Entrar com Google".
- Só entra quem tem cadastro aprovado. Quem não tem vê "Seu acesso ainda não foi liberado. Fale com a coordenação."
- **Tipos de acesso (os mesmos de hoje):**
  - `admin`: Rafael. Painel do administrador e tudo o que a coordenação vê.
  - `coordenacao`: vê todas as equipes, marca baixa e valida.
  - `financeiro`: dá baixa e lança valor pago (regra: só financeiro e coordenação fazem isso).
  - `cadastro`: lista do remarketing e evolução da base.
  - `lider`: a equipe dele (Recreio, Lua, Elite, Águias, Pé no Chão, Tubarões, Magnatas, Elim).
  - `vendedora_interna`: carteira própria (hoje Nalva e Camila).
  - `especialista`: só os dados dele (liderado de uma equipe).
- **Links de cadastro, um para cada tipo de acesso.** O admin gera no painel. A pessoa abre o link, entra com o Google e preenche o nome. O cadastro fica **pendente** até o admin aprovar e ligar a pessoa ao nome do SGA, à equipe e, no caso do especialista, ao líder. O link pode ter validade e ser desativado.
- Para especialista, o vínculo com o SGA é pelo nome exato do especialista no SGA (campo `sga`), não pelas duas primeiras palavras. Isso evita o problema "Rodrigo Moraes Luiz × Rodrigo Moraes Venâncio".
- Migrar os acessos de hoje: a lista de pessoas, equipes e tipos vem do sistema atual. O Claude do chat entrega essa lista direto no banco, sem passar pelo GitHub. Cada pessoa só precisa entrar uma vez com o Google pelo link do tipo dela.

> **Decisão do Rafael em 08/11/2026 (substitui os links de cadastro acima):**
> - Só entra quem a coordenação cadastrou antes: **nome, tipo de conta e CPF** (equipe, nome no SGA, líder e WhatsApp quando tiver). O cadastro é feito no painel do administrador, um por um ou **colando a planilha do Excel**.
> - **Um endereço só para todo mundo**, sem link de cadastro. No **primeiro acesso**, a pessoa informa **CPF e WhatsApp** e entra com o Google; o CPF liga a conta Google ao cadastro e o acesso já fica liberado. Das próximas vezes, só "Entrar com Google".
> - Se a pessoa clicar direto em "Entrar com Google" no primeiro acesso, o sistema pede CPF e WhatsApp em seguida.
> - O WhatsApp informado é gravado no cadastro (a coordenação não tinha os telefones).
> - O administrador (Rafael) vê o card do painel e, a partir da etapa 3, todos os cards e todas as equipes.
> - **Tela de entrada:** CPF e WhatsApp em cima e um botão só, **Entrar com Google**, embaixo, liberado depois dos dois preenchidos (senão as pessoas não preenchem o telefone). Vale para todas as entradas; o WhatsApp novo atualiza o cadastro. Quem tentar entrar com outra conta Google que não a ligada ao CPF não entra.
> - **Cadastros em tabela**, com as colunas **E-mail Google** e **WhatsApp**, que se preenchem no primeiro acesso.
> - A planilha de hoje (Usuário, Tipo de conta, Nome, Equipe(s), CPF, Matrícula SGA) entra como está: "liderado" = especialista, "INSIDE SALES" = vendedora interna, "SENHA FINANCEIRO" = financeiro, "SENHA MASTER" = o próprio Rafael (o CPF é ligado ao cadastro de administrador). Uma pessoa pode ter **mais de uma equipe**. A **Matrícula SGA** fica no cadastro e vale no lugar do nome no SGA. Sem a coluna Líder, o liderado fica com o líder da equipe dele quando só um líder cuida dela.

## 5. Painel do administrador
Card novo no menu principal, só para `admin` (e a coordenação, se o Rafael liberar):
- **Cadastros:** quem está cadastrado, tipo, equipe, nome no SGA, e-mail Google, situação (pendente, ativo, bloqueado), data de cadastro. Aprovar, editar, bloquear.
- ~~Links de cadastro~~ (não existem mais, decisão de 08/11). No lugar: **Novo cadastro** e **Importar planilha** dentro de Cadastros, com CPF e WhatsApp.
- **Acessos:** quem entrou, quando (data e hora), quantas vezes, último acesso, quais abas abriu. Filtro por pessoa, equipe e período.
- **Atualizações:** última atualização de cada fonte (SGA, Power CRM, BI, Drive), erros recentes e botão "atualizar agora" (respeitando o limite do SGA).
- **Fila de comprovantes para conferir** (seção 3).

## 6. Banco de dados (sugestão de tabelas)
- `pessoas` (nome, e-mail Google, tipo, equipe, nome_sga, líder, situação, criado_em)
- `links_cadastro` (tipo, código, validade, ativo, usos)
- `acessos` (pessoa, data_hora, aba, IP resumido)
- `veiculos`, `historico_situacao`, `boletos`, `contratos` (espelho do que o SGA devolve)
- `cotacoes` (Power CRM)
- `cancelados`, `cancenv` (mensagem enviada), `remarketing` (lista do remarketing e quem já foi contatado)
- `comprovantes` (placa/chassi, mês, especialista, valor informado, valor lido, conferido, URL no Drive)
- `marcacoes` (`comp/<mês>` e `regras` de hoje: meta sem cobrança, validação manual, TOP 3 plantão)
- `reativacoes` (prints, mês, líder, validada)
- `series_mensais` (meses fechados congelados: base, adesões, validadas, reativações)
- `atualizacoes` (fonte, início, fim, ok/erro, mensagem)

## 7. Regras de negócio que não podem mudar
Estão todas em `docs/MANUAL_SISTEMA_ATUAL.md`, seção 5. As principais:
- **Adesões = contratos pela data de contrato no SGA.** Reativação **não** entra em adesões nem na taxa de validação; soma só no bônus do líder.
- Validada = 1º boleto pago. Faixas do bônus do líder: 20 = R$ 500, 30 = R$ 2.000, 60 = R$ 4.000, 100 = R$ 6.000 (vale a maior faixa).
- Rastreador não cobrado por meta só vale se a data do contrato for do mês da meta.
- **Região dos Lagos:** desconto do rastreador de R$ 50, na base ou na residência. Cidades: Rio das Ostras, Cabo Frio, Macaé, Araruama, São Pedro da Aldeia, Maricá, Saquarema, Casimiro de Abreu, Arraial do Cabo, Armação dos Búzios, Iguaba Grande, Silva Jardim e Campos dos Goytacazes. Promoção de meta continua sem desconto. A cidade vem do Power CRM.
- Fora isso, o rastreador desconta R$ 50 na base e R$ 100 na residência.
- **Remarketing realizado:** quem estava na lista ou nos cancelados e voltou com contrato a partir de 01/10/2026 (por matrícula ou CPF) fica verde-escuro, com "Parabéns!", e a mensagem fica travada.
- Promoção de resgate: margem ≥ 70% e ≥ 3 boletos pagos.
- Cores de comprovantes: branco = sem comprovante; amarelo = anexado; azul = valor conferido; verde-escuro = baixa do financeiro.

## 8. Testes
- Portar `referencia/testes/rodar_testes.py` (Playwright) para o sistema novo, entrando com usuários de teste (sem Google, por uma rota de login só de teste, desligada em produção).
- Testes novos: login Google obrigatório; link de cadastro cria pessoa pendente; especialista vê só os dados dele; admin vê o painel e os acessos; escolha da página pelo host; trava do SGA (BLOQUEADO para as consultas); a regra de adesões sem reativações; a Região dos Lagos.
- Rodar os testes no GitHub Actions a cada mudança.

## 9. Variáveis de ambiente no Render (nunca no GitHub)
`SGA_TOKEN` (ou usuário/senha do SGA), `POWERCRM_TOKEN`, credenciais do BI, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_SERVICE_ACCOUNT_JSON` (Drive e Gmail), `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SESSION_SECRET`, `APPS_SCRIPT_URL`, `ADMIN_EMAILS`, `TZ=America/Sao_Paulo`. Ter um `.env.example` só com os nomes.

## 10. Ordem de entrega
1. Esqueleto do servidor + banco + login com Google + painel do administrador (cadastros, links, acessos). Publicar no Render e testar o login.
2. Sincronização com SGA, Power CRM e BI no agendador, gravando no banco (portar `atualizar_retorno.py`).
3. Front-end lendo da API, com todas as abas de hoje.
4. Comprovantes (Drive + leitura de valor + fila manual) e reativações (prints).
5. E-mails dos cancelados.
6. Testes completos, domínio `escritorio.exodusbeneficios.com.br`, migração dos dados e dos acessos, e troca oficial. O sistema atual continua no ar até o Rafael aprovar o novo.

## 11. O que precisa ser feito fora do código (pelo Rafael, com ajuda do Claude)
- Criar o projeto no Google Cloud com a tela de consentimento e o cliente OAuth ("Entrar com Google"), com o endereço de retorno `https://escritorio.exodusbeneficios.com.br/auth/callback` (e o `.onrender.com` para teste).
- Criar uma conta de serviço do Google e compartilhar com ela a pasta "Comprovantes de adesões" do Drive.
- Criar o projeto no Supabase (o Claude do chat pode criar pelo conector).
- No Render: o serviço web Starter ligado a este repositório (o Claude do chat cria pelo conector) e as variáveis da seção 9.
- Na Hostinger: CNAME `escritorio` apontando para o endereço `.onrender.com`.
