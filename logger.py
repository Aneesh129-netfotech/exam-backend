from flask_socketio import emit

def log_event(session_id, event_type, timestamp):
    emit("warning", {
        "session_id": session_id,
        "type": event_type,
        "timestamp": timestamp
    }, broadcast=True)
