# events.py - Fixed version to ensure single row per candidate/question_set
from flask_socketio import SocketIO
from supabase import create_client
from dotenv import load_dotenv
import os
from datetime import datetime
import uuid

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase credentials not found! Make sure .env has SUPABASE_URL and SUPABASE_KEY.")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

VALID_COLUMNS = {
    "tab_switches",
    "inactivities",
    "text_selections",
    "copies",
    "pastes",
    "right_clicks",
    "face_not_visible",
}

LEGACY_MAP = {
    "tab_switch": "tab_switches",
    "inactivity": "inactivities",
    "text_selection": "text_selections",
    "copy": "copies",
    "paste": "pastes",
    "right_click": "right_clicks",
    "face_not_visible": "face_not_visible",
}


def find_or_create_test_result(question_set_id, candidate_id, candidate_email, candidate_name):
    """
    Always return a single row for (candidate_id + question_set_id).
    If exists, return it; otherwise, create a new row with zeroed violations.
    """
    res = supabase.table("test_results") \
        .select("*") \
        .eq("question_set_id", question_set_id) \
        .eq("candidate_id", candidate_id) \
        .limit(1) \
        .execute()
    
    if res.data:
        return res.data[0]

    # Insert new record if not found
    new_record = {
        "id": str(uuid.uuid4()),
        "question_set_id": question_set_id,
        "candidate_id": candidate_id,
        "candidate_email": candidate_email,
        "candidate_name": candidate_name or "Unknown",
        "score": 0,
        "max_score": 0,
        "percentage": 0.0,
        "status": "Pending",
        "total_questions": 0,
        "raw_feedback": "",
        "evaluated_at": datetime.utcnow().isoformat(),
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "duration_used_seconds": 0,
        "duration_used_minutes": 0,
        **{col: 0 for col in VALID_COLUMNS},  # all violations start at 0
    }

    insert_res = supabase.table("test_results").insert(new_record).execute()
    if insert_res.data:
        return insert_res.data[0]
    
    # Fallback: if insert fails, retry fetch
    res_retry = supabase.table("test_results") \
        .select("*") \
        .eq("question_set_id", question_set_id) \
        .eq("candidate_id", candidate_id) \
        .limit(1) \
        .execute()
    if res_retry.data:
        return res_retry.data[0]

    return new_record

def register_socket_events(socketio: SocketIO):
    @socketio.on("connect")
    def handle_connect():
        print("✅ Client connected")

    @socketio.on("disconnect")
    def handle_disconnect():
        print("❌ Client disconnected")

    @socketio.on("suspicious_event")
    def handle_suspicious_event(data):
        """
        Increment only specified violations; do NOT overwrite.
        Always merges with existing record.
        """
        try:
            question_set_id = data["question_set_id"]
            candidate_id = data["candidate_id"]
            candidate_email = data.get("candidate_email")
            candidate_name = data.get("candidate_name", "Unknown")

            existing_record = find_or_create_test_result(
                question_set_id, candidate_id, candidate_email, candidate_name
            )

            # Map legacy keys and increment properly
            increments = {}
            for key, value in data.items():
                if key in VALID_COLUMNS or key in LEGACY_MAP:
                    col = LEGACY_MAP.get(key, key)
                    if col in VALID_COLUMNS and value > 0:
                        increments[col] = value

            # Add to existing counts instead of overwriting
            merged = {col: existing_record.get(col, 0) + increments.get(col, 0) for col in VALID_COLUMNS}

            # Update record
            supabase.table("test_results").update({
                **merged,
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", existing_record["id"]).execute()

            # Broadcast for live monitoring
            socketio.emit("violation_update", {
                "candidate_id": candidate_id,
                "candidate_email": candidate_email,
                "question_set_id": question_set_id,
                **merged
            })

        except Exception as e:
            print(f"❌ Failed to process suspicious event: {e}")
