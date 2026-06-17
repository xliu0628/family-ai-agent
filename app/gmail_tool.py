import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

def get_gmail_service():
    """Authenticates and returns the Gmail API service instance."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json')
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise Exception("Authentication token missing or invalid. Please run test_auth.py.")
            
    return build('gmail', 'v1', credentials=creds)

def list_recent_emails(max_results: int = 5, sender: str = "*@seattleschools.org", search_terms: str = "Eleanor OR Hazel") -> list:
    """
    Retrieves recent emails from the user's Gmail inbox using target filters.
    """
    # If no parameters are passed from the caller, fall back to environment variables
    if sender is None:
        sender = os.environ.get("TARGET_SENDER", "*@seattleschools.org")
    if search_terms is None:
        search_terms = os.environ.get("TARGET_KEYWORDS", "Eleanor OR Hazel")
    
    try:
        service = get_gmail_service()
        
        # 1. Start with base filters to strip out clutter
        query_parts = ["-category:promotions", "-category:social"]
        
        # 2. Add the sender or domain filter if provided
        if sender:
            query_parts.append(f"from:{sender}")
            
        # 3. Add our specific names/keywords
        if search_terms:
            query_parts.append(f"({search_terms})")
            
        # Join the parts into one clean Gmail search string
        filter_query = " ".join(query_parts)
        print(f"🔍 Executing Gmail Search: {filter_query}")
        
        # Pass the dynamically built query to the API
        results = service.users().messages().list(
            userId='me', 
            maxResults=max_results,
            q=filter_query
        ).execute()
        
        messages = results.get('messages', [])
        
        if not messages:
            return []

        # Parse the email data
        email_data = []
        for msg in messages:
            msg_id = msg['id']
            message = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
            
            headers = message['payload'].get('headers', [])
            subject = next((header['value'] for header in headers if header['name'] == 'Subject'), 'No Subject')
            from_address = next((header['value'] for header in headers if header['name'] == 'From'), 'Unknown Sender')
            date = next((header['value'] for header in headers if header['name'] == 'Date'), 'Unknown Date')
            
            snippet = message.get('snippet', '')
            
            email_data.append({
                "from": from_address,
                "date": date,
                "subject": subject,
                "snippet": snippet
            })
            
        return email_data

    except Exception as error:
        print(f"An error occurred pulling emails: {error}")
        return []

if __name__ == "__main__":
    print("Testing isolated filter script...")
    emails = list_recent_emails(max_results=3)
    print(f"Found {len(emails)} matching emails.")
