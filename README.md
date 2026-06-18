# Projeto Atendente Simples

MVP em Python puro para atendimento pelo terminal, sem IA, sem WhatsApp, sem web e sem banco externo.

O comportamento vem de `config/config.json`, permitindo usar o mesmo motor em modos como `barbearia`, `clinica` e `loja`.

## Arquitetura

A conversa agora passa por canais. Um canal recebe a mensagem, envia para a `ConversationEngine`, recebe a resposta e devolve ao usuário.

```text
Canal -> ConversationEngine -> Canal
```

O canal real atual é:

```text
channels/terminal.py
```

Ele concentra `input()` e `print()` do terminal, sem regra de negócio.

O motor reutilizável fica em:

```text
core/conversation/engine.py
```

Ele:

```text
recebe session_id + mensagem
mantém o estado da conversa por sessão
chama o fluxo de atendimento
retorna a resposta em texto
```

Existe também um canal falso para simulação:

```text
channels/fake_whatsapp.py
```

Ele não usa API real, não conecta na Meta e não envia mensagens externas. Serve apenas para testes e demonstração de como um WhatsApp futuro poderia reaproveitar a engine.

Exemplo de uso direto:

```python
from core.conversation.engine import ConversationEngine
from core.storage.json_repository import JsonAgendaRepository

engine = ConversationEngine(agenda_repository=JsonAgendaRepository())

print(engine.start("cliente_1"))
resposta = engine.process_message("cliente_1", "agendar")
print(resposta)
```

Exemplo com fake WhatsApp:

```python
from channels.base import OutgoingMessage
from channels.fake_whatsapp import FakeWhatsAppChannel
from core.conversation.engine import ConversationEngine
from core.storage.json_repository import JsonAgendaRepository

channel = FakeWhatsAppChannel()
engine = ConversationEngine(agenda_repository=JsonAgendaRepository())

incoming = channel.build_incoming("14999999999", "agendar")
engine.start(incoming.sender_id)
response = engine.process_message(incoming.sender_id, incoming.text)

channel.send(
    OutgoingMessage(
        channel=incoming.channel,
        recipient_id=incoming.sender_id,
        text=response,
    )
)
```

WhatsApp real ainda não foi implementado.

## Como rodar

```bash
python main.py
```

O atendimento acontece no terminal. Digite uma das opções do menu inicial e siga as perguntas.

O `main.py` só chama `app/terminal_app.py`, que orquestra `TerminalChannel` e `ConversationEngine`. As regras de agendamento, consulta, cancelamento e remarcação não ficam no terminal nem no canal.

## Painel administrativo local

O projeto também possui um painel visual simples em Streamlit para o dono do estabelecimento acompanhar os dados locais:

```bash
streamlit run app/admin_dashboard.py
```

O painel mostra:

```text
dados básicos do estabelecimento vindos de config/config.json
agenda por data
agenda de hoje e amanhã pela seleção de data
filtro por profissional
agendamentos cancelados
solicitações da loja em data/solicitacoes.json
horários disponíveis por data, período, profissional e serviço
resumo do dia com totais, serviços, profissionais, primeiro e último horário
```

Ele é apenas local, não possui login real nesta etapa e continua usando JSON como armazenamento. Ainda não existe IA, OpenAI, WhatsApp real, banco externo, Flask, FastAPI ou Django.

Os dados reais continuam em:

```text
data/agenda.json
data/solicitacoes.json
```

Esses arquivos podem conter dados reais de clientes e não devem ser enviados ao GitHub. Eles estão no `.gitignore`.

Para instalar a dependência visual do painel:

```bash
pip install -r requirements.txt
```

Para preencher o painel com dados fictícios seguros para demonstração:

```bash
python scripts/gerar_dados_demo.py
```

O script cria agendamentos e solicitações fictícias em:

```text
data/agenda.json
data/solicitacoes.json
```

Para limpar os dados locais e voltar os arquivos para listas vazias:

```bash
python scripts/limpar_dados.py
```

Fluxo sugerido para demonstração:

```bash
python scripts/gerar_dados_demo.py
streamlit run app/admin_dashboard.py
```

## Como testar

```bash
python -m pytest -q
```

## Configuração

O arquivo principal carregado pelo sistema é:

```text
config/config.json
```

Exemplos prontos ficam em:

```text
exemplos/barbearia.json
exemplos/clinica.json
exemplos/loja.json
```

Para trocar o modo, substitua o conteúdo de `config/config.json` pelo exemplo desejado.

Exemplo PowerShell:

```powershell
Copy-Item exemplos\clinica.json config\config.json
python main.py
```

Para voltar para barbearia:

```powershell
Copy-Item exemplos\barbearia.json config\config.json
python main.py
```

Para loja:

```powershell
Copy-Item exemplos\loja.json config\config.json
python main.py
```

No modo `loja`, o sistema não pede data nem horário. Ele faz um atendimento simples para categoria, orçamento ou humano. Solicitações de orçamento são salvas em `data/solicitacoes.json`.

## Agendamento

