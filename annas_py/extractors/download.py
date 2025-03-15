from html import unescape as html_unescape
from urllib.parse import urljoin

from bs4 import NavigableString

from ..models.data import URL, Download
from ..utils import html_parser
from . import BASE_URL
from .generic import extract_file_info, extract_publish_info


def remove_search_icon(s: str) -> str:
    return s.replace("🔍", "").strip()


def get_information(id: str) -> Download:
    soup = html_parser(urljoin(BASE_URL, f"md5/{id}"))

    def get_text(tag: str, cls: str):
        return soup.find(tag, class_=cls).text

    title = remove_search_icon(get_text("div", "text-3xl font-bold"))
    authors = remove_search_icon(get_text("div", "italic"))
    description = get_text("div", "js-md5-top-box-description")
    thumbnail = soup.find("img").get("src") or None

    publisher, publish_date = extract_publish_info(get_text("div", "text-md"))

    file_info = extract_file_info(get_text("div", "text-sm text-gray-500"))

    # 提取下载链接并去重
    raw_links = [
        parse_link(container)
        for container in soup.find_all("a", class_="js-download-link")
    ]
    download_links = list({(link.title, link.url): link for link in raw_links if link}.values())


    return Download(
        title=html_unescape(title),
        description=html_unescape(description[1:-1]),
        authors=html_unescape(authors),
        file_info=file_info,
        urls=download_links,
        thumbnail=thumbnail,
        publisher=html_unescape(publisher) if publisher else None,
        publish_date=publish_date,
    )


def parse_link(link: NavigableString) -> URL | None:
    url = link.get("href")
    if url == "/datasets":
        return None
    elif url[0] == "/":
        url = urljoin(BASE_URL, url[1:])
    return URL(html_unescape(link.text), url)
