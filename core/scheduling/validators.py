from datetime import date, datetime, timedelta
import re
from typing import Any
import unicodedata

from core.config.config_loader import carregar_config


def normalizar_texto(texto: str) -> str:
    texto = texto.strip().lower()
    texto = "".join(
        char
        for char in unicodedata.normalize("NFD", texto)
        if unicodedata.category(char) != "Mn"
    )
    return " ".join(texto.split())


def normalizar_data(texto: str, hoje: date | None = None) -> str | None:
    data = _extrair_data(texto, hoje=hoje)
    hoje = hoje or date.today()

    if data is None or data < hoje:
        return None

    return data.isoformat()


def validar_data_agendamento(texto: str, hoje: date | None = None) -> tuple[str | None, str | None]:
    hoje = hoje or date.today()
    data = _extrair_data(texto, hoje=hoje)

    if data is None:
        return (
            None,
            "Data inválida. Responda com hoje, amanhã ou uma data válida no formato DD/MM/AAAA.",
        )

    if data < hoje:
        return (
            None,
            (
                "A data informada é anterior ao dia atual "
                f"({formatar_data_br(hoje.isoformat())}). Informe hoje, amanhã ou uma data futura "
                "no formato DD/MM/AAAA."
            ),
        )

    return data.isoformat(), None


def _extrair_data(texto: str, hoje: date | None = None) -> date | None:
    hoje = hoje or date.today()
    valor = normalizar_texto(texto)

    if valor == "hoje":
        return hoje
    if valor == "amanha":
        return hoje + timedelta(days=1)

    try:
        return datetime.strptime(texto.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def formatar_data_br(data_iso: str) -> str:
    try:
        data = datetime.strptime(data_iso, "%Y-%m-%d").date()
    except ValueError:
        return data_iso
    return data.strftime("%d/%m/%Y")


def validar_servico(texto: str, config: dict[str, Any] | None = None) -> str | None:
    config = config or carregar_config()
    valor = normalizar_nome_servico(texto)

    for servico in config.get("servicos", {}):
        servico_normalizado = normalizar_nome_servico(servico)
        if valor == servico_normalizado:
            return servico

        sem_conectivo = servico_normalizado.replace(" + ", " ")
        com_conectivo = servico_normalizado.replace(" + ", " e ")
        if valor in {sem_conectivo, com_conectivo}:
            return servico

    return None


def normalizar_nome_servico(texto: str) -> str:
    valor = normalizar_texto(texto).replace("+", " + ")
    return " ".join(valor.split())


def validar_profissional(texto: str, config: dict[str, Any] | None = None) -> tuple[bool, str | None]:
    config = config or carregar_config()
    valor = normalizar_texto(texto)

    if valor in {"nao", "não", "sem preferencia", "sem preferência", "qualquer", "tanto faz"}:
        return True, None

    for profissional in config.get("profissionais", []):
        if normalizar_texto(profissional) == valor:
            return True, profissional

    return False, None


def validar_periodo(texto: str, config: dict[str, Any] | None = None) -> str | None:
    config = config or carregar_config()
    valor = normalizar_texto(texto)

    for periodo in config.get("horarios", {}):
        if normalizar_texto(periodo) == valor:
            return periodo

    return None


def normalizar_horario(texto: str) -> str | None:
    valor = texto.strip()
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?", valor)

    if not match:
        return None

    hora = int(match.group(1))
    minuto = int(match.group(2) or "0")

    if hora < 0 or hora > 23 or minuto < 0 or minuto > 59:
        return None

    return f"{hora:02d}:{minuto:02d}"


def normalizar_resposta_sim_nao(texto: str) -> str | None:
    valor = normalizar_texto(texto)

    if valor in {"sim", "s", "confirmar", "confirmo"}:
        return "sim"
    if valor in {"nao", "não", "n", "cancelar"}:
        return "nao"

    return None


def validar_resposta_sim_nao(texto: str) -> str | None:
    return normalizar_resposta_sim_nao(texto)


def normalizar_telefone(texto: str) -> str:
    return re.sub(r"\D", "", texto)


def validar_telefone(texto: str) -> str | None:
    telefone = normalizar_telefone(texto)
    if len(telefone) < 8:
        return None
    return telefone


def horario_para_minutos(horario: str) -> int:
    hora, minuto = horario.split(":")
    return int(hora) * 60 + int(minuto)


def minutos_para_horario(total_minutos: int) -> str:
    hora = total_minutos // 60
    minuto = total_minutos % 60
    return f"{hora:02d}:{minuto:02d}"


def horario_esta_na_configuracao(horario: str, config: dict[str, Any] | None = None) -> bool:
    config = config or carregar_config()
    return any(horario in horarios for horarios in config.get("horarios", {}).values())
