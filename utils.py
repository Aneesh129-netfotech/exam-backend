import uuid

class StrikeTracker:
    def __init__(self):
        self.sessions = {}

    def add_strike(self, sid):
        if sid not in self.sessions:
            self.sessions[sid] = 0
        self.sessions[sid] += 1

    def get_strikes(self, sid):
        return self.sessions.get(sid, 0)

strike_tracker = StrikeTracker()
