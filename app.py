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

        violations = {
            "tab_switches": data.get("tab_switches", 0),
            "inactivities": data.get("inactivities", 0),
            "text_selections": data.get("text_selections", 0),
            "copies": data.get("copies", 0),
            "pastes": data.get("pastes", 0),
            "right_clicks": data.get("right_clicks", 0),
            "face_not_visible": data.get("face_not_visible", 0),
        }

        total_violations = sum(violations.values())

        sql = """
        INSERT INTO test_results (
            id,
            candidate_id,
            candidate_name,
            candidate_email,
            question_set_id,
            max_score,
            percentage,
            status,
            total_questions,
            raw_feedback,
            evaluated_at,
            created_at,
            updated_at,
            duration_used_seconds,
            duration_used_minutes,
            tab_switches,
            inactivities,
            text_selections,
            copies,
            pastes,
            right_clicks,
            face_not_visible,
            violations
        ) VALUES (
            %(id)s,
            %(candidate_id)s,
            %(candidate_name)s,
            %(candidate_email)s,
            %(question_set_id)s,
            %(max_score)s,
            %(percentage)s,
            %(status)s,
            %(total_questions)s,
            %(raw_feedback)s,
            %(evaluated_at)s,
            %(created_at)s,
            %(updated_at)s,
            %(duration_used_seconds)s,
            %(duration_used_minutes)s,
            %(tab_switches)s,
            %(inactivities)s,
            %(text_selections)s,
            %(copies)s,
            %(pastes)s,
            %(right_clicks)s,
            %(face_not_visible)s,
            %(violations)s
        )
        RETURNING *;
        """

        params = {
            "id": str(uuid.uuid4()),
            "candidate_id": data.get("candidate_id"),
            "candidate_name": data.get("candidate_name"),
            "candidate_email": data.get("candidate_email"),
            "question_set_id": data.get("question_set_id"),
            "max_score": data.get("max_score", 0),
            "percentage": data.get("percentage", 0.0),
            "status": data.get("status", "Pending"),
            "total_questions": data.get("total_questions", len(data.get("questions", []))),
            "raw_feedback": data.get("raw_feedback", ""),
            "evaluated_at": datetime.utcnow().isoformat(),
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "duration_used_seconds": data.get("duration_used", 0),
            "duration_used_minutes": round((data.get("duration_used", 0)) / 60, 2),
            **violations,
            "violations": total_violations,
        }

        # 🚨 Using Supabase PostgREST directly doesn’t allow raw SQL
        # You’ll need a Postgres connection string OR Supabase function (rpc)
        response = supabase.postgrest.rpc("exec_sql", {"sql": sql, "params": params}).execute()

        return jsonify({"status": "success", "saved": response.data})
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
