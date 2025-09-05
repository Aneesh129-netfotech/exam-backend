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
# Violation fields only
VALID_COLUMNS = {
    "tab_switches",
    "inactivities",
    "face_not_visible",
    "screenshot"
}

LEGACY_MAP = {
    "tab_switch": "tab_switches",
    "inactivity": "inactivities",
    "face_not_visible": "face_not_visible",
    "screenshot": "screenshot",
}

def normalize_violations(data: dict) -> dict:
    # Return only violation counts
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
        print("📥 suspicious_event received:", data)
        try:
            question_set_id = data.get("question_set_id")
            candidate_email = data.get("candidate_email")
            candidate_name = data.get("candidate_name", "Unknown")

            if not question_set_id or not candidate_email:
                print("⚠️ Missing question_set_id or candidate_email")
                return# Only counts sent by frontend            
            increments = {col: data.get(col, 0) for col in VALID_COLUMNS}
            increments = {k: v for k, v in increments.items() if v > 0}
            if not increments:
                return# Find existing row            
            res = supabase.table("test_results") \
                .select("*") \
                .eq("question_set_id", question_set_id) \
                .eq("candidate_email", candidate_email) \
                .limit(1) \
                .execute()

            if res.data:
                row = res.data[0]

                # Overwrite with latest totals from frontend                
                numeric_updates = {col: int(increments.get(col, row.get(col, 0))) for col in VALID_COLUMNS}

                # Update feedback summary (violations only)                
                new_feedback = "Total Violations: " + ", ".join([f"{col}={val}" for col, val in numeric_updates.items()])
                print(f"[VIOLATIONS] {new_feedback}")

                supabase.table("test_results").update({
                    **numeric_updates,
                    "raw_feedback": new_feedback,
                    "updated_at": datetime.utcnow().isoformat(),
                    "score": row.get("score", 0),
                    "max_score": row.get("max_score", 0),
                    "percentage": row.get("percentage", 0.0),
                    "total_questions": row.get("total_questions", 0),
                }).eq("id", row["id"]).execute()

                payload = {**row, **numeric_updates, "raw_feedback": new_feedback}

            else:
                # 🚀 Create a row only with violations, no score fields                
                new_feedback = "Total Violations: " + ", ".join([f"{col}={val}" for col, val in increments.items()])
                payload = {
                    "id": str(uuid.uuid4()),
                    "exam_id": data.get("exam_id"),
                    "question_set_id": question_set_id,
                    "candidate_name": candidate_name,
                    "candidate_email": candidate_email,
                    "status": "Pending",
                    "raw_feedback": new_feedback,
                    "created_at": datetime.utcnow().isoformat(),
                    "updated_at": datetime.utcnow().isoformat(),
                    "evaluated_at": None,                   
                    **increments
                }
                supabase.table("test_results").insert(payload).execute()

            # Broadcast update            
            socketio.emit("violation_update", {
                "candidate_email": candidate_email,
                "question_set_id": question_set_id,
                **{col: payload.get(col, 0) for col in VALID_COLUMNS},
            })

            print(f"✅ Violation batch saved for {candidate_email} in set {question_set_id}: {increments}")

        except Exception as e:
            print(f"❌ Failed to upsert violation batch: {e}")
