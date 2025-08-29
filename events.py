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


def normalize_violations(data: dict) -> dict:
    # Return only individual violation counts, ignore totals
    return {col: data.get(col, 0) for col in VALID_COLUMNS}


def find_or_create_test_result(question_set_id, candidate_id, candidate_email, candidate_name):
    """
    Helper function to find existing test result or create a new one.
    Ensures only one row exists per candidate/question_set combination.
    """
    # First, try to find existing record with both candidate_id AND candidate_email for safety
    res = supabase.table("test_results") \
        .select("*") \
        .eq("question_set_id", question_set_id) \
        .eq("candidate_id", candidate_id) \
        .limit(1) \
        .execute()
    
    if res.data:
        return res.data[0]
    
    # Also check by email if candidate_id lookup failed
    if candidate_email:
        res_email = supabase.table("test_results") \
            .select("*") \
            .eq("question_set_id", question_set_id) \
            .eq("candidate_email", candidate_email) \
            .limit(1) \
            .execute()
        
        if res_email.data:
            # Update the candidate_id if it was missing
            existing_record = res_email.data[0]
            if not existing_record.get("candidate_id") and candidate_id:
                supabase.table("test_results").update({
                    "candidate_id": candidate_id,
                    "updated_at": datetime.utcnow().isoformat()
                }).eq("id", existing_record["id"]).execute()
                existing_record["candidate_id"] = candidate_id
            return existing_record
    
    # If no record found, create a new one
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
        # Initialize all violation columns to 0
        "tab_switches": 0,
        "inactivities": 0,
        "text_selections": 0,
        "copies": 0,
        "pastes": 0,
        "right_clicks": 0,
        "face_not_visible": 0,
    }
    
    try:
        # Insert the new record
        insert_res = supabase.table("test_results").insert(new_record).execute()
        return insert_res.data[0] if insert_res.data else new_record
    except Exception as e:
        print(f"⚠️ Error creating new record, attempting to find existing: {e}")
        # If insert fails due to conflict, try to find the record again
        res_retry = supabase.table("test_results") \
            .select("*") \
            .eq("question_set_id", question_set_id) \
            .eq("candidate_id", candidate_id) \
            .limit(1) \
            .execute()
        
        if res_retry.data:
            return res_retry.data[0]
        raise e


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

            if not question_set_id:
                print("⚠️ Missing question_set_id")
                return
            
            if not candidate_email and not candidate_id:
                print("⚠️ Missing both candidate_email and candidate_id")
                return

            # Only valid columns
            increments = {col: data.get(col, 0) for col in VALID_COLUMNS}
            increments = {k: v for k, v in increments.items() if v > 0}  # skip zeros
            if not increments:
                print("⚠️ No valid violations to process")
                return  # nothing to update

            # Find or create the test result record
            existing_record = find_or_create_test_result(
                question_set_id, candidate_id, candidate_email, candidate_name
            )

            # Merge violations (add to existing counts)
            merged_violations = {
                col: existing_record.get(col, 0) + increments.get(col, 0) 
                for col in VALID_COLUMNS
            }

            # Append feedback
            violation_log = ", ".join([f"{k}: +{v}" for k, v in increments.items()])
            new_feedback = (existing_record.get("raw_feedback") or "") + f"\n[VIOLATION] {violation_log}"

            # Update the existing record
            update_data = {
                **merged_violations,
                # "raw_feedback": new_feedback,
                "updated_at": datetime.utcnow().isoformat()
            }

            supabase.table("test_results").update(update_data).eq("id", existing_record["id"]).execute()

            # Prepare payload for broadcast
            payload = {**existing_record, **update_data}

            # Always broadcast update
            socketio.emit("violation_update", {
                "candidate_email": candidate_email,
                "candidate_id": candidate_id,
                "question_set_id": question_set_id,
                **{col: payload.get(col, 0) for col in VALID_COLUMNS},
            })

            print(f"✅ Violation batch saved for {candidate_email or candidate_id} in set {question_set_id}: {increments}")
            
            # Instead of saving, just broadcast for live monitoring
            socketio.emit("violation_update", {
                    "candidate_email": candidate_email,
                    "candidate_id": candidate_id,
                    "question_set_id": question_set_id,
                    **{col: data.get(col, 0) for col in VALID_COLUMNS},
            })
            print(f"🔔 Live violation event (not saved): {data}")
        except Exception as e:
            print(f"❌ Failed to process suspicious event: {e}")
            import traceback
            traceback.print_exc()
