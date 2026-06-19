import os
import json
import requests
import urllib.parse  # Added to manually build the login link
from dotenv import load_dotenv

# 1. ENVIRONMENT INITIALIZATION
load_dotenv()

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import RedirectResponse
from fastapi import FastAPI, BackgroundTasks, Request, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google import genai
from supabase import create_client, Client

app = FastAPI(title="Family AI Assistant Multi-User API")
templates = Jinja2Templates(directory="templates")

# --- 🔍 DEBUG ENVIRONMENT KEYS ---
print("--- 🔍 DEBUG ENVIRONMENT KEYS ---")
client_id = os.environ.get("GOOGLE_CLIENT_ID")
client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

print(f"Loaded Client ID: {client_id}")
print(f"Loaded Client Secret: {client_secret[:10] if client_secret else 'None'}...")
print("---------------------------------")

from cryptography.fernet import Fernet
import os

def decrypt_token(encrypted_token: str) -> str:
    # Example using Fernet (ensure ENCRYPTION_KEY is in your Render Env vars)
    key = os.environ.get("ENCRYPTION_KEY")
    f = Fernet(key)
    return f.decrypt(encrypted_token.encode()).decode()

from pydantic import BaseModel

class ConfigPayload(BaseModel):
    user_id: str
    sender: str
    keywords: str

@app.post("/api/agent/save-config")
def save_config(payload: ConfigPayload):
    """Updates the user configuration directly inside Supabase from the UI."""
    if not supabase:
        raise HTTPException(status_code=500, detail="Database offline.")
        
    try:
        supabase.table("users_config").update({
            "target_sender": payload.sender,
            "target_keywords": payload.keywords
        }).eq("user_id", payload.user_id).execute()
        
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# Data model to handle toggle updates from the frontend checkboxes
class TaskTogglePayload(BaseModel):
    task_id: str
    status: str

@app.post("/api/agent/tasks/toggle")
def toggle_task_status(payload: TaskTogglePayload):
    """Updates a task's status ('pending' vs 'completed') from the UI."""
    if not supabase:
        raise HTTPException(status_code=500, detail="Database offline.")
    try:
        supabase.table("user_tasks").update({"status": payload.status}).eq("id", payload.task_id).execute()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# 2. CLOUD DATABASE & INTEGRATIONS CONFIG
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/calendar'
]

REDIRECT_URI = "http://127.0.0.1:8000/callback"

class DeleteEmailPayload(BaseModel):
    user_id: str
    email_address: str

@app.post("/api/agent/delete-email")
def delete_connected_email(payload: DeleteEmailPayload):
    """Deletes a linked Gmail inbox record from Supabase."""
    if not supabase:
        raise HTTPException(status_code=500, detail="Database disconnected.")
        
    try:
        # Wipe out the specific email token row matching the current session profile
        supabase.table("connected_emails")\
            .delete()\
            .eq("user_id", payload.user_id)\
            .eq("email_address", payload.email_address)\
            .execute()
            
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# 3. THE WEB ROUTING ENDPOINTS
import uuid

