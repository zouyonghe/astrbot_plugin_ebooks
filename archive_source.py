import asyncio
import os
import re
from urllib.parse import unquote, urlparse

import aiofiles
import aiohttp
from astrbot.api.all import Plain, Image, Node, Nodes, File, logger

from data.plugins.astrbot_plugin_ebooks.utils import (
    download_and_convert_to_base64,
    is_base64_image,
    is_url_accessible,
    parse_html_to_text,
    is_valid_archive_book_url,
    truncate_filename,
)


class ArchiveSource:
    def __init__(self, config, proxy: str, max_results: int, temp_path: str):
        self.config = config
        self.proxy = proxy
        self.max_results = max_results
        self.temp_path = temp_path

    async def _search_archive_books(self, query: str, limit: int = 20):
        base_search_url = "https://archive.org/advancedsearch.php"
        base_metadata_url = "https://archive.org/metadata/"
        formats = ("pdf", "epub")

        params = {
            "q": f'title:"{query}" mediatype:texts',
            "fl[]": "identifier,title",
            "sort[]": "downloads desc",
            "rows": limit + 10,
            "page": 1,
            "output": "json",
        }

        async with aiohttp.ClientSession() as session:
            response = await session.get(base_search_url, params=params, proxy=self.proxy)
            if response.status != 200:
                logger.error(f"[archive.org] Error during search: archive.org API returned status code {response.status}")
                return []

            result_data = await response.json()
            docs = result_data.get("response", {}).get("docs", [])
            if not docs:
                logger.info("[archive.org] 未找到匹配的电子书。")
                return []

            tasks = [self._fetch_metadata(session, base_metadata_url + doc["identifier"], formats) for doc in docs]
            metadata_results = await asyncio.gather(*tasks)

            books = [
                {
                    "title": doc.get("title"),
                    "cover": metadata.get("cover"),
                    "authors": metadata.get("authors"),
                    "language": metadata.get("language"),
                    "year": metadata.get("year"),
                    "publisher": metadata.get("publisher"),
                    "download_url": metadata.get("download_url"),
                    "description": metadata.get("description"),
                }
                for doc, metadata in zip(docs, metadata_results)
                if metadata
            ][:limit]
            return books

    async def _fetch_metadata(self, session: aiohttp.ClientSession, url: str, formats: tuple) -> dict:
        try:
            response = await session.get(url, proxy=self.proxy)
            if response.status != 200:
                logger.error(f"[archive.org] Error retrieving Metadata: Status code {response.status}")
                return {}

            book_detail = await response.json()

            identifier = book_detail.get("metadata", {}).get("identifier", None)
            if not identifier:
                return {}
            files = book_detail.get("files", [])
            description = book_detail.get("metadata", {}).get("description", "无简介")
            authors = book_detail.get("metadata", {}).get("creator", "未知")
            language = book_detail.get("metadata", {}).get("language", "未知")
            year = (
                book_detail.get("metadata", {}).get("publicdate", "未知")[:4]
                if book_detail.get("metadata", {}).get("publicdate", "未知") != "未知"
                else "未知"
            )
            publisher = book_detail.get("metadata", {}).get("publisher", "未知")

            if isinstance(description, str):
                description = parse_html_to_text(description)
                description = description[:150] + "..." if len(description) > 150 else description
            else:
                description = "无简介"

            for file in files:
                if any(file.get("name", "").lower().endswith(fmt) for fmt in formats):
                    return {
                        "cover": f"https://archive.org/services/img/{identifier}",
                        "authors": authors,
                        "year": year,
                        "publisher": publisher,
                        "language": language,
                        "description": description,
                        "download_url": f"https://archive.org/download/{identifier}/{file['name']}",
                    }
        except Exception as e:
            logger.error(f"[archive.org] 获取 Metadata 数据时发生错误: {e}")
        return {}

    async def _cleanup_file(self, path: str):
        try:
            await asyncio.sleep(5)
            os.remove(path)
        except Exception:
            pass

    async def search_nodes(self, event, query: str = None, limit: str = ""):
        if not self.config.get("enable_archive", False):
            return "[archive.org] 功能未启用。"

        if not query:
            return "[archive.org] 请提供电子书关键词以进行搜索。"

        if not await is_url_accessible("https://archive.org", proxy=self.proxy):
            return "[archive.org] 无法连接到 archive.org。"

        limit = int(limit) if str(limit).isdigit() else self.max_results
        if limit < 1:
            return "[archive.org] 请确认搜索返回结果数量在 1-60 之间。"
        if limit > 60:
            limit = 60

        try:
            logger.info(f"[archive.org] Received books search query: {query}, limit: {limit}")
            results = await self._search_archive_books(query, limit)

            if not results:
                return "[archive.org] 未找到匹配的电子书。"

            async def construct_node(book):
                chain = [Plain(f"{book.get('title', '未知')}")]

                if book.get("cover"):
                    base64_image = await download_and_convert_to_base64(book.get("cover"), proxy=self.proxy)
                    if base64_image and is_base64_image(base64_image):
                        chain.append(Image.fromBase64(base64_image))
                    else:
                        chain.append(Plain("\n"))
                else:
                    chain.append(Plain("\n"))

                chain.append(Plain(f"作者: {book.get('authors', '未知')}\n"))
                chain.append(Plain(f"年份: {book.get('year', '未知')}\n"))
                chain.append(Plain(f"出版社: {book.get('publisher', '未知')}\n"))
                chain.append(Plain(f"语言: {book.get('language', '未知')}\n"))
                chain.append(Plain(f"简介: {book.get('description', '无简介')}\n"))
                chain.append(Plain(f"链接(用于下载): {book.get('download_url', '未知')}"))

                return Node(
                    uin=event.get_self_id(),
                    name="archive.org",
                    content=chain,
                )

            tasks = [construct_node(book) for book in results]
            return await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"[archive.org] Error processing archive.org search request: {e}")
            return "[archive.org] 搜索电子书时发生错误，请稍后再试。"

    async def download(self, event, book_url: str = None):
        if not self.config.get("enable_archive", False):
            return [event.plain_result("[archive.org] 功能未启用。")]

        if not is_valid_archive_book_url(book_url):
            return [event.plain_result("[archive.org] 请提供有效的下载链接。")]

        if not await is_url_accessible("https://archive.org", proxy=self.proxy):
            return [event.plain_result("[archive.org] 无法连接到 archive.org")]

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(book_url, allow_redirects=True, proxy=self.proxy, timeout=300) as response:
                    if response.status == 200:
                        ebook_url = str(response.url)
                        logger.debug(f"[archive.org] 跳转后的下载地址: {ebook_url}")

                        content_disposition = response.headers.get("Content-Disposition", "")
                        book_name = None

                        if content_disposition:
                            book_name_match = re.search(r'filename\*=(?:UTF-8\'\')?([^;]+)', content_disposition)
                            if book_name_match:
                                book_name = unquote(book_name_match.group(1))
                            else:
                                book_name_match = re.search(r'filename=["\']?([^;\']+)["\']?', content_disposition)
                                if book_name_match:
                                    book_name = book_name_match.group(1)

                        if not book_name or book_name.strip() == "":
                            parsed_url = urlparse(ebook_url)
                            book_name = os.path.basename(parsed_url.path) or "unknown_book"

                        book_name = truncate_filename(book_name)
                        temp_file_path = os.path.join(self.temp_path, book_name)

                        async with aiofiles.open(temp_file_path, "wb") as temp_file:
                            await temp_file.write(await response.read())

                        logger.info(f"[archive.org] 文件已下载并保存到临时目录：{temp_file_path}")
                        file = File(name=book_name, file=temp_file_path)
                        asyncio.create_task(self._cleanup_file(temp_file_path))
                        return [event.chain_result([file])]
                    return [event.plain_result(f"[archive.org] 无法下载电子书，状态码: {response.status}")]
        except Exception as e:
            logger.error(f"[archive.org] 下载失败: {e}")
            return [event.plain_result(f"[archive.org] 下载电子书时发生错误，请稍后再试。")]
