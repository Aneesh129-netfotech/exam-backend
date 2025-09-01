# events.py
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


def normalize_violations(data: dict) -> dict:
    # Return only individual violation counts, ignore totals
    return {col: data.get(col, 0) for col in VALID_COLUMNS}


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
            candidate_name = data.get("candidate_name", "Unknown")

            if not question_set_id or not candidate_email:
                print("⚠️ Missing question_set_id or candidate_email")
                return

            # Only valid columns
            increments = {col: data.get(col, 0) for col in VALID_COLUMNS}
            increments = {k: v for k, v in increments.items() if v > 0}  # skip zeros
            if not increments:
                return  # nothing to update

            # Find existing row
            res = supabase.table("test_results") \
                .select("*") \
                .eq("question_set_id", question_set_id) \
                .eq("candidate_email", candidate_email) \
                .limit(1) \
                .execute()

            if res.data:
                row = res.data[0]

                # Overwrite instead of increment
                numeric_updates = {col: increments.get(col, row.get(col, 0)) for col in VALID_COLUMNS}

                # Feedback (optional: can still append to raw_feedback if you want history)
                violation_log = ", ".join([f"{k}: {v}" for k, v in increments.items()])
                new_feedback = f"[SNAPSHOT] {violation_log}"

                supabase.table("test_results").update({
                    **numeric_updates,
                    "raw_feedback": new_feedback,
                    "updated_at": datetime.utcnow().isoformat()
                }).eq("id", row["id"]).execute()

                payload = {**row, **numeric_updates, "raw_feedback": new_feedback}

            else:
                # Create new row
                violation_log = ", ".join([f"{k}: {v}" for k, v in increments.items()])
                payload = {
                    "id": str(uuid.uuid4()),
                    "question_set_id": question_set_id,
                    "candidate_name": candidate_name,
                    "candidate_email": candidate_email,
                    "status": "Pending",
                    "score": 0,
                    "max_score": 0,
                    "percentage": 0.0,
                    "total_questions": 0,
                    "raw_feedback": f"[VIOLATION] {violation_log}",
                    "created_at": datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat(),
                    "evaluated_at": datetime.utcnow().isoformat(),
                    **increments
                }
                supabase.table("test_results").upsert(payload, on_conflict=["candidate_email", "question_set_id"]).execute()

            # Always broadcast update
            socketio.emit("violation_update", {
                "candidate_email": candidate_email,
                "question_set_id": question_set_id,
                **{col: payload.get(col, 0) for col in VALID_COLUMNS},
            })

            print(f"✅ Violation batch saved for {candidate_email} in set {question_set_id}: {increments}")

        except Exception as e:
            print(f"❌ Failed to upsert violation batch: {e}")
