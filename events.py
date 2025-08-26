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
    counts = data.get("violations") or data.get("counts")

    # If violations is just an int (total), ignore it
    if isinstance(counts, int):
        counts = None

    if not counts:
        # Try flat keys
        counts = {col: data.get(col, 0) for col in VALID_COLUMNS}

    # Legacy single-event format
    if not any(counts.values()):
        vt = data.get("violation_type")
        if vt:
            col = LEGACY_MAP.get(vt)
            if col:
                counts = {col: 1}

    # ✅ Ensure all keys in VALID_COLUMNS are present
    normalized = {}
    for col in VALID_COLUMNS:
        try:
            normalized[col] = int(counts.get(col, 0)) if counts.get(col) is not None else 0
        except Exception:
            normalized[col] = 0
        return normalized

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
            candidate_name = data.get("candidate_name")
            candidate_email = data.get("candidate_email")

            if not question_set_id or not candidate_email:
                print("⚠️ missing question_set_id or candidate_email")
                return

            increments = normalize_violations(data)
            if not increments:
                return

            res = (
                supabase.table("test_results")
                .select("*")
                .eq("question_set_id", question_set_id)
                .eq("candidate_email", candidate_email)
                .limit(1)
                .execute()
            )

            if res.data:
                # 🔄 Update existing row
                row = res.data[0]

                prev_feedback = row.get("raw_feedback", "") or ""
                violation_log = "\n".join([f"{col}: +{inc}" for col, inc in increments.items()])
                new_feedback = prev_feedback + f"\n[VIOLATION] {violation_log}"

                numeric_updates = {
                    col: row.get(col, 0) + increments.get(col, 0)
                    for col in increments.keys()
                }

                new_total_violations = row.get("violations", 0) + sum(increments.values())

                supabase.table("test_results").update({
                    "raw_feedback": new_feedback,
                    **numeric_updates,
                    "violations": new_total_violations,
                    "updated_at": datetime.utcnow().isoformat()
                }).eq("id", row["id"]).execute()

                payload = {**row, "raw_feedback": new_feedback, **numeric_updates, "violations": new_total_violations}

            else:
                # 🆕 Fresh row
                violation_log = "\n".join([f"{col}: {inc}" for col, inc in increments.items()])
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
                    **{col: increments.get(col, 0) for col in VALID_COLUMNS},
                    "violations": sum(increments.values())
                }
                supabase.table("test_results").insert(payload).execute()

            # Broadcast update
            socketio.emit("violation_update", {
                "candidate_email": candidate_email,
                "question_set_id": question_set_id,
                **{col: payload.get(col, 0) for col in VALID_COLUMNS},
                "violations": payload.get("violations", 0)
            })

            print(f"✅ Violation batch saved for {candidate_email} in set {question_set_id}: {increments}")

        except Exception as e:
            print(f"❌ Failed to upsert violation batch: {e}")
