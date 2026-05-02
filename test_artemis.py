import os

from dotenv import load_dotenv

load_dotenv()
print("GEMINI_API_KEY set:", bool(os.getenv("GEMINI_API_KEY")))
from api.core import fact_check_text_input

res_text, status = fact_check_text_input(
    "Did NASA do the Artemis 2 mission a few days ago?"
)
print(f"Status: {status}")
print(f"Result: {res_text}")
