import google.auth
from google import genai
import sys

try:
    scopes = ['https://www.googleapis.com/auth/generative-language.retriever', 'https://www.googleapis.com/auth/cloud-platform']
    creds, project = google.auth.default(scopes=scopes)
    
    # Try different ways to initialize client with credentials
    try:
        client = genai.Client(http_options={'credentials': creds})
        print('SUCCESS: http_options=credentials')
        sys.exit(0)
    except Exception as e:
        print(f'Failed http_options: {e}')
        
    try:
        client = genai.Client(credentials=creds)
        print('SUCCESS: credentials=creds')
        sys.exit(0)
    except Exception as e:
        print(f'Failed credentials: {e}')

except Exception as e:
    print(f'ADC Error: {e}')
    sys.exit(1)
