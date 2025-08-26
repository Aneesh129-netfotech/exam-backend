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

from events import register_socket_events
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

# ✅ Use eventlet for proper websocket support
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
        
        print("\n" + "="*60)
        print("FLASK: DETAILED SUBMISSION DEBUG")
        print("="*60)
        print(f"Raw data received: {data}")
        
        # Validate we have data
        if not data:
            print("ERROR: No data received")
            return jsonify({"error": "No data received"}), 400
        
        # Check for violations specifically
        violations_received = {}
        violation_fields = ["tab_switches", "inactivities", "text_selections", 
                          "copies", "pastes", "right_clicks", "face_not_visible"]
        
        print("\nVIOLATIONS CHECK:")
        for field in violation_fields:
            value = data.get(field, 0)
            violations_received[field] = int(value) if value is not None else 0
            print(f"  {field}: {value} -> {violations_received[field]} (type: {type(violations_received[field])})")
        
        # Calculate totals for verification
        total_violations = sum(violations_received.values())
        print(f"\nTotal violations: {total_violations}")
        
        now = datetime.utcnow().isoformat()
        
        # Build payload
        payload = {
            "id": str(uuid.uuid4()),
            "question_set_id": data.get("question_set_id"),
            "max_score": data.get("max_score", 0),
            "percentage": data.get("percentage", 0.0),
            "status": data.get("status", "Pending"),
            "total_questions": data.get("total_questions", len(data.get("questions", []))),
            "raw_feedback": data.get("raw_feedback", ""),
            "evaluated_at": data.get("evaluated_at", now),
            "created_at": now,
            "updated_at": now,
            "duration_used_seconds": data.get("duration_used", 0),
            "duration_used_minutes": round((data.get("duration_used", 0)) / 60, 2),
            "candidate_id": data.get("candidate_id"),
            "candidate_email": data.get("candidate_email"),
            "candidate_name": data.get("candidate_name"),
            # Violations
            "tab_switches": data.get("tab_switches", 0),
            "inactivities": data.get("inactivities", 0),
            "text_selections": data.get("text_selections", 0),
            "copies": data.get("copies", 0),
            "pastes": data.get("pastes", 0),
            "right_clicks": data.get("right_clicks", 0),
            "face_not_visible": data.get("face_not_visible", 0),
        }
        
        print(f"\nFINAL PAYLOAD:")
        print(f"Basic info:")
        print(f"  candidate_name: {payload['candidate_name']}")
        print(f"  candidate_email: {payload['candidate_email']}")
        print(f"  score: {payload['score']}")
        print(f"Violations in payload:")
        for field in violation_fields:
            print(f"  {field}: {payload[field]}")
        
        print(f"\nAttempting Supabase insert...")
        response = supabase.table("test_results").insert(payload).execute()
        
        print(f"Supabase response received")
        print(f"Response data: {response.data}")
        
        if hasattr(response, 'error') and response.error:
            print(f"Supabase error: {response.error}")
            return jsonify({"error": f"Database error: {response.error}"}), 500
        
        if response.data and len(response.data) > 0:
            saved_record = response.data[0]
            print(f"\nSUCCESS! Record saved with ID: {saved_record.get('id')}")
            print(f"Violations saved:")
            for field in violation_fields:
                saved_value = saved_record.get(field)
                original_value = violations_received[field]
                status = "✓" if saved_value == original_value else "✗"
                print(f"  {field}: {original_value} -> {saved_value} {status}")
            
            return jsonify({
                "status": "success",
                "score": saved_record.get("score"),
                "max_score": saved_record.get("max_score"), 
                "saved_data": saved_record,
                "violations_summary": {field: saved_record.get(field, 0) for field in violation_fields}
            })
        else:
            print("ERROR: No data returned from Supabase insert")
            return jsonify({"error": "Database insert failed - no data returned"}), 500
            
    except Exception as e:
        print(f"\nEXCEPTION in submit_test:")
        print(f"Error type: {type(e)}")
        print(f"Error message: {str(e)}")
        import traceback
        print("Full traceback:")
        print(traceback.format_exc())
        print("="*60)
        
        return jsonify({"error": f"Server error: {str(e)}"}), 500

    except Exception as e:
        print(f"\n💥 ERROR in submit_test:")
        print(f"Error: {str(e)}")
        import traceback
        print("Traceback:")
        print(traceback.format_exc())
        print("="*50 + "\n")
        
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@app.route("/api/results/<question_set_id>/<candidate_email>", methods=["GET"])
def get_result_with_violations(question_set_id, candidate_email):
    try:
        res = supabase.table("test_results").select("*") \
            .eq("question_set_id", question_set_id) \
            .eq("candidate_email", candidate_email) \
            .limit(1).execute()

        if not res.data:
            return jsonify({"error": "Result not found"}), 404

        return jsonify(res.data[0])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5001, debug=False)

