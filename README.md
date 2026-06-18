# Projeto Atendente Simples

MVP em Python puro para atendimento pelo terminal, sem IA, sem WhatsApp, sem web e sem banco externo.

O comportamento vem de `config/config.json`, permitindo usar o mesmo motor em modos como `barbearia`, `clinica` e `loja`.

## Como rodar

```bash
python main.py
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

## Exemplo de uso

```text
Olá! Eu sou o assistente virtual desse estabelecimento. Você quer agendar ou falar com alguém? Responda com: agendar ou alguém.
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
Nome: Eduardo
Serviço: corte
Dia: 17/06/2026
Horário: 10:00
Profissional: Marcos

Digite sim para confirmar ou não para cancelar.
> sim
Agendamento confirmado! Um atendente te espera no dia 17/06/2026 às 10:00 com Marcos.
```

Digite `cancelar` em qualquer etapa para encerrar o atendimento.
