from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ConversationState:
    etapa: str = "inicio"
    data: Optional[str] = None
    servico: Optional[str] = None
    profissional_preferido: Optional[str] = None
    periodo: Optional[str] = None
    horario: Optional[str] = None
    profissional: Optional[str] = None
    nome: Optional[str] = None
    telefone: Optional[str] = None
    boas_vindas_enviada: bool = False
    humano_solicitado: bool = False
    etapa_antes_humano: Optional[str] = None
    categoria: Optional[str] = None
    descricao_orcamento: Optional[str] = None
    opcoes_horarios: list[dict[str, str]] = field(default_factory=list)
    agendamentos_encontrados: list[dict] = field(default_factory=list)
    agendamento_selecionado: Optional[dict] = None
    nova_data: Optional[str] = None
    novo_periodo: Optional[str] = None
    novo_horario: Optional[str] = None
