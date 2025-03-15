from bs4 import BeautifulSoup, NavigableString
from requests import get


class HTTPFailed(Exception):
    pass


def html_parser(url: str, params: dict = {}) -> NavigableString:
    params = dict(filter(lambda i: i[1], params.items()))
    response = get(url, params=params)
    if response.status_code >= 400:
        raise HTTPFailed(f"server returned http status {response.status_code}")
    # Uncomment code that would be dynamically rendered by JavaScript
    html = response.text.replace("<!--", "").replace("-->", "")
    soup = BeautifulSoup(html, "lxml")
    return soup
