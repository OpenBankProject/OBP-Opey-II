from typing import List, Dict, Optional

class OpeySession:
    def __init__(self, session_id: str, session_data: Dict):
        self.session_id = session_id
        self.session_data = session_data
        self.is_anonymous = session_data.get('is_anonymous', False)

    def update_session_data(self, new_data: Dict):
        self.session_data.update(new_data)

    def get_threads_for_user(self):
        raise NotImplementedError("This method is not implemented yet")

    @classmethod
    def from_session_data(cls, session_id: str, session_data: Dict):
        return cls(session_id=session_id, session_data=session_data)


class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, OpeySession] = {}

    def create_session(self, session_id: Optional[str] = None, session_data: Dict) -> OpeySession:
        if session_id in self.sessions:
            raise ValueError(f"Session with ID {session_id} already exists.")
        session = OpeySession.from_session_data(session_id, session_data)
        self.sessions[session_id] = session
        return session