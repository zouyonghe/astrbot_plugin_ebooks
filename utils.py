import base64
import io
import os
import re
from typing import Union

import aiohttp
from astrbot.api.all import Node, Nodes
from PIL import Image as Img
from aiohttp import ClientPayloadError
from bs4 import BeautifulSoup


async def is_url_accessible(url: str, proxy: str = None) -> bool:
    """Check whether a URL is reachable with a short HEAD request."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(
                url,
                timeout=5,
                proxy=proxy,
                allow_redirects=True,
            ) as response:
                return response.status == 200
    except Exception:
        return False


async def download_and_convert_to_base64(cover_url: str, proxy: str = None):
    """Fetch an image and convert it to base64 (handles HTML indirection)."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(cover_url, proxy=proxy) as response:
                if response.status != 200:
                    return None

                content_type = response.headers.get("Content-Type", "").lower()
                if "html" in content_type:
                    html_content = await response.text()
                    soup = BeautifulSoup(html_content, "html.parser")
                    img_tag = soup.find("meta", attrs={"property": "og:image"})
                    if img_tag:
                        return await download_and_convert_to_base64(
                            img_tag.get("content"),
                            proxy=proxy,
                        )
                    return None

                content = await response.read()
                base64_data = base64.b64encode(content).decode("utf-8")
                return base64_data
    except ClientPayloadError:
        if "content" in locals():
            base64_data = base64.b64encode(content).decode("utf-8")
            if is_base64_image(base64_data):
                return base64_data
        return None
    except Exception:
        return None


def is_base64_image(base64_data: str) -> bool:
    """Validate that the base64 data represents an image."""
    try:
        image_data = base64.b64decode(base64_data)
        image = Img.open(io.BytesIO(image_data))
        image.verify()
        return True
    except Exception:
        return False


def truncate_filename(filename: str, max_length: int = 100):
    """Truncate long filenames while keeping the extension."""
    base, ext = os.path.splitext(filename)
    if len(filename.encode("utf-8")) > max_length:
        truncated = base[: max_length - len(ext.encode("utf-8")) - 7] + " <省略>"
        return f"{truncated}{ext}"
    return filename


def is_valid_calibre_book_url(book_url: str) -> bool:
    """检测电子书下载链接格式是否合法"""
    if not book_url:
        return False
    pattern = re.compile(r"^https?://.+/.+$")
    if not pattern.match(book_url):
        return False
    if "/opds/download/" not in book_url:
        return False
    return True


def is_html(content):
    """Determine whether a string is in HTML format."""
    if not isinstance(content, str):
        return False
    return bool(re.search(r"<[^>]+>", content))


def parse_html_to_text(html_content: str):
    """Parse HTML content into plain text."""
    soup = BeautifulSoup(html_content, "html.parser")
    return soup.get_text().strip()


def is_valid_zlib_book_id(book_id: str) -> bool:
    """检测 zlib ID 是否为纯数字"""
    if not book_id:
        return False
    return str(book_id).isdigit()


def is_valid_zlib_book_hash(hash: Union[str, int]) -> bool:
    """检测 zlib Hash 是否为 6 位十六进制"""
    if not hash:
        return False
    if isinstance(hash, int):
        hash = str(hash)
    pattern = re.compile(r"^[a-f0-9]{6}$", re.IGNORECASE)
    return bool(pattern.match(hash))


def is_valid_liber3_book_id(book_id: str) -> bool:
    """检测 Liber3 的 book_id 是否有效"""
    if not book_id:
        return False
    pattern = re.compile(r"^L[a-fA-F0-9]{32}$")
    return bool(pattern.match(book_id))


def is_valid_annas_book_id(book_id: str) -> bool:
    """检测 Anna's Archive 的 book_id 是否有效"""
    if not book_id:
        return False
    pattern = re.compile(r"^A[a-fA-F0-9]{32}$")
    return bool(pattern.match(book_id))


def is_valid_archive_book_url(book_url: str) -> bool:
    """检测 archive.org 下载链接格式是否合法"""
    if not book_url:
        return False
    pattern = re.compile(r"^https://archive\\.org/download/[^/]+/[^/]+$")
    return bool(pattern.match(book_url))


class SharedSession:
    """Provide a reusable aiohttp session per source."""

    def __init__(self, proxy: str = None):
        self.proxy = proxy
        self._session: aiohttp.ClientSession = None

    async def get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close_session(self):
        if self._session and not self._session.closed:
            await self._session.close()


def to_event_results(event, platform_name: str, results, chunk_size: int = 30):
    """Convert search results to event results with chunked forwarding."""
    if isinstance(results, str):
        return [event.plain_result(results)]
    if isinstance(results, list):
        if len(results) <= chunk_size:
            ns = Nodes(results)
            return [event.chain_result([ns])]
        ns = Nodes([])
        for i in range(0, len(results), chunk_size):
            chunk_results = results[i : i + chunk_size]
            node = Node(
                uin=event.get_self_id(),
                name=platform_name,
                content=chunk_results,
            )
            ns.nodes.append(node)
        return [event.chain_result([ns])]
    raise ValueError("Unknown result type.")
