import os
import json
from google import genai
from google.genai import types

# Import the tools we built
from app.gmail_tool import list_recent_emails
from app.calendar_tool import add_calendar_event

def run_agent_cycle():
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    
    print("🤖 Agent initiating upgraded Tool-Use sweep...")
    
    # 1. Fetch your live data context
    recent_emails = list_recent_emails(max_results=5)
    if not recent_emails:
        print("Inbox is clear or no emails returned. Exiting cycle.")
        return
        
    # 2. Initialize Gemini 2.5 Flash
    client = genai.Client()
    
    # Define our execution instructions
    system_instruction = """
    You are an Executive Assistant AI Agent. Your job is to analyze the provided emails 
    and identify deadlines, appointments, or clear events that belong on a user's calendar.
    
    If you find a clear commitment or deadline, call the 'add_calendar_event' tool 
    with the appropriate parameters. If an email has no deadlines, do nothing.
    """

    prompt = f"""
    Today's reference date context is Tuesday, June 16, 2026.
    Analyze these recent email snippets and use your tools to schedule any deadlines you find:
    
    {recent_emails}
    """
    
    print("🧠 Handing control to Gemini 2.5 Flash to evaluate tools...")
    
    # 3. Call Gemini, passing our Python function directly as a tool
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            # Pass the function blueprint directly in the tools list
            tools=[add_calendar_event],
            # Use standard strings for the execution mode
            tool_config={
                "function_calling_config": {
                    "mode": "AUTO"
                }
            }
        )
    )

    # 4. Check if Gemini decided to run your function
    # The SDK handles executing the function behind the scenes if the model requested it
    if response.function_calls:
        print(f"\n✅ Success! Gemini executed {len(response.function_calls)} tool call(s).")
    else:
        print("\n💤 Sweep complete. Gemini reviewed the emails and found no actionable deadlines.")

if __name__ == "__main__":
    run_agent_cycle()


from app.calendar_tool import get_calendar_briefing

def generate_daily_briefing():
    """
    Gathers agenda data for the next 3 days and uses Gemini to synthesize 
    a clean, readable morning brief for the user.
    """
    print("\n🌅 Compiling your Morning Briefing...")
    
    # 1. Grab raw calendar events for the next 3 days
    raw_agenda = get_calendar_briefing(days_ahead=3)
    
    if not raw_agenda:
        print("Your calendar is completely clear for the next 3 days! No brief needed.")
        return "Your calendar is clear for the next 3 days."
        
    # 2. Package the context for Gemini
    agenda_context = json.dumps(raw_agenda, indent=2)
    
    system_instruction = """
    You are an elite Executive Assistant. Your goal is to provide a highly concise, 
    warm, and clear morning briefing based on raw calendar entries.
    
    Group the events by:
    - TODAY
    - TOMORROW
    - THE DAY AFTER
    
    Highlight any major deadliness, school drop-offs, or scheduling conflicts. Keep it punchy 
    so the user can read it in 15 seconds. Use clean markdown bullet points.
    """
    
    prompt = f"""
    Analyze this raw agenda data and compile a clean, conversational 3-day briefing block:
    
    {agenda_context}
    """
    
    # 3. Ask Gemini to write the briefing
    client = genai.Client()
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction
        )
    )
    
    briefing_text = response.text.strip()
    
    print("\n=================== 🌅 YOUR DAILY BRIEFING ===================")
    print(briefing_text)
    print("==============================================================")

    # ADD THIS LINE: Automatically post the compiled results to your calendar
    from app.calendar_tool import post_daily_brief_to_calendar
    post_daily_brief_to_calendar(briefing_text)
    
    return briefing_text
