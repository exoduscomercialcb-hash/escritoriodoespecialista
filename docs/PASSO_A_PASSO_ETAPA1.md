# Passo a passo da etapa 1: Supabase, Google Cloud e Render

O que você precisa cadastrar fora do código para o Escritório novo funcionar com login do Google.
Faça na ordem. Nenhuma senha vai para o GitHub nem para o chat: elas ficam só no Render.

---

## 1. Supabase (banco de dados)

1. Entre em https://supabase.com e clique em **New project**.
2. Nome: `escritorio-do-especialista`. Região: **East US (North Virginia)**. Fica perto do servidor do Render e deixa as telas mais rápidas.
3. Crie uma **senha do banco** forte e guarde no seu Excel de senhas. Ela não volta a aparecer.
4. Com o projeto pronto, clique em **Connect** (no alto da tela) e escolha **Session pooler**.
   Use o Session pooler, e não o Direct connection: o Render não conecta pelo endereço direto.
5. Copie o endereço que começa com `postgresql://postgres.` **como ele vem, sem mexer** (com o `[YOUR-PASSWORD]` no meio).
   Esse endereço é o **DATABASE_URL**, e a senha do passo 3 é o **DATABASE_PASSWORD** (os dois vão no Render, passo 3).
   O servidor coloca a senha no lugar do `[YOUR-PASSWORD]` sozinho, então não precisa editar o endereço.

As tabelas `pessoas`, `links_cadastro` e `acessos` são criadas sozinhas quando o servidor liga.
Elas ficam trancadas para a API pública do Supabase: só o servidor do Escritório lê e grava.

## 2. Google Cloud ("Entrar com Google")

1. Entre em https://console.cloud.google.com com a conta Google da Exodus e crie um projeto: `Escritorio do Especialista`.
2. No menu, abra **Google Auth Platform** (ou "APIs e serviços > Tela de consentimento OAuth") e clique em **Começar**:
   - Nome do app: `Escritório do Especialista`.
   - E-mail de suporte: o seu.
   - Público: **Externo**.
   - Contato: o seu e-mail.
3. Em **Público**, clique em **Publicar app** (fica "Em produção").
   Sem isso, só entram as contas que você listar como "usuários de teste". O app só pede nome e e-mail, então o Google não exige verificação.
4. Em **Clientes**, clique em **Criar cliente**:
   - Tipo: **Aplicativo da Web**.
   - Nome: `Escritório no Render`.
   - **URIs de redirecionamento autorizados**, adicione os dois:
     - `https://escritorio.exodusbeneficios.com.br/auth/callback`
     - `https://NOME-DO-SERVICO.onrender.com/auth/callback` (troque pelo endereço que o Render der no passo 3; dá para voltar aqui e acrescentar depois)
5. Copie o **ID do cliente** e a **Chave secreta do cliente**. São o `GOOGLE_OAUTH_CLIENT_ID` e o `GOOGLE_OAUTH_CLIENT_SECRET`.

## 3. Render (servidor)

1. Em https://dashboard.render.com, clique em **New > Web Service** e escolha este repositório (`escritoriodoespecialista`), branch `main`.
   Se preferir, use **New > Blueprint**: o arquivo `render.yaml` já traz tudo do item 2.
2. Configuração:
   - Plano: **Starter**. Região: **Virginia (US East)**.
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn --factory app.main:criar_app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*'`
   - Health check path: `/saude`
   - Auto-Deploy: **After CI checks pass** (só publica quando os testes do GitHub passam).
3. Em **Environment**, cadastre:

| Nome | Valor |
|---|---|
| `DATABASE_URL` | o endereço do Supabase (passo 1.5) |
| `DATABASE_PASSWORD` | a senha do banco do Supabase (passo 1.3) |
| `SESSION_SECRET` | clique em **Generate** |
| `GOOGLE_OAUTH_CLIENT_ID` | passo 2.5 |
| `GOOGLE_OAUTH_CLIENT_SECRET` | passo 2.5 |
| `ADMIN_EMAILS` | o seu e-mail Google (se for mais de um, separe por vírgula) |
| `TZ` | `America/Sao_Paulo` |

   Opcional: `PAINEL_COORDENACAO` = `1` libera o painel do administrador para a coordenação.
   Se faltar alguma variável obrigatória, o servidor não liga e o log do Render mostra qual falta.
   Se não conectar no banco, o log diz o motivo em português (por exemplo, "o Supabase recusou a senha"), sem mostrar a senha.
4. Depois do primeiro deploy, copie o endereço `https://….onrender.com` e confira se ele está nos URIs de redirecionamento do Google (passo 2.4).

## 4. Testar o login

1. Abra `https://….onrender.com` e clique em **Entrar com Google** com o e-mail que está em `ADMIN_EMAILS`.
   Você cai no menu principal com o card **Painel do administrador**.
2. No painel, em **Links de cadastro**, gere um link do tipo **Especialista** e copie.
3. Abra o link numa janela anônima e entre com outra conta Google. Escreva o nome e envie.
   A tela mostra "Seu acesso ainda não foi liberado. Fale com a coordenação."
4. Volte ao painel, em **Cadastros > Pendentes**: preencha a equipe, o nome exato no SGA e o líder e clique em **Aprovar**.
   (Para aprovar especialista, é preciso ter pelo menos um líder já aprovado. Gere um link do tipo **Líder** primeiro.)
5. Na janela anônima, entre de novo: agora abre o menu. Em **Acessos** aparecem as entradas e as abas abertas.

## 5. GitHub: só entra na `main` com os testes passando

Em **Settings > Branches > Add branch ruleset** (ou "Add rule") para a branch `main`:
marque **Require status checks to pass** e escolha o teste **testes**.

## 6. Domínio (fica para a etapa 6)

No Render, em **Settings > Custom Domains**, adicione `escritorio.exodusbeneficios.com.br`.
Na Hostinger, crie o CNAME `escritorio` apontando para o endereço `.onrender.com`.
O sistema atual continua no ar até você aprovar o novo.
