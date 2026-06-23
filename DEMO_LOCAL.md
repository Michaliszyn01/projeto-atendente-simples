# Demo Local

## Objetivo

Esta demo serve para apresentar localmente o MVP do atendente inteligente, usando arquivos JSON e o painel administrativo em Streamlit.

## Como preparar os dados demo

Rode o comando abaixo na raiz do projeto:

```bash
python scripts/gerar_dados_demo.py
```

O script renova somente os registros marcados como demo e preserva registros locais que não sejam de demonstração.

## Como abrir o painel

```bash
streamlit run app/admin_dashboard.py
```

## Como rodar os testes

```bash
python -m pytest -q
```

## O que observar na demonstração

- métricas do topo;
- agenda do dia;
- próximos agendamentos;
- cancelamentos;
- remarcações;
- horários disponíveis;
- solicitações.

## Limitações atuais

Esta ainda é uma demo local. O projeto não possui WhatsApp real, API, login ou banco de dados robusto nesta etapa.
