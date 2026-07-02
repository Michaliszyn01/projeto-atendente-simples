# Demo Local e Teste Real

Este projeto roda localmente com Python, SQLite local, canais de teste e integracao real opcional com WhatsApp Cloud API da Meta. Ele nao possui IA, login ou banco externo nesta etapa.

## Instalar dependencias

Use um ambiente virtual antes de instalar:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Em Linux/macOS, ative com `source .venv/bin/activate`.

## Rodar testes

```bash
python -m pytest -q
```

## Rodar terminal

```bash
python main.py
```

O terminal usa `app/terminal_app.py`, `channels/terminal.py` e `ConversationEngine`. Neste canal nao existe telefone real, entao o fluxo continua perguntando o telefone quando precisar.

## Rodar fake WhatsApp

O fake WhatsApp e usado por codigo ou testes, sem Meta API. Exemplo minimo:

```python
from channels.base import OutgoingMessage
from channels.fake_whatsapp import FakeWhatsAppChannel
from core.conversation.engine import ConversationEngine

channel = FakeWhatsAppChannel()
engine = ConversationEngine()

incoming = channel.build_incoming_from_payload(
    {"from": "whatsapp:+5514999999999", "message": "agendar"}
)
engine.start(incoming.sender_id)
response = engine.process_message(incoming.sender_id, incoming.text)
channel.send(OutgoingMessage(incoming.channel, incoming.sender_id, response))
```

Quando o `sender_id` for um WhatsApp valido, o telefone normalizado e usado como telefone principal do cliente.

## Rodar API HTTP generica

Para testar n8n, Evolution API, Z-API ou outro provedor pelo endpoint generico, suba a API local:

```bash
uvicorn app.webhook_api:app --reload
```

`WEBHOOK_API_KEY` e obrigatoria. Defina uma chave antes de subir a API; sem ela, `POST /webhook/whatsapp` retorna erro de configuracao.

PowerShell:

```powershell
$env:WEBHOOK_API_KEY="sua_chave"
uvicorn app.webhook_api:app --reload
```

Linux/macOS:

```bash
export WEBHOOK_API_KEY="sua_chave"
uvicorn app.webhook_api:app --reload
```

Health check publico:

```bash
curl http://127.0.0.1:8000/health
```

Endpoint protegido por `WEBHOOK_API_KEY`:

```text
POST /webhook/whatsapp
```

Payload aceito:

```json
{
  "from": "whatsapp:+5514999999999",
  "message": "agendar"
}
```

Tambem aceita:

```json
{
  "telefone": "+55 (14) 99999-9999",
  "mensagem": "agendar"
}
```

Exemplo com `curl`:

```bash
curl -X POST http://127.0.0.1:8000/webhook/whatsapp ^
  -H "Content-Type: application/json" ^
  -H "X-API-Key: sua_chave" ^
  -d "{\"from\":\"whatsapp:+5514999999999\",\"message\":\"agendar\"}"
```

A API generica apenas recebe a mensagem e devolve a resposta em JSON. Ela nao envia mensagem real para WhatsApp.

## Teste com WhatsApp Cloud API da Meta

A integracao real com a Meta e opcional e nao substitui `POST /webhook/whatsapp`. Se as variaveis da Meta nao estiverem configuradas, o projeto continua funcionando localmente com terminal, fake WhatsApp, painel e API generica.

No primeiro contato de cada numero de WhatsApp, a resposta inclui uma mensagem de boas-vindas com as opcoes de atendimento. A flag fica salva na sessao SQLite, entao a saudacao nao aparece de novo para o mesmo numero.

Variaveis de ambiente:

```env
WEBHOOK_API_KEY=coloque_uma_chave_forte_aqui
META_WHATSAPP_TOKEN=coloque_o_token_da_meta_aqui
META_WHATSAPP_PHONE_NUMBER_ID=coloque_o_phone_number_id_aqui
META_WHATSAPP_VERIFY_TOKEN=coloque_um_verify_token_forte_aqui
META_GRAPH_VERSION=v20.0
ADMIN_USERNAME=coloque_um_usuario_admin_aqui
ADMIN_PASSWORD=coloque_uma_senha_forte_aqui
```

Use `.env.example` como referencia e nunca commite tokens reais. `META_GRAPH_VERSION` usa `v20.0` quando nao for definida.

