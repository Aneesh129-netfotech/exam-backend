# events.py
from flask_socketio import SocketIO
from supabase import create_client
from dotenv import load_dotenv
import os
import datetime
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

            # Normalize counts
            counts = data.get("counts")
            if not counts:
                vt = data.get("violation_type")
                if not vt:
                    print("⚠️ Ignoring event: missing counts/violation_type")
                    return
                col = LEGACY_MAP.get(vt)
                if not col:
                    print(f"⚠️ Unknown violation type: {vt}")
                    return
                counts = {col: 1}

            # Only keep valid + positive
            increments = {k: int(v) for k, v in counts.items() if k in VALID_COLUMNS and int(v) > 0}
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

                # Increment per-column
                numeric_updates = {col: row.get(col, 0) + increments.get(col, 0) for col in increments.keys()}

                # ✅ Also update total violations
                new_total_violations = row.get("violations", 0) + sum(increments.values())

                supabase.table("test_results").update({
                    "raw_feedback": new_feedback,
                    **numeric_updates,
                    "violations": new_total_violations,
                    "updated_at": datetime.utcnow().isoformat()
                }).eq("id", row["id"]).execute()

                payload = {**row, "raw_feedback": new_feedback, **numeric_updates, "violations": new_total_violations}

            else:
                # 🆕 Insert fresh row (ensure required columns exist!)
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

            # Broadcast
            socketio.emit("violation_update", {
                "candidate_email": candidate_email,
                "question_set_id": question_set_id,
                **{col: payload.get(col, 0) for col in VALID_COLUMNS},
                "violations": payload.get("violations", 0)
            })

            print(f"✅ Violation batch saved for {candidate_email} in set {question_set_id}: {increments}")

        except Exception as e:
            print(f"❌ Failed to upsert violation batch: {e}")
