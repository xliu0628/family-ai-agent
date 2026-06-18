import os
import requests
import urllib.parse  # Added to manually build the login link
from dotenv import load_dotenv

# 1. ENVIRONMENT INITIALIZATION
load_dotenv()

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import RedirectResponse
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google import genai
from supabase import create_client, Client

app = FastAPI(title="Family AI Assistant Multi-User API")

# --- 🔍 DEBUG ENVIRONMENT KEYS ---
print("--- 🔍 DEBUG ENVIRONMENT KEYS ---")
client_id = os.environ.get("GOOGLE_CLIENT_ID")
client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

print(f"Loaded Client ID: {client_id}")
print(f"Loaded Client Secret: {client_secret[:10] if client_secret else 'None'}...")
print("---------------------------------")


# 2. CLOUD DATABASE & INTEGRATIONS CONFIG
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/calendar'
]

REDIRECT_URI = "http://127.0.0.1:8000/callback"


# 3. THE WEB ROUTING ENDPOINTS

@app.get("/")
def read_root():
    return {"status": "online", "message": "Multi-user backend running cleanly."}

@app.get("/login")
def login(user_id: str, request: Request):
    """
    Kicks off the login sequence by manually constructing the Google Auth URL.
    Dynamically infers the correct redirect_uri based on the incoming request host.
    """
    # 1. Look for Render environment variable first
    redirect_target = os.environ.get("REDIRECT_URI")
    
    # 2. Dynamic fallback: If running on Render, construct it from the live host automatically
    if not redirect_target:
        host = request.headers.get("host", "127.0.0.1:8000")
        if "onrender.com" in host:
            redirect_target = f"https://{host}/callback"
        else:
            redirect_target = f"http://{host}/callback"
            
    print(f"📡 DEBUG: Initiating OAuth link using redirect target: {redirect_target}")

    params = {
        "client_id": os.environ.get("GOOGLE_CLIENT_ID"),
        "redirect_uri": redirect_target,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",         # Tells Google we need offline background access
        "prompt": "consent",              # Forces the consent screen to guarantee refresh token delivery
        "include_granted_scopes": "true", # Carries over existing permissions cleanly
        "state": user_id
    }

    
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"
    return RedirectResponse(auth_url)

@app.get("/callback")
def callback(request: Request, code: str, state: str):
    """Catches the authenticated callback and executes the direct token trade."""
    if not supabase:
        raise HTTPException(status_code=500, detail="Database connection unconfigured.")

    # 1. Dynamically infer the redirect URI so it perfectly matches Step 1
    redirect_target = os.environ.get("REDIRECT_URI")
    if not redirect_target:
        host = request.headers.get("host", "127.0.0.1:8000")
        if "onrender.com" in host:
            redirect_target = f"https://{host}/callback"
        else:
            redirect_target = f"http://{host}/callback"

    try:
        token_url = "https://oauth2.googleapis.com/token"
        payload = {
            "code": code,
            "client_id": os.environ.get("GOOGLE_CLIENT_ID"),
            "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET"),
            "redirect_uri": redirect_target,  # <-- THIS MUST BE redirect_target, NOT REDIRECT_URI
            "grant_type": "authorization_code"
        }

        response = requests.post(token_url, data=payload)
        token_data = response.json()

        if "error" in token_data:
            raise Exception(f"Google Server Error: {token_data.get('error_description', token_data['error'])}")

        token_data["scopes"] = SCOPES

        supabase.table("users_config").upsert({
            "user_id": state,
            "encrypted_gmail_token": token_data,
            "target_keywords": "ChangeMe"
        }).execute()

        return {"status": "success", "message": f"Google Account linked for User ID: {state}!"}

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Exchange failed: {str(e)}")

