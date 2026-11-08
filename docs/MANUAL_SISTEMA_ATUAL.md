# Manual do Escritório do Especialista (Retorno Exodus)

Leia este arquivo antes de qualquer trabalho no sistema: sessão de conversa, tarefa agendada ou correção. Ele existe para não redescobrir o que já foi resolvido.
Dono: Rafael Veiga (coordenador, Exodus Benefícios). Responder sempre em português.

## 1. Regras de trabalho (obrigatórias)
1. **Todo erro corrigido ganha um teste** em `kit/testes/rodar_testes.py` e uma linha na seção 6 (sintoma → causa → correção → teste).
2. **Nada é publicado sem todos os testes passarem.** Rode: `python3 -I kit/testes/rodar_testes.py <pagina.html> <senhas_teste.json>` e veja `"falhas": 0`.
3. SGA, Power CRM e BI são **somente leitura**. Nunca gravar nada neles.
4. Se o SGA responder **BLOQUEADO**: parar na hora. Não tentar de novo e não insistir (é extração demais no mesmo token).
5. Só financeiro ou coordenação dão baixa ou lançam valor pago.
6. Não apagar prints, comprovantes ou arquivos sem confirmação do Rafael.
7. O Kit é privado e o código do Apps Script nunca é publicado em lugar público.
8. Antes de publicar o Kit, leia o arquivo publicado (Artifact read com `path`) e construa em cima dele. Arquivos `.py` só sobem com `contentType: "text/plain"`.

## 2. Mapa: onde fica cada coisa
| Peça | Onde | Observação |
|---|---|---|
| Página do Escritório | https://claude.ai/artifact/S8us5UE78ZFtUAZn8R1Cr3 | Dados criptografados dentro do HTML (blocos `evo`, `vault`, `motivos`, `rtcfg`). Cerca de 1 MB. Limite: 16 MB |
| Kit privado | https://claude.ai/artifact/HKvRXdvZtqxaRSgJEnAFVs | Scripts, acesso ao SGA e ao Power CRM, chaves dos líderes (`leader_rings.json`) e dos especialistas (`spec_keys.json`), este manual e os testes |
| Banco de dados da página | coleções `comp` (marcações por mês e `regras`), `compconf` (leitura dos comprovantes: `{lido, conferido}`), `reativ` (prints de reativação), `cancenv` | Limite: 25.000 documentos e 256 KB por documento |
| Prints de reativação | assets da página (`/_blob/<id>`) | 1 GB e 5.000 arquivos (38 MB usados em 01/11). Sem backup, por decisão do Rafael |
| Comprovantes de adesão | Google Drive: "Comprovantes de adesões / <Mês> / Equipes / <Equipe> / <Especialista>" | A descrição de cada arquivo é um JSON {placa, mes, equipe, especialista, associado, valor, lider, enviado} |
| Envio sem login | Apps Script (Web App "Qualquer pessoa"); o link fica em `rtcfg.gas` | Recebe os prints e os comprovantes e grava no Drive |
| Senhas | Excel do Rafael (fora do sistema) | No `vault` só há o hash. Para os testes é preciso `senhas_teste.json` (não fica no Kit) |

## 3. Tarefas agendadas
| Tarefa | Quando | O que faz |
|---|---|---|
| trig_017gH5dQ9VkdBEYm7NqoC3QF | 5:52 e 15:52 | Atualização completa: SGA, Power CRM, BI, leitura dos comprovantes, publicação e e-mails de cancelados. **Vinha travando (PENDING)**: investigar |
| trig_01QSRqYsbpv52T2E5paTjyay | :25, das 7h às 15h e das 17h às 22h | Comprovantes de hora em hora: só o Drive, sem ler valores; publica só se mudar algo (`cpmud > 0`) |
| trig_01PAstpGTT2ft8ri16cFcXdb | dia 2 de cada mês, 10:37 | Apaga só as IMAGENS dos prints de reativação de listas com mais de 5 meses (mes < mês atual − 5); o registro fica, com `rm` = data e sem `url`. A página mostra "Imagem apagada em …" |

