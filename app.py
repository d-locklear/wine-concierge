
from flask import Flask, request, jsonify
from openai import OpenAI
import gspread
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Flask setup
app = Flask(__name__)

# OpenAI setup
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Google Sheets setup
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
import json
creds_dict = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
gs_client = gspread.authorize(creds)
sheet = gs_client.open("Locklear Wine Data").sheet1
records = sheet.get_all_records()
df = pd.DataFrame(records)

# Recommendation function
def recommend_wine(user_prompt):
    wine_data = "\n".join([
        f"{row['Wine Name']}: {row['Flavor Profile']}, Sweetness: {row['Sweetness']}, Pairings: {row['Pairings']}"
        for _, row in df.iterrows()
    ])

    full_prompt = f"""You're an AI wine expert at Locklear Vineyard and Winery. A customer asks:

    "{user_prompt}"

    Here are the wines available:
    {wine_data}

    Recommend the best option and explain why.
    """

    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {
                "role": "system",
                "content": "You're the wine concierge for Locklear Vineyard & Winery in North Carolina. You speak with approachable confidence, using friendly, knowledgeable language. You're warm and welcoming without being overly casual. You offer pairing suggestions, tasting insights, and recommendations with a tone that feels both professional and personal—like a great host in a tasting room."
            },
            {"role": "user", "content": full_prompt}
        ]
    )

    return response.choices[0].message.content

# Flask route
@app.route("/ask", methods=["POST"])
def ask():
    data = request.get_json()
    user_prompt = data.get("prompt", "")
    if not user_prompt:
        return jsonify({"error": "Prompt is required"}), 400

    try:
        recommendation = recommend_wine(user_prompt)
        return jsonify({"response": recommendation})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Health check (optional)
@app.route("/")
def home():
    return "🍷 Locklear Wine Concierge is running!"

