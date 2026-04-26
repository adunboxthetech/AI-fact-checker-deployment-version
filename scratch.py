import sys
from api.core import extract_content_from_url, _extract_reddit
url = "https://www.reddit.com/r/IndiaTech/comments/1svx5pe/the_fall_of_chegg/"
print(_extract_reddit(url))
print(extract_content_from_url(url))