## 4. Comandos do Rafael
- **"atualize" / "atualize tudo" / "atualize painel"**: atualização completa.
  1. Montar `runNN/kit` com os arquivos do Kit, `comp_registro.json` e `comp_marks.json` (`{"<mês>": doc comp/<mês>, "regras": doc comp/regras}`).
  2. Rodar `atualizar_retorno.py`.
  3. Rodar `pix.py`.
  4. Rodar os testes.
  5. Publicar.
  6. Enviar os e-mails de cancelados com `email_cancelados.py`.
- **"Pix"**: só os comprovantes. Conferir os novos no Drive, gravar na `compconf` e rodar `pix.py` sem consultar o SGA.
- **"Pix DD"**: imagem de ganho ("Meta batida. Mais ganho para você."). Base = R$ 50, residência = R$ 100, só com contrato ativo. Inside Sales não ganha; instalação cancelada não ganha.
- **"ranking"**: pertence a outra conversa.

## 5. Regras de negócio (definidas pelo Rafael)
- **Comprovante**: Pix, boleto pago, recibo em papel da Exodus (dinheiro ou débito) e **print de pagamento no cartão de crédito** valem como pagamento (desde 30/10).
- **Valor**: o que entra na soma e no "a receber" é o **valor encontrado no comprovante**. Se divergir do informado pelo especialista, vale o do comprovante (01/11). No registro: `valor` = lido e `vi` = informado.
- **Descontos (Power CRM)**: só contam as cotações em **venda concretizada** (`cardStatus` = 5). Cotações arquivadas (`isShelved` = S) e as de outras etapas do funil são ignoradas (01/11).
- **Rastreador não cobrado por meta (ex.: Meta 21/10, 28/10, 30/10)**: só vale se a **data do contrato no SGA** for do mês da meta (`regras[placa].mes`). Ativou em outro mês = cobra. Sem placa: usar o chassi ou `NOME:<NOME COMPLETO NORMALIZADO>`.
- **Região dos Lagos** (04/11): associado de Rio das Ostras, Cabo Frio, Macaé, Araruama, São Pedro da Aldeia, Maricá, Saquarema, Casimiro de Abreu, Arraial do Cabo, Armação dos Búzios, Iguaba Grande, Silva Jardim ou Campos dos Goytacazes: o rastreador desconta **R$ 50** (base ou residência). Promoção que libera o rastreador (meta, `nc`) continua sem desconto. Cidade = `clientCity` da cotação no Power CRM (`ades[].cid`); sem SGA, `kit/cid_pc.py` preenche. Lista em `LAGOS` na página. Teste T15.
- **TOP 3 Plantão**: regra `plt` (desconto conta como plantão). Sem mês definido.
- **Validação manual**: `regras[placa] = {val: true, forma: "cartão de crédito", mes}` conta a adesão como validada sem boleto.
- **Cores**:
  - Comprovantes: branco = sem comprovante; amarelo = anexado (verificação de hora em hora); azul com letra branca = valor conferido pelo sistema (2x ao dia ou pelo coordenador); verde-escuro com letra branca = baixa do financeiro.
  - Validadas: azul = 1º boleto pago; letras verdes = reativou e aguarda o 2º boleto; verde-escuro = reativação validada.
  - Cancelados: branco com letras verdes = liberado para resgatar com promoção; amarelo = pedir análise ao coordenador antes do contato; vermelho = não contatar (se o associado procurar, pedir análise ao coordenador).
