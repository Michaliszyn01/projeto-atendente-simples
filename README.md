# Projeto Atendente Simples

MVP 0.3 em Python puro para atendimento pelo terminal, sem IA, sem WhatsApp, sem web e sem banco externo.

O comportamento vem de `config/config.json`, permitindo usar o mesmo motor em modos como `barbearia`, `clinica` e `loja`.

## Como rodar

```bash
python main.py
```

O atendimento acontece no terminal. Digite uma das opções do menu inicial e siga as perguntas.

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
consultar
ver agendamento
cancelar
desmarcar
alguém
falar com alguém
```

Fluxo básico:

```text
Olá! Eu sou o assistente virtual da Barbearia Exemplo. O que você deseja fazer?
Responda com:

* agendar
* consultar
* cancelar
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

O registro não é apagado do JSON. O sistema altera o `status` para `cancelado` e adiciona `cancelado_em`. Horários cancelados deixam de bloquear a agenda.

## Arquivos de dados

Os arquivos reais ficam em:

```text
data/agenda.json
data/solicitacoes.json
```

Eles começam como listas vazias (`[]`) e estão no `.gitignore`, porque podem conter dados reais de clientes. Não envie esses arquivos para o GitHub com dados reais.

Exemplos seguros ficam em:

```text
data/exemplo_agenda.json
data/exemplo_solicitacoes.json
```

Durante um fluxo em andamento, digite `cancelar` para encerrar o atendimento. No menu inicial, `cancelar` inicia o fluxo de cancelamento de agendamento.