No modo com agendamento, o menu inicial aceita variações simples como:

```text
agendar
marcar
marcar horário
consultar
ver agendamento
meu horário
qual meu horário
cancelar
desmarcar
cancelar horário
remarcar
trocar horário
mudar horário
mudar agendamento
alguém
falar com alguém
atendente
humano
```

Fluxo básico:

```text
Olá! Eu sou o assistente virtual da Barbearia Exemplo. O que você deseja fazer?
Responda com:

* agendar
* consultar
* cancelar
* remarcar
* alguém
> agendar
Qual dia você quer agendar? Responda com hoje, amanhã ou uma data no formato DD/MM/AAAA.
> amanhã
Qual serviço você quer? Opções: corte, barba, corte + barba.
> corte
Tem preferência por algum profissional? Opções: Marcos, Julio ou não.
> não
Você prefere manhã ou tarde?
> manhã
Horários disponíveis:
- 09:00 (Marcos ou Julio)
- 09:30 (Marcos ou Julio)
- 10:00 (Marcos ou Julio)
- 10:30 (Marcos ou Julio)
- 11:00 (Marcos ou Julio)
- 11:30 (Marcos ou Julio)

Qual horário você quer?
> 10
Me fala seu nome.
> Eduardo
Me informe seu telefone para contato.
> (14) 99999-9999
Nome: Eduardo
Serviço: corte
Telefone: 14999999999
Dia: 17/06/2026
Horário: 10:00
Profissional: Marcos

Digite sim para confirmar ou não para cancelar.
> sim
Agendamento confirmado! Um atendente te espera no dia 17/06/2026 às 10:00 com Marcos.
```

O telefone é salvo normalizado, mantendo apenas números.

## Consulta de agendamento

Para consultar:

```text
> consultar
Digite o telefone usado no agendamento.
> 14999999999
Encontrei estes agendamentos:

1. Corte com Marcos em 18/06/2026 às 15:00
```

Somente agendamentos com `status: "agendado"` aparecem na consulta.

Se o agendamento já tiver sido remarcado, a consulta mostra a data e horário atuais e informa:

```text
Este agendamento já foi remarcado anteriormente.
```

## Cancelamento

Para cancelar:

```text
> cancelar
Digite o telefone usado no agendamento.
> 14999999999
Encontrei estes agendamentos ativos:

1. Corte com Marcos em 18/06/2026 às 15:00

Digite o número do agendamento que deseja cancelar ou digite voltar.
> 1
Tem certeza que deseja cancelar este agendamento? Responda sim ou não.
> sim
Agendamento cancelado com sucesso.
```

O registro não é apagado do JSON. O sistema altera o `status` para `cancelado`, adiciona `cancelado_em` e registra um evento no `historico`. Horários cancelados deixam de bloquear a agenda.

## Remarcação

Para remarcar:

```text
> remarcar
Digite o telefone usado no agendamento.
> 14999999999
Encontrei estes agendamentos ativos:

1. Corte com Marcos em 18/06/2026 às 15:00

Digite o número do agendamento que deseja remarcar ou digite voltar.
> 1
Para qual dia deseja remarcar?
> 19/06/2026
Você prefere manhã ou tarde?
> tarde
Horários disponíveis:
- 14:00
- 14:30
- 15:00
- 15:30
- 16:00
- 16:30
- 17:00
- 17:30

Qual novo horário você quer?
> 14:30
Confirmando remarcação:
Agendamento atual:
Corte com Marcos em 18/06/2026 às 15:00

Novo agendamento:
Corte com Marcos em 19/06/2026 às 14:30

Digite sim para confirmar ou não para cancelar.
> sim
Agendamento remarcado com sucesso.
```

A remarcação atualiza o mesmo registro no `agenda.json`, mantendo o mesmo `id`. O sistema adiciona `remarcado_em` e um evento no `historico` com data, horário e profissional anteriores e novos.

Ao buscar horários para remarcação, o próprio agendamento é ignorado para não bloquear seu horário atual. Outros agendamentos ativos continuam bloqueando conflitos normalmente.

## Arquivos de dados

Os arquivos reais ficam em:

```text
data/agenda.json
data/solicitacoes.json
```

Eles começam como listas vazias (`[]`) e estão no `.gitignore`, porque podem conter dados reais de clientes. Não envie esses arquivos para o GitHub com dados reais.

Para uma demonstração sem dados reais, rode:

```bash
python scripts/gerar_dados_demo.py
```

Para zerar os dados locais:

```bash
python scripts/limpar_dados.py
```

Exemplos seguros ficam em:

```text
data/exemplo_agenda.json
data/exemplo_solicitacoes.json
```

## Comandos do terminal

Durante um fluxo em andamento:

```text
cancelar
voltar
menu
sair
```

`cancelar` encerra o fluxo atual. `voltar` retorna uma etapa quando fizer sentido. `menu` volta ao menu inicial. `sair` encerra o atendimento. No menu inicial, `cancelar` inicia o fluxo de cancelamento de agendamento.
