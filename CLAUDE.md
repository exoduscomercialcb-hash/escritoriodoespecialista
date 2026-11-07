# Escritório do Especialista (Exodus Benefícios)

Leia antes de qualquer trabalho:
1. `docs/ESPECIFICACAO.md`: o que construir (Render + Supabase + login com Google + painel do administrador, dados atualizados sem IA).
2. `docs/MANUAL_SISTEMA_ATUAL.md`: regras de negócio e histórico de erros do sistema atual. As regras de negócio não mudam.
3. `referencia/`: página, scripts e testes do sistema atual, para portar a lógica e o visual.

Regras obrigatórias:
- Responder e escrever tudo em português do Brasil. Dono: Rafael Veiga (coordenador).
- SGA, Power CRM e BI são somente leitura. Se o SGA responder BLOQUEADO ou 401 seguido: parar, registrar e não insistir.
- Nenhuma senha, token ou chave no repositório. Tudo em variáveis de ambiente do Render; manter `.env.example` só com os nomes.
- Dados pessoais de associados (nome, CPF, telefone, placa) nunca vão para o repositório, nem em testes: usar dados inventados.
- Todo erro corrigido ganha um teste e uma linha no histórico de erros. Nada vai para a branch principal sem todos os testes passarem.
- Termos: "especialista" (não voluntário), "equipe" (não cooperativa), "liderado" (não afiliado). A Exodus é Proteção Veicular, nunca "seguradora" nem "empresa".
- Fuso horário: America/Sao_Paulo.
