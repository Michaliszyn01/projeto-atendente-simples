from core.scheduling.availability import calcular_horarios_disponiveis, tem_conflito


def test_disponibilidade_sem_agenda_mostra_profissionais_para_sem_preferencia():
    opcoes = calcular_horarios_disponiveis(
        data="2026-06-16",
        servico="corte",
        profissional_preferido=None,
        periodo="manhã",
        agenda=[],
    )

    assert {"horario": "09:00", "profissional": "Marcos"} in opcoes
    assert {"horario": "09:00", "profissional": "Julio"} in opcoes
    assert {"horario": "11:30", "profissional": "Marcos"} in opcoes


def test_servico_de_60_minutos_nao_passa_do_fim_do_periodo():
    opcoes = calcular_horarios_disponiveis(
        data="2026-06-16",
        servico="corte + barba",
        profissional_preferido="Marcos",
        periodo="manhã",
        agenda=[],
    )

    horarios = [opcao["horario"] for opcao in opcoes]
    assert "11:00" in horarios
    assert "11:30" not in horarios


def test_conflito_bloqueia_mesmo_profissional_no_intervalo():
    agenda = [
        {
            "id": "1",
            "nome": "Cliente",
            "servico": "corte + barba",
            "data": "2026-06-16",
            "horario": "10:00",
            "profissional": "Marcos",
            "duracao_minutos": 60,
            "status": "agendado",
        }
    ]

    assert tem_conflito("2026-06-16", "10:30", "Marcos", 30, agenda) is True
    assert tem_conflito("2026-06-16", "10:30", "Julio", 30, agenda) is False


def test_horario_ocupado_some_somente_para_profissional_ocupado():
    agenda = [
        {
            "id": "1",
            "nome": "Cliente",
            "servico": "corte",
            "data": "2026-06-16",
            "horario": "15:00",
            "profissional": "Marcos",
            "duracao_minutos": 30,
            "status": "agendado",
        }
    ]

    opcoes = calcular_horarios_disponiveis(
        data="2026-06-16",
        servico="corte",
        profissional_preferido=None,
        periodo="tarde",
        agenda=agenda,
    )

    assert {"horario": "15:00", "profissional": "Marcos"} not in opcoes
    assert {"horario": "15:00", "profissional": "Julio"} in opcoes


def test_horario_cancelado_volta_a_ficar_disponivel():
    agenda = [
        {
            "id": "1",
            "nome": "Cliente",
            "servico": "corte",
            "data": "2026-06-16",
            "horario": "15:00",
            "profissional": "Marcos",
            "duracao_minutos": 30,
            "status": "cancelado",
        }
    ]

    opcoes = calcular_horarios_disponiveis(
        data="2026-06-16",
        servico="corte",
        profissional_preferido="Marcos",
        periodo="tarde",
        agenda=agenda,
    )

    assert {"horario": "15:00", "profissional": "Marcos"} in opcoes


def test_disponibilidade_ignora_o_proprio_agendamento_quando_informado():
    agenda = [
        {
            "id": "1",
            "nome": "Cliente",
            "servico": "corte",
            "data": "2026-06-16",
            "horario": "15:00",
            "profissional": "Marcos",
            "duracao_minutos": 30,
            "status": "agendado",
        }
    ]

    opcoes = calcular_horarios_disponiveis(
        data="2026-06-16",
        servico="corte",
        profissional_preferido="Marcos",
        periodo="tarde",
        agenda=agenda,
        ignorar_agendamento_id="1",
    )

    assert {"horario": "15:00", "profissional": "Marcos"} in opcoes


def test_disponibilidade_nao_ignora_outros_agendamentos():
    agenda = [
        {
            "id": "1",
            "nome": "Cliente",
            "servico": "corte",
            "data": "2026-06-16",
            "horario": "15:00",
            "profissional": "Marcos",
            "duracao_minutos": 30,
            "status": "agendado",
        },
        {
            "id": "2",
            "nome": "Outro Cliente",
            "servico": "corte",
            "data": "2026-06-16",
            "horario": "15:30",
            "profissional": "Marcos",
            "duracao_minutos": 30,
            "status": "agendado",
        },
    ]

    opcoes = calcular_horarios_disponiveis(
        data="2026-06-16",
        servico="corte",
        profissional_preferido="Marcos",
        periodo="tarde",
        agenda=agenda,
        ignorar_agendamento_id="1",
    )

    assert {"horario": "15:00", "profissional": "Marcos"} in opcoes
    assert {"horario": "15:30", "profissional": "Marcos"} not in opcoes