Suba a API:

```bash
uvicorn app.webhook_api:app --reload
```

Cadastre no painel da Meta uma URL HTTPS publica:

```text
https://SEU-TUNEL-HTTPS/webhook/meta
```

Use no painel da Meta o mesmo verify token configurado em `META_WHATSAPP_VERIFY_TOKEN`. Para testar localmente, use um tunel HTTPS para a porta 8000:

```bash
ngrok http 8000
```

Endpoints adicionados:

```text
GET /webhook/meta
POST /webhook/meta
```

O `GET /webhook/meta` valida `hub.mode`, `hub.verify_token` e `hub.challenge`. O `POST /webhook/meta` recebe mensagens reais de texto, ignora eventos de status, processa a conversa com `ConversationEngine` e tenta responder pela Cloud API quando `META_WHATSAPP_TOKEN` e `META_WHATSAPP_PHONE_NUMBER_ID` existem.

O painel administrativo roda separado:

```bash
streamlit run app/admin_dashboard.py
```

Smoke local sem chamar a Meta real:

```bash
python scripts/smoke_meta_payload.py
```

Esse script envia um payload parecido com o payload da Meta para `/webhook/meta`, apenas para validar extracao de telefone e mensagem.

## Banco SQLite

O banco padrao fica em:

```text
data/agenda.db
```

Esse arquivo e local, pode conter dados reais e nao deve ir para GitHub/deploy. A pasta `data/` deve manter apenas `data/.gitkeep` versionado.

## Resetar dados de teste

Para zerar agenda e solicitacoes locais:

```bash
python scripts/limpar_dados.py
```

Para gerar dados ficticios para apresentacao:

```bash
python scripts/gerar_dados_demo.py
```

## Migrar JSON antigo para SQLite

Se existir uma agenda antiga em `data/agenda.json`, rode:

```bash
python -m core.storage.migrate_json_to_sqlite
```

A migracao le `data/agenda.json` e grava em `data/agenda.db`, preservando os IDs quando existirem.

## Painel local

```bash
streamlit run app/admin_dashboard.py
```

Defina login e senha antes de abrir o painel fora do seu ambiente local:

```powershell
$env:ADMIN_USERNAME="admin"
$env:ADMIN_PASSWORD="sua_senha_forte"
& "C:\Users\Eduardo\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m streamlit run app/admin_dashboard.py
```

Sem `ADMIN_USERNAME` e `ADMIN_PASSWORD`, o painel bloqueia o acesso e exibe aviso de credenciais administrativas ausentes. O painel mostra dados sensiveis de clientes, telefones e agenda; nao deixe publico sem senha. Para producao real, o ideal futuro e autenticacao mais forte.

## Checklist manual

1. Agendar pelo terminal: `python main.py`, escolher `agendar`, preencher dia, servico, profissional, periodo, horario, nome e telefone.
2. Consultar agendamento pelo terminal usando o telefone salvo.
3. Cancelar agendamento pelo terminal e confirmar que o status mudou.
4. Remarcar agendamento pelo terminal e confirmar nova data/horario.
5. Pedir humano no meio do agendamento, por exemplo na etapa de horario digitar `humano` ou `quero falar com alguem`; o fluxo deve encerrar e registrar `humano_solicitado`.
6. Simular dois numeros diferentes no fake WhatsApp e confirmar que as sessoes nao misturam estado:

```python
from channels.fake_whatsapp import FakeWhatsAppChannel
from core.conversation.engine import ConversationEngine

channel = FakeWhatsAppChannel()
engine = ConversationEngine()

m1 = channel.build_incoming_from_payload({"from": "whatsapp:+5514999999999", "message": "agendar"})
m2 = channel.build_incoming_from_payload({"from": "whatsapp:+5514888888888", "message": "consultar"})

engine.start(m1.sender_id)
engine.start(m2.sender_id)
print(engine.process_message(m1.sender_id, m1.text))
print(engine.process_message(m2.sender_id, m2.text))
```

## Preparar para GitHub/deploy simples

Antes de enviar, confira:

```bash
python -m pytest -q
git status --short
```

Nao envie `data/agenda.db`, `data/agenda.json`, `data/solicitacoes.json`, `pytest_tmp/`, `.pytest_cache/`, `__pycache__/`, `.env`, `venv/` ou `.venv/`.
