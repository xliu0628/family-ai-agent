import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

# 1. Define global variables at the top so the whole file can see them
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/calendar'
]
CLIENT_SECRET_FILE = 'client_secret.json'

def main():
    if not os.path.exists(CLIENT_SECRET_FILE):
        print(f"Error: Cannot find '{CLIENT_SECRET_FILE}' in the current directory.")
        return

    print("Starting authentication flow...")
    
    # 2. Use the globally defined variable name here
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    
    # Force offline access type and consent prompt to guarantee a refresh_token
    creds = flow.run_local_server(
        port=8080,
        access_type='offline',
        prompt='consent'
    )
    
    with open('token.json', 'w') as token_file:
        token_file.write(creds.to_json())
        
    print("\nSuccess! 'token.json' has been created in your root folder.")

if __name__ == '__main__':
    main()