- **Remarketing realizado** (01/11): quem está na lista do remarketing ou nos cancelados recentes e voltou com contrato a partir de 01/10/2026 (veículo novo ou o mesmo), ou teve o veículo cancelado reativado a partir de 01/10/2026, e hoje está Ativo, Ativo – Pendente Instalação, Aguardando instalação ou Dispensa instalação. Reconhecido pelo associado (matrícula) e pelo CPF (`cpf_associado`). Nos cancelados recentes, o contrato precisa ser na data do cancelamento ou depois. O card fica verde-escuro com letras brancas, com "Parabéns! Você conseguiu realizar esse remarketing." e a data. A mensagem e o WhatsApp ficam travados e não sai e-mail de campanha. Na lista do remarketing há o contador **Reativados** (verde-escuro, letra branca; ao tocar, filtra) e o filtro "Reativados"; nos cancelados recentes, o filtro "Reativados (N)". Pendentes e Enviados não contam os reativados. Dados: `META.resg` (matrícula → {dc, tp, pl, sit}) e `canc[].rs`. Testes T12 e T13.
- **Promoção de resgate**: margem ≥ 70% e ≥ 3 boletos pagos (BI Brasil Atuarial).
- **Reativação**: print do líder + lista do financeiro ou SGA. Validada quando paga o boleto seguinte. **Não entra em adesões nem na taxa de validação; soma só no bônus do líder** (05/11). Adesões = contratos pela data de contrato no SGA. Dados: `series.*.rt/rv` (reativações e validadas), a página desconta de `ad/va` e guarda `vb` para o bônus. Teste T16. Prazo de envio por mês em `rtcfg.prazos`.
- **Termos**: "especialista" (não voluntário), "equipe" (não cooperativa). A Exodus é Proteção Veicular, nunca "seguradora" nem "empresa".

## 6. Histórico de erros (sintoma → causa → correção → teste)
| Data | Sintoma | Causa | Correção | Teste |
|---|---|---|---|---|
| 30/10 e 31/10 | Log com "BLOQUEADO" | Token do SGA bloqueado por excesso de extração (várias tarefas usam o mesmo token) | Parar, não repetir; aplicar só os comprovantes com `pix.py` e publicar | Regra 1.4 |
| 27/10 | `JSONDecodeError` em `/listar/veiculo` | Oscilação do SGA | Rodar de novo uma vez | — |
| 28/10 | 406 "Parâmetros Inválidos" na 1ª chamada | SGA recusa o início de paginação 0 | O script já tenta de novo sozinho | — |
| 27/10 | Comprovante do Luis Paes não aparecia | Adesão sem placa usa o chassi; a chave "SP…" não casava | Chave = placa, senão chassi, senão "SP"+nome+data | T6 |
| 27/10 | `create_file` do Drive falhou | Campo "description" inexistente e base64 redigitado inválido | Usar o asset da página ou `update_file` no arquivo já existente. Nunca redigitar base64 | — |
| 30/10 | Publicar `.py` no Kit falhou | Extensão `.py` não é servida | Usar `files` com `contentType: "text/plain"` | — |
| 31/10 | Rastreador de meta liberado em contrato de outro mês | Regra sem mês | `regras.mes` e conferência `rg.mes === r.m` na página e nos scripts | T4 |
| 01/11 | Valor errado no "a receber" (Ruth, Jacqueline, Mauro) | Usava o valor informado | `valor` = lido no comprovante e `vi` = informado | T5 |
| 01/11 | Aba de comprovantes vazia no dia 1º | Mês novo ainda sem adesões | O mês anterior continua no seletor (abrir nele por padrão: aguardando decisão do Rafael) | T3 |
| 01/11 | Comprovante anexado não aparecia até a atualização | Página não sabe do envio feito pelo Google | Amarelo local na hora mais a tarefa de hora em hora | T3 (cores) |
| 31/10 | Arquivo do Guilherme não era comprovante | Print de WhatsApp enviado pelo botão do líder (descrição sem placa) | Ignorar arquivos cuja descrição não tem "placa" e "mes" | — |
| 21/10 | Pix com valor trocado ("Maria Luiza" de base para residência) | Campo `inst` desatualizado | Recalcular com SGA atual antes da imagem | — |
| 01/11 | Menu principal publicado "sem design" (cards crus, foto enorme) | O CSS novo foi colocado no `<style>` do esqueleto (antes do `<title>`), que a publicação substitui | Todo CSS da página fica DEPOIS do `<title>`, no `<style>` da própria página | T11 |
| 03/11 | Liderado novo com o mesmo início de nome de outro (Rodrigo Moraes Venâncio × Rodrigo Moraes Luiz) | O login usa as 2 primeiras palavras do nome; "Rodrigo Moraes" já existia. E ele não tem vendas no próprio nome no SGA | Login "Rodrigo Venâncio" (id 99, equipe Elite, `sga` = RODRIGO MORAES VENANCIO). Sem vendas no SGA, o script usa a equipe do cadastro (`eqs`) | T14 |
| 03/11 | Atualização parou: `ValueError` em `VC = dict(OLD.get("vcache"))`; página foi de 1,1 MB para 1,9 MB | A regra das vendas concretizadas (01/11) usou o nome `VC`, que já era o cache das validadas: o bloco `all` passou a guardar as 1.561 cotações do Power CRM no lugar do `vcache` | Variável renomeada para `VCOT`; `vcache` restaurado da atualização de 01/11 22:16; o script recusa publicar se o `vcache` não for um dicionário | assert no script |
| 04/11 | SGA recusou o login (401 "Login ou senha inválido") e oscilou (ReadTimeout/ProxyError) | Instabilidade ou bloqueio do SGA | Parar a extração (regra 1.4) e aplicar comprovantes/cidades sem SGA (`cid_pc.py` + `pix.py`) | Regra 1.4 |
| — | Funções da página inacessíveis no teste (`CP is not defined`) | Código dentro de uma IIFE | Gancho `window.__teste` só em `file://` | T4–T6 |
| 07/11 | Escritório novo no Render não ligava: "failed to resolve host" e depois "password authentication failed"; um pedaço da senha do banco apareceu no log | Senha do banco escrita à mão no meio do DATABASE_URL (com `@`, colchete e quebra de linha) | Senha em variável separada (`DATABASE_PASSWORD`), encaixada pelo servidor no lugar do `[YOUR-PASSWORD]`; falha de conexão explicada em português, sem a senha; senha do banco trocada | `tests/test_banco_config.py` |
| 08/11 | Link de cadastro aberto já logado ia para o menu; ao trocar de conta, o Google voltava com "acesso não liberado" | O link se perdia ao sair e entrar de novo | Links de cadastro substituídos pelo endereço único com primeiro acesso por CPF e WhatsApp (decisão do Rafael); quem entra pelo Google sem CPF recebe o pedido de CPF em seguida | `tests/test_cadastro.py`, `tests/test_interface.py` |

