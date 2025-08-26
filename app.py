# app.py
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

from events import register_socket_events, VALID_COLUMNS
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
    try:
        data = request.get_json()

        # Insert individual violation fields only
        params = {
            "id": str(uuid.uuid4()),
            "question_set_id": data.get("question_set_id"),
            "score": data.get("score", 0),
            "max_score": data.get("max_score", len(data.get("questions", [])) * 10),
            "percentage": data.get("percentage", 0.0),
            "status": data.get("status", "Pending"),
            "total_questions": data.get("total_questions", len(data.get("questions", []))),
            "raw_feedback": data.get("raw_feedback", ""),
            "evaluated_at": datetime.utcnow().isoformat(),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "duration_used_seconds": data.get("duration_used", 0),
            "duration_used_minutes": round((data.get("duration_used", 0)) / 60, 2),
            "candidate_id": data.get("candidate_id"),
            "candidate_email": data.get("candidate_email"),
            "candidate_name": data.get("candidate_name"),
            **{col: data.get(col, 0) for col in VALID_COLUMNS},
        }

        response = supabase.table("test_results").insert(params).execute()

        return jsonify({
            "status": "success",
            "saved": response.data[0] if response.data else None
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/violations/manual", methods=["POST"])
def insert_manual_violations():
    """
    Endpoint to manually insert violation data from F12 console
    """
    try:
        data = request.get_json()
        print(f"📥 Manual violation insert request: {data}")
        
        # Extract individual violation counts
        violations = {col: data.get(col, 0) for col in VALID_COLUMNS}
        
        # Prepare the record
        params = {
            "id": str(uuid.uuid4()),
            "question_set_id": data.get("question_set_id", f"manual-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"),
            "candidate_email": data.get("candidate_email", "manual@example.com"),
            "candidate_name": data.get("candidate_name", "Manual Entry"),
            "score": data.get("score", 0),
            "max_score": data.get("max_score", 0),
            "percentage": data.get("percentage", 0.0),
            "status": data.get("status", "Manual Entry"),
            "total_questions": data.get("total_questions", 0),
            "raw_feedback": data.get("raw_feedback", f"Manual violation entry: {', '.join([f'{k}={v}' for k,v in violations.items() if v > 0])}"),
            "evaluated_at": datetime.utcnow().isoformat(),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "duration_used_seconds": data.get("duration_used_seconds", 0),
            "duration_used_minutes": data.get("duration_used_minutes", 0),
            "candidate_id": data.get("candidate_id"),
            **violations,  # individual columns only
        }
        
        print(f"📝 Inserting manual violation record: {params}")
        
        # Insert into Supabase
        response = supabase.table("test_results").insert(params).execute()
        
        if response.data:
            print(f"✅ Manual violation record created successfully: {response.data[0]['id']}")
            return jsonify({
                "status": "success",
                "message": "Manual violation record created successfully",
                "data": response.data[0],
                "violations_summary": violations
            })
        else:
            return jsonify({"error": "Failed to create record"}), 500
            
    except Exception as e:
        print(f"❌ Manual violation insert failed: {str(e)}")
        return jsonify({"error": str(e)}), 500


# Add this endpoint for testing the connection
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