@app.get("/")
def serve_dashboard(request: Request, user_id: str = None):
    # Case A: User typed a completely bare URL (No user_id in the address bar)
    if not user_id or user_id.strip() == "":
        # 🍪 Check if this browser has a saved session cookie from before
        saved_user_id = request.cookies.get("family_agent_user_id")
        
        if saved_user_id:
            print(f"🍪 Found return user session cookie! Redirecting to dashboard: {saved_user_id}")
            return RedirectResponse(url=f"/?user_id={saved_user_id}", status_code=303)
        
        # Truly brand new user with no cookie history -> Give them a clean slate ID
        import uuid
        new_user_id = str(uuid.uuid4())
        print(f"✨ Brand new visitor. Assigning unique ID: {new_user_id}")
        
        response = RedirectResponse(url=f"/?user_id={new_user_id}", status_code=303)
        # Drop the cookie onto their device so they are remembered next time
        response.set_cookie(key="family_agent_user_id", value=new_user_id, max_age=31536000) # Valid for 1 year
        return response

    # Case B: The user has a user_id explicitly in the URL bar (e.g., your private bookmark)
    # We load the page normally, but we also ensure their cookie is updated to match this ID!
    current_sender = ""
    current_keywords = ""
    connected_accounts = []
    tasks = []

    try:
        if supabase:
            config_res = supabase.table("users_config").select("*").eq("user_id", user_id).execute()
            if config_res.data:
                user_data = config_res.data[0]
                current_sender = user_data.get("target_sender", current_sender)
                current_keywords = user_data.get("target_keywords", current_keywords)
            
            emails_res = supabase.table("connected_emails").select("email_address").eq("user_id", user_id).execute()
            connected_accounts = [row["email_address"] for row in emails_res.data] if emails_res.data else []
            
            tasks_res = supabase.table("user_tasks").select("*").eq("user_id", user_id).order("due_date").execute()
            tasks = tasks_res.data if tasks_res.data else []
            
    except Exception as e:
        print(f"⚠️ Error fetching UI configurations: {e}")

    # Generate the standard page response
    response = templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context={
            "request": request,
            "user_id": user_id,       
            "sender": current_sender,
            "keywords": current_keywords,
            "connected_accounts": connected_accounts,
            "tasks": tasks
        }
    )
    
    # 💾 Update the cookie to sync with whatever ID is currently active in the address bar
    response.set_cookie(key="family_agent_user_id", value=user_id, max_age=31536000)
    return response
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

        # 🛠️ NEW MULTI-ACCOUNT CODE TO PASTE IN:
        token_data["scopes"] = SCOPES

        # Create a temporary credentials wrapper to ask Google for the email address
        creds = Credentials(
            token=token_data.get("access_token"),
            refresh_token=token_data.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.environ.get("GOOGLE_CLIENT_ID"),
            client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
            scopes=token_data.get("scopes")
        )
        
        # Call the Gmail API profile endpoint to get the user's specific email address
        gmail_service = build('gmail', 'v1', credentials=creds)
        profile = gmail_service.users().getProfile(userId='me').execute()
        user_email = profile.get('emailAddress')

        supabase.table("users_config").upsert({
            "user_id": state,
            "target_keywords": "*"  
        }).execute()

        # Check if this email is already linked to this user in our new table
        existing = supabase.table("connected_emails").select("id").eq("user_id", state).eq("email_address", user_email).execute()
        
        if existing.data:
            # Update the token for this email if it already exists
            supabase.table("connected_emails").update({
                "encrypted_gmail_token": token_data
            }).eq("id", existing.data[0]["id"]).execute()
            print(f"🔄 Updated token for connected account: {user_email}")
        else:
            # Add a brand new connection record if it's a new email address
            supabase.table("connected_emails").insert({
                "user_id": state,
                "email_address": user_email,
                "encrypted_gmail_token": token_data
            }).execute()
            print(f"➕ Added brand new inbox connection: {user_email}")

        # 🛠️ NEW: Drop the cookie during callback so their device remembers this account connection
        response = RedirectResponse(url=f"/?user_id={state}")
        response.set_cookie(key="family_agent_user_id", value=state, max_age=31536000)
        return response

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
    """Loops through all active configurations safely and logs any inner loop errors."""
    print("\n🚀 Starting Global Cloud Sweep across all active user accounts...")
    if not supabase:
        print("❌ Supabase connection missing in background thread.")
        return
        
    try:
        profiles = supabase.table("users_config").select("*").execute()
        print(f"📋 Found {len(profiles.data)} profiles to process.")
        
        for profile in profiles.data:
            # Wrap the individual profile execution in a try block so it won't die silently
            try:
                user_id = profile.get("user_id")
                sender_raw = profile.get("target_sender") or "" # Fallback to empty string if None
                keywords = profile.get("target_keywords") or "*"
                
                print(f"🔍 DEBUG: Fetching inboxes for profile user_id: {user_id}")
                
                # Safe comma-splitting
                senders = [s.strip() for s in str(sender_raw).split(",") if s.strip()]
                if not senders:
                    senders = ["*"]

                # Fetch email connections
                email_records = supabase.table("connected_emails").select("*").eq("user_id", user_id).execute()
                print(f"📋 DEBUG: Found {len(email_records.data)} linked inbox rows for this user.")
                
                if not email_records.data:
                    print(f"📭 User {user_id} has no connected email records yet.")
                    continue
                    
                for email_account in email_records.data:
                    email_address = email_account.get("email_address")
                    token_package = email_account.get("encrypted_gmail_token")
                    
                    # 🛠️ FIX: If the database returns the token as a string, parse it into a dict!
                    if isinstance(token_package, str):
                        import json
                        token_package = json.loads(token_package)
                    
                    print(f"👤 Ready to run sweep loop on email inbox: {email_address}")
                    
                    from google.oauth2.credentials import Credentials
                    creds = Credentials(
                        token=token_package.get("access_token"),
                        refresh_token=token_package.get("refresh_token"),
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.environ.get("GOOGLE_CLIENT_ID"),
                        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
                        scopes=token_package.get("scopes")
                    )
    
                    for sender in senders:
                        print(f"🚀 Triggering run_agent_cycle for {email_address} targeting sender: {sender}")
                        run_agent_cycle(creds, user_id, sender, keywords)
                        
            except Exception as inner_error:
                print(f"❌ Error while running individual profile loop for user {profile.get('user_id')}: {str(inner_error)}")
                
    except Exception as global_error:
        print(f"❌ Global sweep loop crash: {str(global_error)}")

