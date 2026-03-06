import os
import json
import requests
from google.oauth2.credentials import Credentials
from google import genai

# gemini-cli constants
OAUTH_CLIENT_ID = '681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com'
# Usually desktop apps don't need a client secret, or it's a known string. We'll try without or empty first.
OAUTH_CLIENT_SECRET = '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' # Often used for desktop apps or empty. Actually let's try just None or empty string

CRED_FILE = os.path.expanduser('~/.gemini/oauth_creds.json')

def load_credentials():
    with open(CRED_FILE, 'r') as f:
        data = json.load(f)
    
    # Needs refresh token, client_id, client_secret, token_uri
    creds = Credentials(
        token=data.get('access_token'),
        refresh_token=data.get('refresh_token'),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=OAUTH_CLIENT_ID,
        client_secret=OAUTH_CLIENT_SECRET,
        scopes=['https://www.googleapis.com/auth/cloud-platform', 'https://www.googleapis.com/auth/userinfo.profile', 'https://www.googleapis.com/auth/userinfo.email', 'openid']
    )
    return creds

if __name__ == "__main__":
    try:
        creds = load_credentials()
        # Force a refresh to see if it works
        import google.auth.transport.requests
        request = google.auth.transport.requests.Request()
        creds.refresh(request)
        print("Successfully refreshed credentials!")
        
        # Test Gemini Client
        client = genai.Client(api_key="DUMMY_KEY_TO_BYPASS_VALIDATION", http_options={'headers': {'Authorization': f'Bearer {creds.token}'}})
        models = client.models.list()
        for m in models:
            print(m.name)
            break
        print("Successfully called Gemini API with OAuth!")
    except Exception as e:
        print(f"Failed: {e}")
