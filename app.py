# app.py - Fixed version to ensure single row per candidate/question_set
from flask import Flask, jsonify, request
from flask_socketio import SocketIO
from flask_cors import CORS
from dotenv import load_dotenv
import os
import logging
import asyncio
from supabase import create_client
from datetime import datetime
import uuid

from events import register_socket_events, VALID_COLUMNS, find_or_create_test_result
from test_generator import generate_questions, TestRequest

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

app = Flask(__name__)
CORS(app, supports_credentials=True)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "defaultsecret")

# Disable Flask logs
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

# Use eventlet for proper websocket support
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")
register_socket_events(socketio)


@app.route("/")
def index():
    return jsonify({"status": "Server is running."})


@app.route("/api/exam/<candidate_id>", methods=["GET"])
def get_exam_for_candidate(candidate_id):
    try:
        candidate_resp = supabase.table("candidates").select("*").eq("id", candidate_id).execute()
        if not candidate_resp.data:
            return jsonify({"error": "Candidate not found"}), 404
        candidate = candidate_resp.data[0]

        exam_id = candidate.get("exam_id")
        test_resp = supabase.table("exams").select("*").eq("id", exam_id).execute()
        questions = test_resp.data if test_resp.data else []

        return jsonify({
            "candidate": {
                "id": candidate["id"],
                "name": candidate["name"],
                "email": candidate["email"],
                "exam_id": exam_id,
            },
            "questions": questions,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/test/<test_id>", methods=["GET"])
def get_test(test_id):
    try:
        test_request = TestRequest(
            topic=f"Demo topic for test {test_id}",
            difficulty="easy",
            num_questions=5,
            question_type="mcq",
            jd_id=test_id,
        )
        loop = asyncio.get_event_loop()
        questions = loop.run_until_complete(generate_questions(test_request))
        return jsonify({"test_id": test_id, "questions": questions})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/test/generate", methods=["POST"])
def generate_test_route():
    try:
        data = request.get_json()
        test_request = TestRequest(
            topic=data.get("topic"),
            difficulty=data.get("difficulty", "easy"),
            num_questions=data.get("num_questions", 5),
            question_type=data.get("question_type", "mcq"),
            jd_id=data.get("jd_id"),
            mcq_count=data.get("mcq_count"),
            coding_count=data.get("coding_count"),
        )
        loop = asyncio.get_event_loop()
        questions = loop.run_until_complete(generate_questions(test_request))
        return jsonify({"questions": questions})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/test/submit", methods=["POST"])
def submit_test():
    """
    Dump frontend console data directly into Supabase.
    DB = exactly what frontend sends (no merging or backend increments).
    """
    try:
        data = request.get_json()

        question_set_id = data.get("question_set_id")
        candidate_id = data.get("candidate_id")
        candidate_email = data.get("candidate_email")
        candidate_name = data.get("candidate_name")

        if not question_set_id or not candidate_id:
            return jsonify({"error": "Missing question_set_id or candidate_id"}), 400# Always ensure a row exists        
        existing_record = find_or_create_test_result(
            question_set_id, candidate_id, candidate_email, candidate_name
        )

        # ✅ Dump everything exactly from frontend        
        update_data = {
            "score": data.get("score", 0),
            "max_score": data.get("max_score", 0),
            "percentage": data.get("percentage", 0.0),
            "total_questions": data.get("total_questions", 0),
            "status": data.get("status", "Pending"),
            "raw_feedback": data.get("raw_feedback", ""),
            "updated_at": datetime.utcnow().isoformat(),
            "duration_used_seconds": data.get("duration_used", 0),
            "duration_used_minutes": round(data.get("duration_used", 0) / 60, 2),
            **{col: data.get(col, 0) for col in VALID_COLUMNS}  # 👈 exact violations        
        }

        # Overwrite the row in Supabase        
        supabase.table("test_results").update(update_data).eq("id", existing_record["id"]).execute()

        return jsonify({
            "status": "success",
            "saved": update_data
        })

    except Exception as e:
        print(f"❌ Error in submit_test: {str(e)}")
        return jsonify({"error": str(e)}), 500 

@app.route("/api/violations/manual", methods=["POST"])
def insert_manual_violations():
    """
    Endpoint to manually insert violation data from F12 console
    """
    try:
        data = request.get_json()
        print(f"📥 Manual violation insert request: {data}")
        
        question_set_id = data.get("question_set_id", f"manual-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}")
        candidate_id = data.get("candidate_id", f"manual-{str(uuid.uuid4())[:8]}")
        candidate_email = data.get("candidate_email", "manual@example.com")
        candidate_name = data.get("candidate_name", "Manual Entry")
        
        # Find or create the test result record
        existing_record = find_or_create_test_result(
            question_set_id, candidate_id, candidate_email, candidate_name
        )
        
        # Extract individual violation counts
        violations = {col: data.get(col, 0) for col in VALID_COLUMNS}
        
        # Merge with existing violations
        merged_violations = {
            col: existing_record.get(col, 0) + violations.get(col, 0) 
            for col in VALID_COLUMNS
        }
        
        # Prepare update data
        violation_summary = ', '.join([f'{k}={v}' for k, v in violations.items() if v > 0])
        new_feedback = (existing_record.get("raw_feedback") or "") + (
            f"\nManual violation entry: {violation_summary}" if violation_summary else ""
        )
        
        update_data = {
            "score": data.get("score", existing_record.get("score", 0)),
            "max_score": data.get("max_score", existing_record.get("max_score", 0)),
            "percentage": data.get("percentage", existing_record.get("percentage", 0.0)),
            "status": data.get("status", existing_record.get("status", "Manual Entry")),
            "total_questions": data.get("total_questions", existing_record.get("total_questions", 0)),
            "raw_feedback": new_feedback,
            "updated_at": datetime.utcnow().isoformat(),
            "duration_used_seconds": data.get("duration_used_seconds", existing_record.get("duration_used_seconds", 0)),
            "duration_used_minutes": data.get("duration_used_minutes", existing_record.get("duration_used_minutes", 0)),
            **merged_violations
        }
        
        # Update the record
        response = supabase.table("test_results").update(update_data).eq("id", existing_record["id"]).execute()

        if response.data:
            print(f"✅ Manual violation record updated successfully: {existing_record['id']}")
            return jsonify({
                "status": "success",
                "message": "Manual violation record updated successfully",
                "data": {**existing_record, **update_data},
                "violations_summary": violations
            })
        else:
            return jsonify({"error": "Failed to update record"}), 500
            
    except Exception as e:
        print(f"❌ Manual violation insert failed: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/violations/test", methods=["GET"])
def test_violations_endpoint():
    """
    Test endpoint to verify the violations API is working
    """
    return jsonify({
        "status": "success",
        "message": "Violations API is working",
        "timestamp": datetime.utcnow().isoformat(),
        "valid_columns": list(VALID_COLUMNS)
    })


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5001, debug=False)
