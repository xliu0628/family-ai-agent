import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

def get_calendar_service():
    """Authenticates and returns the Google Calendar API service instance."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json')
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise Exception("Authentication token missing or invalid.")
            
    return build('calendar', 'v3', credentials=creds)

def add_calendar_event(summary: str, start_time: str, end_time: str, description: str = "") -> str:
    """
    Creates an event on the user's primary calendar.
    
    Parameters:
    - summary (str): The title of the event (e.g., "Submit Tax Documents")
    - start_time (str): ISO 8601 string format (e.g., "2026-06-20T09:00:00-07:00")
    - end_time (str): ISO 8601 string format (e.g., "2026-06-20T10:00:00-07:00")
    - description (str): Additional notes or email snippets for context.
    """
    try:
        service = get_calendar_service()
        
        event = {
            'summary': summary,
            'description': description,
            'start': {
                'dateTime': start_time,
                'timeZone': 'America/Los_Angeles', # Hardcoded for Pacific Time local dev
            },
            'end': {
                'dateTime': end_time,
                'timeZone': 'America/Los_Angeles',
            },
            'reminders': {
                'useDefault': False,
                # Force an email and a popup notification via the native calendar app
                'overrides': [
                    {'method': 'email', 'minutes': 24 * 60}, # 1 day before
                    {'method': 'popup', 'minutes': 60},      # 1 hour before
                ],
            },
        }

        created_event = service.events().insert(calendarId='primary', body=event).execute()
        print(f"Successfully created event! Link: {created_event.get('htmlLink')}")
        return created_event

    except Exception as error:
        print(f"An error occurred while creating calendar event: {error}")
        return None

if __name__ == "__main__":
    print("Testing Calendar Tool: Adding a dummy mock deadline...")
    # Creating a test event for June 20th, 2026 at 10:00 AM PST
    add_calendar_event(
        summary="Test Agent Deadline",
        start_time="2026-06-20T10:00:00-07:00",
        end_time="2026-06-20T11:00:00-07:00",
        description="This is a test event created by your development script."
    )

import datetime

def get_calendar_briefing(days_ahead: int = 3) -> list:
    """
    Retrieves all scheduled calendar events from now through the next X days.
    """
    try:
        service = get_calendar_service()
        
        # Calculate time windows (Starting right now)
        now = datetime.datetime.utcnow()
        now_iso = now.isoformat() + 'Z' # 'Z' indicates UTC time
        
        # Calculate the end window boundary (e.g., 3 days from now)
        end_window = now + datetime.timedelta(days=days_ahead)
        end_window_iso = end_window.isoformat() + 'Z'
        
        print(f"📅 Fetching calendar events from {now.strftime('%Y-%m-%d')} to {end_window.strftime('%Y-%m-%d')}...")
        
        # Pull events from primary calendar ordered by start time
        events_result = service.events().list(
            calendarId='primary',
            timeMin=now_iso,
            timeMax=end_window_iso,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        events = events_result.get('items', [])
        
        brief_data = []
        for event in events:
            # Handle all-day events vs standard time-blocked events cleanly
            start = event['start'].get('dateTime', event['start'].get('date'))
            end = event['end'].get('dateTime', event['end'].get('date'))
            
            brief_data.append({
                "title": event.get('summary', 'Untitled Event'),
                "start": start,
                "end": end,
                "description": event.get('description', '')
            })
            
        return brief_data

    except Exception as e:
        print(f"Failed to fetch calendar brief: {e}")
        return []


def post_daily_brief_to_calendar(brief_text: str):
    """
    Creates an all-day event on the primary calendar containing the text of the daily brief.
    """
    try:
        service = get_calendar_service()
        
        # Format today's date for an all-day event entry
        today_date = datetime.datetime.now().strftime('%Y-%m-%d')
        
        event_body = {
            'summary': '📋 Read Today\'s Family Briefing',
            'description': brief_text,
            'start': {
                'date': today_date,
            },
            'end': {
                'date': today_date,
            },
            # Add an aggressive popup reminder rule to trigger notification flags
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 0},
                ],
            },
        }
        
        created_event = service.events().insert(calendarId='primary', body=event_body).execute()
        print(f"🚀 Briefing posted to Calendar! Event Link: {created_event.get('htmlLink')}")
        
    except Exception as e:
        print(f"Failed to post daily brief to calendar: {e}")
