import pandas as pd
from supabase import create_client
from dotenv import load_dotenv
import os

# Load Supabase credentials
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase credentials not found in .env!")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Load CSV
csv_file = "violations.csv"
df = pd.read_csv(csv_file)

# Iterate rows and insert into Supabase
for _, row in df.iterrows():
    data = {
        "candidate_id": row["candidate_id"],
        "exam_id": row["exam_id"],
        "candidate_name": row.get("candidate_name", ""),
        "tab_switches": int(row.get("tab_switches", 0)),
        "inactivities": int(row.get("inactivities", 0)),
        "text_selections": int(row.get("text_selections", 0)),
        "copies": int(row.get("copies", 0)),
        "pastes": int(row.get("pastes", 0)),
        "right_clicks": int(row.get("right_clicks", 0)),
    }

    try:
        supabase.table("violations").insert(data).execute()
        print(f"Inserted: {row['candidate_id']} / {row['exam_id']}")
    except Exception as e:
        print(f"Failed to insert {row['candidate_id']} / {row['exam_id']}: {e}")
