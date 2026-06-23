# Demo Local

## Objetivo

Esta demo serve para apresentar localmente o MVP do atendente inteligente para barbearias, usando arquivos JSON e o painel administrativo em Streamlit.

## Como preparar os dados demo

Na raiz do projeto, rode primeiro a limpeza dos dados locais se quiser uma apresentação totalmente previsível:

```bash
python scripts/limpar_dados.py
```

Depois gere os dados fictícios da demonstração:

```bash
python scripts/gerar_dados_demo.py
```

O gerador renova somente registros marcados como demo e preserva registros locais que não sejam de demonstração.

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
- próximos horários;
- cancelamentos;
- remarcações;
- horários livres;
- solicitações;
- filtros laterais do estabelecimento.

## Limitações atuais

Esta ainda é uma demo local. O projeto não possui WhatsApp real, API, login ou banco de dados robusto nesta etapa.
