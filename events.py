# events.py
from flask_socketio import SocketIO
from supabase import create_client
from dotenv import load_dotenv
import os

# Load .env variables
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
    "tab_switches": "tab_switches",
    "inactivity": "inactivities",
    "inactivities": "inactivities",
    "text_selection": "text_selections",
    "text_selections": "text_selections",
    "copy": "copies",
    "copies": "copies",
    "paste": "pastes",
    "pastes": "pastes",
    "right_click": "right_clicks",
    "right_clicks": "right_clicks",
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

            # normalize counts
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

            increments = {k: int(v) for k, v in counts.items() if k in VALID_COLUMNS and int(v) > 0}
            if not increments:
                return

            # Fetch result row for candidate
            res = (
                supabase.table("results")
                .select("*")
                .eq("question_set_id", question_set_id)
                .eq("candidate_email", candidate_email)
                .limit(1)
                .execute()
            )

            if res.data:
                row = res.data[0]
                # accumulate into existing row
                update_payload = {}
                for col, inc in increments.items():
                    update_payload[col] = int(row.get(col, 0)) + inc

                supabase.table("results").update(update_payload).eq("id", row["id"]).execute()
                payload = {**row, **update_payload}
            else:
                # create fresh row (in case results not created yet)
                payload = {
                    "question_set_id": question_set_id,
                    "candidate_name": candidate_name,
                    "candidate_email": candidate_email,
                    **{col: increments.get(col, 0) for col in VALID_COLUMNS},
                }
                supabase.table("test_results").insert(payload).execute()

            # broadcast update
            socketio.emit("violation_update", {
                "candidate_email": candidate_email,
                "question_set_id": question_set_id,
                **{col: payload.get(col, 0) for col in VALID_COLUMNS},
            })

            print(f"✅ violation batch saved for {candidate_email} in set {question_set_id}: {increments}")

        except Exception as e:
            print(f"❌ Failed to upsert violation batch: {e}")