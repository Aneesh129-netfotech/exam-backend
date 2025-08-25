import os
import json
import httpx
from dotenv import load_dotenv
from schemas.test_schemas import TestRequest

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

async def call_model(model_name: str, prompt: str):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",  # Required for OpenRouter
        "Content-Type": "application/json",
    }

    body = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "You are a JSON-generating assistant."},
            {"role": "user", "content": prompt},
        ],
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=body)
            print(f"🔵 {model_name} | Status:", response.status_code)
            print("🔵 Response preview:", response.text[:200])

            response.raise_for_status()

            content = response.json()
            ai_text = content["choices"][0]["message"]["content"].strip()
            return json.loads(ai_text)

    except Exception as e:
        print(f"❌ {model_name} failed:", e)
        return None

async def fetch_job_summary(jd_id: str):
    """Fetch job summary using the provided job description ID"""
    try:
        JOB_SUMMARY_API_URL = f"http://localhost:5000/api/jd/get-jd-summary/{jd_id}"
        async with httpx.AsyncClient() as client:
            headers = {
                "Content-Type": "application/json",  # No JWT needed now
            }
            response = await client.get(JOB_SUMMARY_API_URL, headers=headers)
            print(f"🔵 Job Summary API | Status:", response.status_code)
            response.raise_for_status()
            data = response.json()
            return data.get("jobSummary")
    except Exception as e:
        print(f"❌ Job Summary API failed:", e)
        return None

async def generate_questions(request: TestRequest):
    # Use the jd_id from the request to fetch job summary
    job_summary = None
    if request.jd_id:
        job_summary = await fetch_job_summary(request.jd_id)
    
    if not job_summary:
        print("⚠️ Failed to fetch job summary, using fallback mock data")
        job_summary = "Mock job summary: Python developer role requiring skills in web development and data analysis."
    
    request.topic = job_summary

    if request.question_type == "coding":
        prompt = (
            f"Generate {request.num_questions} {request.difficulty} level coding questions "
            f"based on the job summary: '{request.topic}'. Respond only as a JSON array of objects. "
            "Each object should have: question (coding problem statement), answer (expected code/logic). "
            "Do NOT include explanations."
        )
    elif request.question_type == "mixed":
        mcq_count = getattr(request, "mcq_count", request.num_questions // 2)
        coding_count = getattr(request, "coding_count", request.num_questions - mcq_count)

        prompt = (
            f"Generate a mixed set of {mcq_count + coding_count} {request.difficulty} level questions "
            f"based on the job summary: '{request.topic}'. Include exactly {mcq_count} multiple choice questions and "
            f"{coding_count} coding questions.\n\n"
            "Each MCQ should include: question, options (list of 4), and answer.\n"
            "Each coding question should include: question and answer (code or logic).\n"
            "Respond only with a JSON array of such objects."
        )
    else:
        prompt = (
            f"Generate {request.num_questions} {request.difficulty} level multiple choice questions "
            f"based on the job summary: '{request.topic}'. "
            "Respond only as a valid JSON array of objects. Each object should have: "
            "question, options (list of 4), and answer."
        )

    result = await call_model("qwen/qwen3-coder:free", prompt)

    if not result:
        print("⚠️ Falling back to mistralai/mistral-7b-instruct:free")
        result = await call_model("mistralai/mistral-7b-instruct:free", prompt)

    if not result:
        result = [
            {
                "question": "Mock Question: What is Python?",
                "options": ["A programming language", "A snake", "A car", "A song"],
                "answer": "A programming language"
            }
        ]

    return result