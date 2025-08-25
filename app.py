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
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
register_socket_events(socketio)


@app.route("/")
def index():
    return jsonify({"status": "Server is running."})

@app.route("/api/exam/<candidate_id>", methods=["GET"])
def get_exam_for_candidate(candidate_id):
    """
    Returns candidate info and exam questions based on candidate_id
    """
    try:
        # 1️⃣ Fetch candidate info from Supabase (replace 'candidates' with your table)
        candidate_resp = supabase.table("candidates").select("*").eq("id", candidate_id).execute()
        if not candidate_resp.data:
            return jsonify({"error": "Candidate not found"}), 404
        candidate = candidate_resp.data[0]
 
        # 2️⃣ Fetch exam questions for this candidate
        exam_id = candidate.get("exam_id")
        test_resp = supabase.table("exams").select("*").eq("id", exam_id).execute()
        questions = test_resp.data if test_resp.data else []
 
        # 3️⃣ Return combined response
        return jsonify({
            "candidate": {
                "id": candidate["id"],
                "name": candidate["name"],
                "email": candidate["email"],
                "exam_id": exam_id
            },
            "questions": questions
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
            jd_id=test_id
        )
        questions = asyncio.run(generate_questions(test_request))
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
            coding_count=data.get("coding_count")
        )
        questions = asyncio.run(generate_questions(test_request))
        return jsonify({"questions": questions})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/test/submit", methods=["POST"])
def submit_test():
    try:
        data = request.get_json()
        return jsonify({"status": "success", "submitted_data": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/feedback/<question_set_id>", methods=["GET"])
def get_feedback(id, question_set_id):
    try:
        response = supabase.table("violations") \
            .select("*") \
            .eq("id", id) \
            .eq("question_set_id", question_set_id) \
            .execute()
        return jsonify(response.data[0] if response.data else {"message": "No feedback found"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/results/<question_set_id>/<candidate_email>", methods=["GET"])
def get_result_with_violations(question_set_id, candidate_email):
    try:
        res = supabase.table("exam_results").select("*") \
            .eq("question_set_id", question_set_id) \
            .eq("candidate_email", candidate_email) \
            .limit(1).execute()

        if not res.data:
            return jsonify({"error": "Result not found"}), 404

        result_row = res.data[0]

        vio = supabase.table("violations").select(
            "tab_switches,inactivities,text_selections,copies,pastes,right_clicks,face_not_visible"
        ).eq("question_set_id", question_set_id) \
         .eq("candidate_email", candidate_email) \
         .limit(1).execute()

        v = (vio.data[0] if vio.data else {})
        merged = {
            **result_row,
            "tab_switches": v.get("tab_switches", 0),
            "inactivities": v.get("inactivities", 0),
            "text_selections": v.get("text_selections", 0),
            "copies": v.get("copies", 0),
            "pastes": v.get("pastes", 0),
            "right_clicks": v.get("right_clicks", 0),
            "face_not_visible": v.get("face_not_visible", 0),
        }
        return jsonify(merged)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/feedback", methods=["POST"])
def post_feedback():
    try:
        data = request.get_json()
        question_set_id = data.get("question_set_id")

        if not question_set_id:
            return jsonify({"error": "question_set_id is required"}), 400

        feedback = {
            "question_set_id": question_set_id,
            "candidate_name": data.get("candidate_name"),
            "candidate_email": data.get("candidate_email"),
            "tab_switches": data.get("tab_switches", 0),
            "inactivities": data.get("inactivities", 0),
            "copies": data.get("copies", 0),
            "pastes": data.get("pastes", 0),
            "right_clicks": data.get("right_clicks", 0),
            "text_selections": data.get("text_selections", 0),
            "face_not_visible": data.get("face_not_visible", 0),
        }

        if data.get("id"):
            feedback["id"] = data["id"]
            # ✅ use upsert if id is present
            response = supabase.table("violations").upsert(feedback, on_conflict="id").execute()
        else:
            # ✅ plain insert lets DB generate id
            response = supabase.table("violations").insert(feedback).execute()

        return jsonify({
            "status": "success",
            "saved_data": response.data
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

''' @socketio.on("suspicious_event")
def handle_suspicious_event(data):
    candidate_id = data.get("candidate_id")
    exam_id = data.get("exam_id")
    violation_type = data.get("violation_type")

    if not candidate_id or not exam_id or not violation_type:
        return
    column_map = {
        "tab_switches": "tab_switches",
        "inactivity": "inactivities",
        "text_selection": "text_selections",
        "copy": "copies",
        "paste": "pastes",
        "right_clicks": "right_clicks"    }

    col = column_map.get(violation_type)
    if col:
        try:
            supabase.rpc("increment_violation", {
                "cand_id": candidate_id,
                "exam": exam_id,
                "field": col
            }).execute()
        except Exception as e:
            print(f"⚠️ Failed to update violation: {e}") '''

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5173, debug=False)