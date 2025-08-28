# events.py - Unified version with atomic violation handling
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
    raise ValueError("Supabase credentials not found!")

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

def merge_violations(existing_record: dict, new_violations: dict) -> dict:
    merged = {}
    for col in VALID_COLUMNS:
        merged[col] = int(existing_record.get(col, 0)) + int(new_violations.get(col, 0))
    return merged

def find_or_create_test_result(question_set_id, candidate_id, candidate_email, candidate_name):
    res = supabase.table("test_results") \
        .select("*") \
        .eq("question_set_id", question_set_id) \
        .eq("candidate_id", candidate_id) \
        .limit(1).execute()

    if res.data:
        return res.data[0]

    # Upsert to avoid race conditions
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
        **{col: 0 for col in VALID_COLUMNS}
    }

    insert_res = supabase.table("test_results") \
        .upsert(new_record, on_conflict=["question_set_id", "candidate_id"]).execute()
    return insert_res.data[0] if insert_res.data else new_record

def register_socket_events(socketio: SocketIO):
    @socketio.on("connect")
    def handle_connect():
        print("✅ Client connected")

    @socketio.on("disconnect")
    def handle_disconnect():
        print("❌ Client disconnected")

    @socketio.on("suspicious_event")
    def handle_suspicious_event(data):
        try:
            question_set_id = data.get("question_set_id")
            candidate_email = data.get("candidate_email")
            candidate_id = data.get("candidate_id")
            candidate_name = data.get("candidate_name", "Unknown")

            if not question_set_id or (not candidate_email and not candidate_id):
                print("⚠️ Missing identifiers")
                return

            violations = {col: int(data.get(col, 0)) for col in VALID_COLUMNS}
            increments = {k: v for k, v in violations.items() if v > 0}
            if not increments:
                return

            existing_record = find_or_create_test_result(
                question_set_id, candidate_id, candidate_email, candidate_name
            )

            merged_violations = merge_violations(existing_record, violations)
            increment_summary = ", ".join([f"{k}:+{v}" for k, v in increments.items()])
            feedback = (existing_record.get("raw_feedback") or "") + f"\n[VIOLATION] {increment_summary}"

            update_data = {
                **merged_violations,
                "raw_feedback": feedback,
                "updated_at": datetime.utcnow().isoformat()
            }
            supabase.table("test_results").update(update_data).eq("id", existing_record["id"]).execute()

            payload = {**existing_record, **update_data}
            socketio.emit("violation_update", {
                "candidate_email": candidate_email,
                "candidate_id": candidate_id,
                "question_set_id": question_set_id,
                **{col: payload.get(col, 0) for col in VALID_COLUMNS},
            })

            print(f"✅ Violation batch saved for {candidate_email or candidate_id}: {increments}")

        except Exception as e:
            print(f"❌ Failed to process suspicious event: {e}")
            import traceback
            traceback.print_exc()
