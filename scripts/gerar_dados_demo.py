import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config.config_loader import carregar_config
from core.storage.json_repository import DEFAULT_AGENDA_PATH


DEFAULT_SOLICITACOES_PATH = PROJECT_ROOT / "data" / "solicitacoes.json"
DEMO_ORIGEM = "demo"
DEMO_AGENDA_PREFIX = "demo-agenda-"
DEMO_SOLICITACAO_PREFIX = "demo-solicitacao-"
SERVICOS_DEMO_PADRAO = {
    "corte": 30,
    "barba": 30,
    "corte + barba": 60,
}
CLIENTES_FICTICIOS = [
    "João Silva",
    "Pedro Santos",
    "Ana Costa",
    "Lucas Lima",
    "Mariana Rocha",
    "Carla Almeida",
    "Rafael Nunes",
    "Bianca Torres",
    "Gustavo Paiva",
]
TELEFONES_FICTICIOS = [
    "14991000001",
    "14991000002",
    "14991000003",
    "14991000004",
    "14991000005",
    "14991000006",
    "14991000007",
    "14991000008",
    "14991000009",
]


def gerar_dados_demo(
    agenda_path: str | Path = DEFAULT_AGENDA_PATH,
    solicitacoes_path: str | Path = DEFAULT_SOLICITACOES_PATH,
    config: dict | None = None,
    hoje: date | None = None,
) -> tuple[list[dict], list[dict]]:
    config = config or carregar_config()
    hoje = hoje or date.today()
    agenda_path = Path(agenda_path)
    solicitacoes_path = Path(solicitacoes_path)

    agenda = _substituir_dados_demo(
        _carregar_json_lista(agenda_path),
        criar_agenda_demo(config, hoje),
        id_prefix=DEMO_AGENDA_PREFIX,
    )
    solicitacoes = _substituir_dados_demo(
        _carregar_json_lista(solicitacoes_path),
        criar_solicitacoes_demo(config, hoje),
        id_prefix=DEMO_SOLICITACAO_PREFIX,
    )

    _salvar_json(agenda_path, agenda)
    _salvar_json(solicitacoes_path, solicitacoes)
    return agenda, solicitacoes


def criar_agenda_demo(config: dict, hoje: date) -> list[dict]:
    servicos = _servicos_demo(config)
    profissionais = list(config.get("profissionais", ["Marcos", "Julio"])) or ["Equipe"]
    horarios = _horarios_demo(config)
    agenda_planejada = [
        (0, "09:00", 0, 0, "agendado"),
        (0, "09:30", 1, 1, "agendado"),
        (0, "10:30", 2, 0, "remarcado"),
        (0, "15:30", 0, 1, "cancelado"),
        (1, "09:00", 2, 1, "agendado"),
        (1, "14:00", 0, 0, "agendado"),
        (2, "10:00", 1, 0, "agendado"),
        (3, "16:00", 2, 1, "agendado"),
        (5, "11:00", 0, 0, "agendado"),
    ]
    agenda = []

    for indice, (offset_dias, horario_padrao, indice_servico, indice_profissional, status_demo) in enumerate(agenda_planejada):
        cliente = CLIENTES_FICTICIOS[indice % len(CLIENTES_FICTICIOS)]
        servico, duracao = servicos[indice_servico % len(servicos)]
        profissional = profissionais[indice_profissional % len(profissionais)]
        data_agendamento = hoje + timedelta(days=offset_dias)
        horario = horario_padrao if horario_padrao in horarios else horarios[indice % len(horarios)]
        status = "cancelado" if status_demo == "cancelado" else "agendado"
        criado_em = datetime.combine(hoje, datetime.min.time()).replace(hour=8, minute=indice).isoformat(timespec="seconds")

        agendamento = {
            "id": f"{DEMO_AGENDA_PREFIX}{indice + 1}",
            "origem": DEMO_ORIGEM,
            "nome": cliente,
            "telefone": TELEFONES_FICTICIOS[indice],
            "servico": servico,
            "data": data_agendamento.isoformat(),
            "horario": horario,
            "profissional": profissional,
            "duracao_minutos": int(duracao),
            "status": status,
            "criado_em": criado_em,
        }

        if status == "cancelado":
            agendamento["cancelado_em"] = datetime.combine(hoje, datetime.min.time()).replace(hour=12, minute=indice).isoformat(timespec="seconds")
            agendamento["historico"] = [{"acao": "cancelado", "feito_em": agendamento["cancelado_em"]}]

        if status_demo == "remarcado":
            agendamento["remarcado_em"] = datetime.combine(hoje, datetime.min.time()).replace(hour=13, minute=30).isoformat(timespec="seconds")
            agendamento["historico"] = [
                {
                    "acao": "remarcado",
                    "data_anterior": (data_agendamento - timedelta(days=1)).isoformat(),
                    "horario_anterior": "09:00",
                    "profissional_anterior": profissional,
                    "data_nova": agendamento["data"],
                    "horario_novo": agendamento["horario"],
                    "profissional_novo": profissional,
                    "feito_em": agendamento["remarcado_em"],
                }
            ]

        agenda.append(agendamento)

    return agenda


