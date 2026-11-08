# Escritório do Especialista

Sistema interno da Exodus Benefícios para especialistas, líderes e coordenação: lista do remarketing, evolução da base e cancelados recentes, adesões validadas e bônus, descontos, comprovantes de adesão e reativações.

Endereço: https://escritorio.exodusbeneficios.com.br (Render). Especificação em `docs/ESPECIFICACAO.md`.

## Situação
- **Etapa 1 (feita):** servidor, banco (Supabase), login com Google e painel do administrador (Cadastros e Acessos). A coordenação cadastra antes (nome, tipo de conta e CPF, um por um ou colando a planilha); no primeiro acesso, a pessoa informa CPF e WhatsApp e entra com o Google, num endereço só. Escolha da página pelo endereço. Lugar do botão "Atualizar meus dados" (a busca no SGA entra na etapa 2).
- Para publicar: `docs/PASSO_A_PASSO_ETAPA1.md` (Supabase, Google Cloud e Render).

## Onde fica cada coisa
| Pasta / arquivo | O que é |
|---|---|
| `app/main.py` | monta o servidor, a escolha da página pelo endereço e os cabeçalhos de segurança |
| `app/config.py` | lê as variáveis de ambiente (nomes em `.env.example`) |
| `app/db.py` | tabelas `pessoas`, `links_cadastro` e `acessos` |
| `app/servicos.py` | regras: login, primeiro acesso (CPF e WhatsApp), aprovação e acessos |
| `app/cadastro.py` | cadastro pela coordenação: um por um e importação da planilha |
| `app/rotas.py`, `app/rotas_admin.py` | endereços da API |
| `app/static/` | a página (visual da página atual) e a página neutra |
| `tests/` | testes automáticos (rodam no GitHub Actions a cada mudança) |

## Rodar no computador
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium
```
```bash
python -m pytest -q
```
```bash
MODO_TESTE=1 ADMIN_EMAILS=admin.teste@exemplo.com.br uvicorn --factory app.main:criar_app --reload
```
Com `MODO_TESTE=1`, abra http://localhost:8000/teste/entrar?email=admin.teste@exemplo.com.br para entrar sem Google.
Essa rota nunca existe no Render. Os testes no Postgres rodam quando `TESTE_POSTGRES_URL` aponta para um banco local descartável.
