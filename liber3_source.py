import asyncio
from typing import Optional

import aiohttp
from astrbot.api.all import Plain, Node, Nodes, File, logger

from data.plugins.astrbot_plugin_ebooks.utils import (
    SharedSession,
    is_valid_liber3_book_id,
)


class Liber3Source(SharedSession):
    def __init__(self, config, proxy: str, max_results: int):
        super().__init__(proxy)
        self.config = config
        self.max_results = max_results

    async def _get_liber3_book_details(self, book_ids: list) -> Optional[dict]:
        detail_url = "https://lgate.glitternode.ru/v1/book"
        headers = {"Content-Type": "application/json"}
        payload = {"book_ids": book_ids}

        try:
            session = await self.get_session()
            async with session.post(detail_url, headers=headers, json=payload, proxy=self.proxy) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("data", {}).get("book", {})
                logger.error(f"[Liber3] Error during detail request: Status code {response.status}")
        except aiohttp.ClientError as e:
            logger.error(f"[Liber3] HTTP client error: {e}")
        except Exception as e:
            logger.error(f"[Liber3] 发生意外错误: {e}")
        return None

    async def _search_liber3_books_with_details(self, word: str, limit: int = 50) -> Optional[dict]:
        search_url = "https://lgate.glitternode.ru/v1/searchV2"
        headers = {"Content-Type": "application/json"}
        payload = {"address": "", "word": word}

        try:
            session = await self.get_session()
            async with session.post(search_url, headers=headers, json=payload, proxy=self.proxy) as response:
                if response.status == 200:
                    data = await response.json()
                    book_data = data["data"].get("book", [])
                    if not book_data:
                        logger.info("[Liber3] 未找到匹配的电子书。")
                        return None

                    book_ids = [item.get("id") for item in book_data[:limit]]
                    if not book_ids:
                        logger.info("[Liber3] 未能提取电子书 ID。")
                        return None

                    detailed_books = await self._get_liber3_book_details(book_ids)
                    if not detailed_books:
                        logger.info("[Liber3] 未获取电子书详细信息。")
                        return None

                    return {"search_results": book_data[:limit], "detailed_books": detailed_books}
                logger.error(f"[Liber3] 请求电子书搜索失败，状态码: {response.status}")
        except aiohttp.ClientError as e:
            logger.error(f"[Liber3] HTTP 客户端错误: {e}")
        except Exception as e:
            logger.error(f"[Liber3] 发生意外错误: {e}")
        return None

    async def search_nodes(self, event, query: str, limit: int):
        if not self.config.get("enable_liber3", False):
            return "[Liber3] 功能未启用。"

        if not query:
            return "[Liber3] 请提供电子书关键词以进行搜索。"

        if not (1 <= limit <= 100):
            return "[Liber3] 请确认搜索返回结果数量在 1-100 之间。"

        try:
            logger.info(f"[Liber3] Received books search query: {query}, limit: {limit}")
            results = await self._search_liber3_books_with_details(query, limit)
            if not results:
                return "[Liber3] 未找到匹配的电子书。"

            search_results = results.get("search_results", [])
            detailed_books = results.get("detailed_books", {})

            async def construct_node(book):
                book_id = book.get("id")
                detail = detailed_books.get(book_id, {}).get("book", {})

                chain = [
                    Plain(f"书名: {book.get('title', '未知')}\n"),
                    Plain(f"作者: {book.get('author', '未知')}\n"),
                    Plain(f"年份: {detail.get('year', '未知')}\n"),
                    Plain(f"出版社: {detail.get('publisher', '未知')}\n"),
                    Plain(f"语言: {detail.get('language', '未知')}\n"),
                    Plain(f"文件大小: {detail.get('filesize', '未知')}\n"),
                    Plain(f"文件类型: {detail.get('extension', '未知')}\n"),
                    Plain(f"ID(用于下载): L{book_id}"),
                ]

                return Node(
                    uin=event.get_self_id(),
                    name="Liber3",
                    content=chain,
                )

            tasks = [construct_node(book) for book in search_results]
            return await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"[Liber3] 搜索失败: {e}")
            return "[Liber3] 搜索电子书时发生错误，请稍后再试。"

    async def download(self, event, book_id: str = None):
        if not self.config.get("enable_liber3", False):
            return [event.plain_result("[Liber3] 功能未启用。")]

        if not is_valid_liber3_book_id(book_id):
            return [event.plain_result("[Liber3] 请提供有效的电子书 ID。")]

        book_id = book_id.lstrip("L")

        book_details = await self._get_liber3_book_details([book_id])
        if not book_details or book_id not in book_details:
            return [event.plain_result("[Liber3] 无法获取电子书元信息，请检查电子书 ID 是否正确。")]

        book_info = book_details[book_id].get("book", {})
        book_name = book_info.get("title", "unknown_book").replace(" ", "_")
        extension = book_info.get("extension", "unknown_extension")
        ipfs_cid = book_info.get("ipfs_cid", "")

        if not ipfs_cid or not extension:
            return [event.plain_result("[Liber3] 电子书信息不足，无法完成下载。")]

        ebook_url = f"https://gateway-ipfs.st/ipfs/{ipfs_cid}?filename={book_name}.{extension}"
        file = File(name=f"{book_name}.{extension}", url=ebook_url)
        return [event.chain_result([file])]

    async def close(self):
        await self.close_session()
