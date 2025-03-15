from html import unescape as html_unescape
from urllib.parse import urljoin

from bs4 import NavigableString

from ..models.args import FileType, Language, OrderBy
from ..models.data import SearchResult
from ..utils import html_parser
from . import BASE_URL
from .generic import extract_file_info, extract_publish_info


def search(
    query: str,
    language: Language = Language.ANY,
    file_type: FileType = FileType.ANY,
    order_by: OrderBy = OrderBy.MOST_RELEVANT,
) -> list[SearchResult]:
    if not query.strip():
        raise ValueError("query can not be empty")
    params = {
        "q": query,
        "lang": language.value,
        "ext": file_type.value,
        "sort": order_by.value,
    }
    soup = html_parser(urljoin(BASE_URL, "search"), params)
    raw_results = soup.find_all("a", class_="js-vim-focus")
    return list(filter(lambda i: i is not None, map(parse_result, raw_results)))


def parse_result(soup: NavigableString) -> SearchResult | None:
    def get_text(selector: str = "") -> str:
        return soup.select_one(selector).text
    try:
        title = get_text("h3").strip()
    except AttributeError:
        return None
    authors = get_text("div:nth-child(2) > div:nth-child(4)")
    publisher, publish_date = extract_publish_info(get_text("div:nth-child(2) > div:nth-child(3)"))
    file_info = extract_file_info(get_text("div:nth-child(2) > div:nth-child(1)"))

    thumbnail = soup.find("img")
    thumbnail = thumbnail.get("src") if thumbnail else None  # 如果找到，则获取 src 属性，否则为 None
    id = soup.get("href").split("md5/")[-1]

    return SearchResult(
        id=id,
        title=html_unescape(title),
        authors=html_unescape(authors),
        file_info=file_info,
        thumbnail=thumbnail,
        publisher=html_unescape(publisher) if publisher else None,
        publish_date=publish_date,
    )