# 4. MULTI-USER SWEEP AUTOMATION ROUTE
@app.post("/api/agent/trigger-sweep")
def trigger_global_sweep(background_tasks: BackgroundTasks):
    print("🎯 WEBHOOK RECEIVED: /api/agent/trigger-sweep hit via POST!")
    
    if not supabase:
        print("❌ CRITICAL: Webhook aborted because Supabase client is None!")
        raise HTTPException(status_code=500, detail="Database offline.")

    print("⏳ Enqueuing execute_all_user_sweeps to BackgroundTasks...")
    background_tasks.add_task(execute_all_user_sweeps)
    
    return {"status": "accepted", "message": "Global agent sweep initiated in the background."}

def execute_all_user_sweeps():
    print("🚀 Starting Global Cloud Sweep across all active user accounts...")
    try:
        response = supabase.table("users_config").select("*").execute()
        active_users = response.data
        print(f"📋 Found {len(active_users)} profiles to process.")
        
        for user in active_users:
            user_id = user["user_id"]
            token_json = user.get("encrypted_gmail_token")
            
            if not token_json:
                continue
                
            print(f"👤 Processing active agent cycle for User ID: {user_id}")
            
            # 🛠️ FIX: Pull client ID and Secret from os.environ, NOT from the token_json
            user_creds = Credentials(
                token=token_json.get("access_token"),
                refresh_token=token_json.get("refresh_token"),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=os.environ.get("GOOGLE_CLIENT_ID"),         # <-- Fixed
                client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"), # <-- Fixed
                scopes=token_json.get("scopes")
            )
 
            sender_filter = user.get("target_sender", "*@seattleschools.org")
            keyword_filter = user.get("target_keywords", "ChangeMe")
           
            run_agent_cycle(creds=user_creds, sender_filter=sender_filter, keyword_filter=keyword_filter) 
            print(f"🔍 Custom Filters -> Sender: {sender_filter} | Keywords: {keyword_filter}")
            print(f"✅ Completed processing logic run for user {user_id}")
            
    except Exception as e:
        print(f"❌ Error during global cloud sweep loop: {e}")

def run_agent_cycle(creds, sender_filter, keyword_filter):
    """Connects to Gmail, applies filters, and uses Gemini to extract calendar events."""
    print("\n🤖 --- Booting up Gmail Agent Brain ---")
    
    # 1. Initialize the Gemini Client
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_api_key:
        print("❌ Error: GEMINI_API_KEY is missing from environment variables.")
        return
        
    ai_client = genai.Client(api_key=gemini_api_key)

    try:
        service = build('gmail', 'v1', credentials=creds)
        query = f"from:{sender_filter} ({keyword_filter}) newer_than:2d"
        print(f"🔍 Executing Live Inbox Search: [{query}]")
        
        results = service.users().messages().list(userId='me', q=query).execute()
        messages = results.get('messages', [])

        if not messages:
            print("📭 No new matching school emails found in the last 48 hours.")
            return

        print(f"📬 Success! Found {len(messages)} matching emails to analyze.")
        
        for msg in messages:
            msg_detail = service.users().messages().get(userId='me', id=msg['id'], format='snippet').execute()
            snippet = msg_detail.get('snippet', '')
            print(f"\n📄 Analyzing Snippet: {snippet}")
            
            # 2. Instruct Gemini on exactly how to read and extract the data
            prompt = f"""
            You are a highly accurate calendar assistant. Read the following email snippet from a school.
            Extract any upcoming events, dates, and times related to the students.
            
            Return ONLY a valid JSON array of objects with the following keys. Do not include markdown formatting or backticks.
            - "event_name" (string)
            - "date" (string, format YYYY-MM-DD if possible, guess the year based on context)
            - "time" (string, or "TBD" if not mentioned)
            - "child_name" (string, e.g. Eleanor, Hazel, or "Both")
            
            If no events are found, return an empty array: []
            
            Email snippet: {snippet}
            """
            
            # 3. Call the Gemini API
            try:
                response = ai_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt
                )
                print(f"🧠 Gemini Extracted JSON: {response.text}")
            except Exception as ai_error:
                print(f"❌ Gemini Processing Error: {ai_error}")

        print("\n✅ Cycle Complete. Ready for Calendar Booking.")

    except Exception as e:
        print(f"❌ Error during Gmail scanning cycle: {e}")
