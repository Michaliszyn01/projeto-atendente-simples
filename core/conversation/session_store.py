from core.conversation.state import ConversationState
from core.storage.sqlite_repository import SQLiteSessionStore


class InMemorySessionStore:
    def __init__(self) -> None:
        self._states: dict[str, ConversationState] = {}
        self._finished: dict[str, bool] = {}

    def exists(self, session_id: str) -> bool:
        return session_id in self._states

    def get_or_create(self, session_id: str) -> ConversationState:
        if session_id not in self._states:
            self._states[session_id] = ConversationState()
            self._finished[session_id] = False
        return self._states[session_id]

    def save(self, session_id: str, state: ConversationState, finished: bool = False) -> None:
        self._states[session_id] = state
        self._finished[session_id] = finished

    def reset(self, session_id: str) -> ConversationState:
        state = ConversationState()
        self.save(session_id, state, finished=False)
        return state

    def delete(self, session_id: str) -> None:
        self._states.pop(session_id, None)
        self._finished.pop(session_id, None)

    def is_finished(self, session_id: str) -> bool:
        return self._finished.get(session_id, False)
