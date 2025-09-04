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
        try:
            question_set_id = data.get("question_set_id")
            candidate_email = data.get("candidate_email")

            if not question_set_id or not candidate_email:
                print("⚠️ Missing question_set_id or candidate_email")
                return

            # Only counts sent by frontend
            increments = {col: data.get(col, 0) for col in VALID_COLUMNS}
            increments = {k: v for k, v in increments.items() if v > 0}
            if not increments:
                return

            # ❌ REMOVE this whole block (Supabase fetch + update/insert)
            # res = supabase.table("test_results")...

            # ✅ Instead, just broadcast to frontend
            socketio.emit("violation_update", {
                "candidate_email": candidate_email,
                "question_set_id": question_set_id,
                **increments
            })

            print(f"📡 Violation batch broadcast for {candidate_email} in set {question_set_id}: {increments}")

        except Exception as e:
            print(f"❌ Failed to handle violation event: {e}")