def run_agent_cycle(creds, user_id, sender_filter, keyword_filter):
    """Fetches emails, extracts tasks via Gemini, and saves them natively to Supabase."""
    print("\n🤖 --- Booting up Full Task Extraction Cycle ---")
    
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_api_key:
        print("❌ Error: GEMINI_API_KEY is missing.")
        return
        
    from google import genai
    import json
    ai_client = genai.Client(api_key=gemini_api_key)

    try:
        # 1. Read the Gmail inbox
        gmail_service = build('gmail', 'v1', credentials=creds)
        query = f"from:{sender_filter} ({keyword_filter}) newer_than:7d"
        results = gmail_service.users().messages().list(userId='me', q=query).execute()
        messages = results.get('messages', [])

        if not messages:
            print("📭 No new matching school emails found in the last 48 hours.")
            return

        print(f"📬 Found {len(messages)} matching emails to process.")
        
        # Grab the user_id dynamically from the credential wrapper or database mapping context
           # 1. Collect all snippets into a single combined payload first
        combined_email_payload = []
        
        for msg in messages:
            msg_detail = gmail_service.users().messages().get(userId='me', id=msg['id'], format='metadata').execute()
            snippet = msg_detail.get('snippet', '')
            combined_email_payload.append({
                "email_id": msg['id'],
                "content": snippet
            })

        # 2. Fire ONE single batch prompt to Gemini outside the loop
        batch_prompt = f"""
        You are an expert administrative assistant. Analyze this collection of school email snippets and extract all actionable items, events, and due dates.
        
        Emails to analyze:
        {json.dumps(combined_email_payload, indent=2)}

        For each extracted item, return a JSON array containing objects with these exact keys:
        - 'task_name': clear descriptive name
        - 'due_date': YYYY-MM-DD formatting if found
        - 'child_name': name of child if inferred
        - 'task_type': 'Event', 'Deadline', or 'To-Do'
        """
        # 3. Call Gemini once using your batch_prompt layout variable
        import time
        from google.genai.errors import APIError  # For the new google-genai SDK
        
        max_retries = 3
        delay = 2  # start with a 2-second delay
        response = None

        for attempt in range(max_retries):
            try:
                response = ai_client.models.generate_content(model='gemini-2.5-flash', contents=batch_prompt)
                break  # 🎉 Success! Break out of the retry loop.
            except APIError as e:
                # Check if it's a 503 or transient overload error
                if e.code == 503 and attempt < max_retries - 1:
                    print(f"⏳ Gemini 503 experiencing high demand. Retrying in {delay}s... (Attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                    delay *= 2  # Double the wait time for the next try
                else:
                    print(f"❌ Gemini API failed completely after {max_retries} attempts.")
                    raise e  # Re-raise the exception to be caught by your outer handlers
            except Exception as e:
                # Catch any other unexpected network glitches
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    delay *= 2
                else:
                    raise e

        # Code continues normally if response was successful:
        clean_text = response.text.replace("```json", "").replace("```", "").strip()

        # 4. Parse the single array and execute the zero-token database writes
        try:
            extracted_tasks = json.loads(clean_text)

            for task in extracted_tasks:
                if supabase:
                    supabase.table("user_tasks").insert({
                        "user_id": user_id,
                        "child_name": task.get("child_name", "Both"),
                        "task_name": task.get("task_name"),
                        "task_type": task.get("task_type", "To-Do"),
                        "due_date": task.get("date"),  # Maps cleanly to the prompt "date" key
                        "status": "pending"
                    }).execute()

            print(f"✅ Batch extraction complete! Wrote {len(extracted_tasks)} tasks to Supabase.")

        except Exception as parse_err:
            print(f"❌ Failed parsing batch JSON payload: {parse_err}")
            print(f"Raw model response text was: {clean_text}")

    except Exception as e:
        print(f"❌ Error during agent cycle: {e}")

@app.get("/api/agent/test-gemini-parse")
def test_gemini_parse():
    """Simulates a raw school email snippet to test the Gemini LLM parser."""
    print("\n🧪 --- Running Mock Gemini Parsing Test ---")
    
    gemini_api_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is missing from Render environment.")
        
    # Initialize the client using the official google-genai library
    from google import genai
    ai_client = genai.Client(api_key=gemini_api_key)
    
    # A highly realistic, unstructured school newsletter email snippet
    mock_snippet = (
        "Hi parents, just a reminder that Eleanor has her kindergarten field trip to the Seattle Aquarium "
        "this coming Friday, June 19th. The bus leaves at 9:00 AM and we will return by 1:30 PM. Please pack a sack lunch! "
        "Also, the Hazel school library books must be returned by Monday morning."
    )
    
    print(f"📄 Testing Mock Snippet: {mock_snippet}")
    
    prompt = f"""
    You are a highly accurate calendar assistant. Read the following email snippet from a school.
    Extract any upcoming events, dates, and times related to the students.
    
    Return ONLY a valid JSON array of objects with the following keys. Do not include markdown formatting or backticks.
    - "event_name" (string)
    - "date" (string, format YYYY-MM-DD if possible, guess the year based on context. Note: Current year is 2026)
    - "time" (string, or "TBD" if not mentioned)
    - "child_name" (string, e.g. Eleanor, Hazel, or "Both")
    
    If no events are found, return an empty array: []
    
    Email snippet: {mock_snippet}
    """
    
    try:
        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        print(f"🧠 Gemini Extracted JSON: {response.text}")
        
        # Parse text string into JSON array to return cleanly to the browser screen
        import json
        clean_text = response.text.replace("```json", "").replace("```", "").strip()
        parsed_events = json.loads(clean_text)
        
        return {
            "status": "success",
            "mock_input_processed": mock_snippet,
            "gemini_extracted_events": parsed_events
        }
        
    except Exception as e:
        print(f"❌ Gemini Processing Error: {e}")
        raise HTTPException(status_code=400, detail=f"LLM Parsing failed: {str(e)}")
