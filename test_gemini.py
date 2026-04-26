import os
import requests
import json

api_key = os.getenv('GEMINI_API_KEY')
url = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}
payload = {
    "model": "gemini-3.0-flash-preview",
    "messages": [{"role": "user", "content": "Hello"}]
}
response = requests.post(url, headers=headers, json=payload)
print(f"Status: {response.status_code}")
print(f"Response: {response.text}")
