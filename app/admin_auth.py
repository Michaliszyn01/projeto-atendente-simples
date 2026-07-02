import hmac
import os
from dataclasses import dataclass
from typing import Mapping


SESSION_AUTH_KEY = "admin_authenticated"
SESSION_USER_KEY = "admin_username"


@dataclass(frozen=True)
class AdminCredentials:
    username: str | None
    password: str | None
    configured: bool = False


def get_admin_credentials(env: Mapping[str, str] | None = None) -> AdminCredentials:
    env = env or os.environ
    username = _clean(env.get("ADMIN_USERNAME"))
    password = _clean(env.get("ADMIN_PASSWORD"))

    if username and password:
        return AdminCredentials(username=username, password=password, configured=True)

    return AdminCredentials(username=username, password=password, configured=False)


def check_login(username: str, password: str, credentials: AdminCredentials | None = None) -> bool:
    credentials = credentials or get_admin_credentials()
    if not credentials.configured or credentials.username is None or credentials.password is None:
        return False
    return hmac.compare_digest(str(username or ""), credentials.username) and hmac.compare_digest(
        str(password or ""),
        credentials.password,
    )


def require_login(st) -> bool:
    credentials = get_admin_credentials()
    session_state = st.session_state

    if session_state.get(SESSION_AUTH_KEY):
        if not credentials.configured:
            session_state.pop(SESSION_AUTH_KEY, None)
            session_state.pop(SESSION_USER_KEY, None)
            _show_missing_credentials(st)
            return False
        return True

    st.title("Login do painel")
    st.caption("Acesse para visualizar agenda, telefones e solicitações.")
    if not credentials.configured:
        _show_missing_credentials(st)
        return False

    username = st.text_input("Usuário")
    password = st.text_input("Senha", type="password")

    if st.button("Entrar"):
        if check_login(username, password, credentials):
            session_state[SESSION_AUTH_KEY] = True
            session_state[SESSION_USER_KEY] = credentials.username
            _rerun(st)
            return True
        st.error("Usuário ou senha inválidos.")

    return False


def logout_button(st) -> None:
    if st.sidebar.button("Sair"):
        st.session_state.pop(SESSION_AUTH_KEY, None)
        st.session_state.pop(SESSION_USER_KEY, None)
        _rerun(st)


def _show_missing_credentials(st) -> None:
    st.error("Credenciais administrativas não configuradas.")


def _rerun(st) -> None:
    rerun = getattr(st, "rerun", None)
    if callable(rerun):
        rerun()


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None
