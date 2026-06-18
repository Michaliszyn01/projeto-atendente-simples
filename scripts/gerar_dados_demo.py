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
CLIENTES_FICTICIOS = [
    "João Silva",
    "Pedro Santos",
    "Ana Costa",
    "Lucas Lima",
    "Mariana Rocha",
    "Carla Almeida",
    "Rafael Nunes",
    "Bianca Torres",
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
]


def gerar_dados_demo(
    agenda_path: str | Path = DEFAULT_AGENDA_PATH,
    solicitacoes_path: str | Path = DEFAULT_SOLICITACOES_PATH,
    config: dict | None = None,
    hoje: date | None = None,
) -> tuple[list[dict], list[dict]]:
    config = config or carregar_config()
    hoje = hoje or date.today()
    agenda = criar_agenda_demo(config, hoje)
    solicitacoes = criar_solicitacoes_demo(config, hoje)

    _salvar_json(Path(agenda_path), agenda)
    _salvar_json(Path(solicitacoes_path), solicitacoes)
    return agenda, solicitacoes


def criar_agenda_demo(config: dict, hoje: date) -> list[dict]:
    servicos = list(config.get("servicos", {"corte": 30}).items())
    profissionais = list(config.get("profissionais", ["Marcos", "Julio"])) or ["Equipe"]
    horarios = _horarios_demo(config)
    agenda = []

    for indice, cliente in enumerate(CLIENTES_FICTICIOS):
        servico, duracao = servicos[indice % len(servicos)]
        profissional = profissionais[indice % len(profissionais)]
        data_agendamento = hoje + timedelta(days=indice % 4)
        horario = horarios[indice % len(horarios)]
        status = "cancelado" if indice in {2, 6} else "agendado"
        criado_em = datetime.combine(hoje, datetime.min.time()).replace(hour=8, minute=indice).isoformat(timespec="seconds")

        agendamento = {
            "id": f"demo-{indice + 1}",
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

        if indice == 4:
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
    categorias = list(config.get("categorias", ["produtos", "orcamento", "humano"]))
    return [
        {
            "id": "sol-demo-1",
            "nome": "Fernanda Martins",
            "telefone": "14992000001",
            "categoria": categorias[0],
            "descricao": "Gostaria de saber valores para um pacote.",
            "criado_em": datetime.combine(hoje, datetime.min.time()).replace(hour=10, minute=15).isoformat(timespec="seconds"),
            "status": "novo",
        },
        {
            "id": "sol-demo-2",
            "nome": "Thiago Ribeiro",
            "telefone": "14992000002",
            "categoria": categorias[min(1, len(categorias) - 1)],
            "descricao": "Pedido fictício para demonstração do painel.",
            "criado_em": datetime.combine(hoje, datetime.min.time()).replace(hour=11, minute=5).isoformat(timespec="seconds"),
            "status": "em análise",
        },
    ]


def _horarios_demo(config: dict) -> list[str]:
    horarios_config = config.get("horarios", {})
    horarios = []
    for lista_horarios in horarios_config.values():
        horarios.extend(lista_horarios)
    return horarios or ["09:00", "10:00", "14:00", "15:00"]


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

