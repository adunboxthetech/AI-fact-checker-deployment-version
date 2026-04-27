from api.core import fact_check_text_input
from dotenv import load_dotenv

load_dotenv()

res_text, status = fact_check_text_input("Who won the super bowl in 2024?")
print(f"Status: {status}")
print(f"Result: {res_text}")
