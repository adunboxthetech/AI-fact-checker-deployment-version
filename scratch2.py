import sys
import json
from dotenv import load_dotenv
load_dotenv()
from api.core import fact_check_url_input
url = "https://www.reddit.com/r/IndiaTech/comments/1svx5pe/the_fall_of_chegg/"
print(json.dumps(fact_check_url_input(url), indent=2))