## 6.1 Criar acesso de especialista (liderado)
1. Novo `id` = próximo número; chave `k` aleatória (32 bytes). Entrada em `spec_keys.json` com `nome`, `eqs` e `sga` (nome exato do voluntário no SGA).
2. No `vault` da página: `specs[id]` com `{u, nome, equipes, rows}` e `users[sha256(pepper|LOGIN)[:24]]` com a chave embrulhada pela senha (PBKDF2). LOGIN = 2 primeiras palavras do nome (sem "de/da/dos"); se já existir, usar primeiro + último nome.
3. Bloco `evo.e[id]` (a próxima atualização refaz sozinha). Senha de 4 dígitos vai para o Excel do Rafael, nunca para o Kit.

## 7. Armazenamento (análise de 01/11/2026)
- **Página**: estável em cerca de 1 MB (janelas de 12 meses de adesões e 2 meses de cancelados).
- **Documento `reativ/<dono>`**: guarda quase todos os prints e cresce cerca de 22 KB por mês. **Enche (256 KB) por volta de ago/2027**. Antes disso, separar as fichas por mês.
- **Assets**: 38 MB de 1 GB.
- **Versões**: cada publicação gera uma versão de cerca de 1 MB. A tarefa de hora em hora só publica quando há mudança.
- **Prints de reativação** (decisão do Rafael em 01/11): sem backup. As imagens com mais de 5 meses são apagadas todo mês pela limpeza automática, e os registros e tabelas não mudam. Além disso, para não sobrecarregar: antes de o documento `reativ/<dono>` chegar a ~200 KB, separar as fichas por mês. As imagens ficam onde estão; nada é apagado sem confirmação.
