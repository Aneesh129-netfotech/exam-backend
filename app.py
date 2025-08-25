from flask import Flask, jsonify, request
from flask_socketio import SocketIO
from flask_cors import CORS
from dotenv import load_dotenv
import os
import logging
import asyncio
from supabase import create_client

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

        # Save exam results including violations
        payload = {
            "question_set_id": data.get("question_set_id"),
            "candidate_name": data.get("candidate_name"),
            "candidate_email": data.get("candidate_email"),
            "score": data.get("score", 0),
            "duration_used_seconds": data.get("duration_used", 0),
            # Map violations to individual columns
            "tab_switches": data.get("violations", {}).get("tabSwitches", 0),
            "inactivities": data.get("violations", {}).get("windowMinimizations", 0),
            "text_selections": data.get("violations", {}).get("textSelections", 0),
            "copies": data.get("violations", {}).get("copies", 0),
            "pastes": data.get("violations", {}).get("pastes", 0),
            "right_clicks": data.get("violations", {}).get("rightClicks", 0),
            "face_not_visible": data.get("violations", {}).get("noFace", 0),
        }

        response = supabase.table("results").insert(payload).execute()
        return jsonify({"status": "success", "saved_data": response.data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/results/<question_set_id>/<candidate_email>", methods=["GET"])
def get_result_with_violations(question_set_id, candidate_email):
    try:
        res = supabase.table("results").select("*") \
            .eq("question_set_id", question_set_id) \
            .eq("candidate_email", candidate_email) \
            .limit(1).execute()

        if not res.data:
            return jsonify({"error": "Result not found"}), 404

        return jsonify(res.data[0])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)
