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
            totals = {col: int(data.get(col, 0)) for col in VALID_COLUMNS}

            # Find existing row
            res = supabase.table("test_results") \
                .select("*") \
                .eq("question_set_id", question_set_id) \
                .eq("candidate_email", candidate_email) \
                .limit(1) \
                .execute()

            if res.data:
                row = res.data[0]

                # Compute increments = new_total - old_total
                increments = {}
                numeric_updates = {}
                for col in VALID_COLUMNS:
                    old_val = row.get(col, 0)
                    new_val = totals.get(col, 0)
                    delta = max(0, new_val - old_val)  # prevent negatives
                    if delta > 0:
                        increments[col] = delta
                    numeric_updates[col] = new_val  # always store latest total

                # Skip if no actual increments
                if not increments:
                    return

                # Append feedback
                violation_log = ", ".join([f"{k}: +{v}" for k, v in increments.items()])
                new_feedback = (row.get("raw_feedback") or "") + f"\n[VIOLATION] {violation_log}"

                supabase.table("test_results").update({
                    **numeric_updates,
                    "raw_feedback": new_feedback,
                    "updated_at": datetime.utcnow().isoformat()
                }).eq("id", row["id"]).execute()

                payload = {**row, **numeric_updates, "raw_feedback": new_feedback}

            else:
                # New row on first violation event
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
                    "raw_feedback": "[VIOLATION] " + ", ".join([f"{k}: {v}" for k, v in totals.items() if v > 0]),
                    "created_at": datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat(),
                    "evaluated_at": datetime.utcnow().isoformat(),
                    **totals
                }
                supabase.table("test_results").upsert(payload, on_conflict=["candidate_email", "question_set_id"]).execute()

            # Always broadcast update
            socketio.emit("violation_update", {
                "candidate_email": candidate_email,
                "question_set_id": question_set_id,
                **{col: payload.get(col, 0) for col in VALID_COLUMNS},
            })

            print(f"✅ Violation totals saved for {candidate_email} in set {question_set_id}: {totals}")

        except Exception as e:
            print(f"❌ Failed to upsert violation batch: {e}")