def criar_solicitacoes_demo(config: dict, hoje: date) -> list[dict]:
    categorias = list(config.get("categorias", ["informacao", "orcamento", "humano"]))
    return [
        {
            "id": f"{DEMO_SOLICITACAO_PREFIX}1",
            "origem": DEMO_ORIGEM,
            "nome": "Fernanda Martins",
            "telefone": "14992000001",
            "categoria": categorias[0],
            "descricao": "Gostaria de saber valores para corte e barba no sábado.",
            "criado_em": datetime.combine(hoje, datetime.min.time()).replace(hour=10, minute=15).isoformat(timespec="seconds"),
            "status": "novo",
        },
        {
            "id": f"{DEMO_SOLICITACAO_PREFIX}2",
            "origem": DEMO_ORIGEM,
            "nome": "Thiago Ribeiro",
            "telefone": "14992000002",
            "categoria": categorias[min(1, len(categorias) - 1)],
            "descricao": "Cliente quer confirmar se há pacote mensal de barbearia.",
            "criado_em": datetime.combine(hoje, datetime.min.time()).replace(hour=11, minute=5).isoformat(timespec="seconds"),
            "status": "em análise",
        },
    ]


def _servicos_demo(config: dict) -> list[tuple[str, int]]:
    servicos_config = config.get("servicos", {})
    servicos = []
    for nome_servico, duracao_padrao in SERVICOS_DEMO_PADRAO.items():
        duracao = servicos_config.get(nome_servico, duracao_padrao)
        servicos.append((nome_servico, int(duracao)))
    return servicos


def _horarios_demo(config: dict) -> list[str]:
    horarios_config = config.get("horarios", {})
    horarios = []
    for lista_horarios in horarios_config.values():
        horarios.extend(lista_horarios)
    return horarios or ["09:00", "10:00", "14:00", "15:00"]


def _carregar_json_lista(caminho: Path) -> list[dict]:
    if not caminho.is_absolute():
        caminho = PROJECT_ROOT / caminho
    if not caminho.exists():
        return []

    try:
        dados = json.loads(caminho.read_text(encoding="utf-8") or "[]")
    except json.JSONDecodeError:
        return []

    if not isinstance(dados, list):
        return []
    return [item for item in dados if isinstance(item, dict)]


def _substituir_dados_demo(dados_atuais: list[dict], dados_demo: list[dict], id_prefix: str) -> list[dict]:
    dados_preservados = [
        item
        for item in dados_atuais
        if not _eh_dado_demo(item, id_prefix)
    ]
    return dados_preservados + dados_demo


def _eh_dado_demo(item: dict, id_prefix: str) -> bool:
    item_id = str(item.get("id", ""))
    return item.get("origem") == DEMO_ORIGEM or item_id.startswith(id_prefix) or item_id.startswith("demo-")


def _salvar_json(caminho: Path, dados: list[dict]) -> None:
    if not caminho.is_absolute():
        caminho = PROJECT_ROOT / caminho
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    gerar_dados_demo()
    print("Dados demo gerados com sucesso.")


if __name__ == "__main__":
    main()
