import asyncio

from astrbot.api.all import Plain, Image, Node, logger

from data.plugins.astrbot_plugin_ebooks.annas_py import get_information as get_annas_information
from data.plugins.astrbot_plugin_ebooks.annas_py import search as annas_search
from data.plugins.astrbot_plugin_ebooks.annas_py.models.args import Language
from data.plugins.astrbot_plugin_ebooks.utils import (
    download_and_convert_to_base64,
    is_base64_image,
    is_url_accessible,
    is_valid_annas_book_id,
)


class AnnasSource:
    def __init__(self, config, proxy: str, max_results: int):
        self.config = config
        self.proxy = proxy
        self.max_results = max_results

    async def search_nodes(self, event, query: str, limit: str = ""):
        if not self.config.get("enable_annas", False):
            return "[Anna's Archive] 功能未启用。"

        if not await is_url_accessible("https://annas-archive.org", proxy=self.proxy):
            return "[Anna's Archive] 无法连接到 Anna's Archive。"

        if not query:
            return "[Anna's Archive] 请提供电子书关键词以进行搜索。"

        limit = int(limit) if str(limit).isdigit() else self.max_results
        if limit < 1:
            return "[Anna's Archive] 请确认搜索返回结果数量在 1-60 之间。"
        if limit > 60:
            limit = 60

        try:
            logger.info(f"[Anna's Archive] Received books search query: {query}, limit: {limit}")
            results = annas_search(query, Language.ZH)
            if not results or len(results) == 0:
                return "[Anna's Archive] 未找到匹配的电子书。"

            books = results[:limit]

            async def construct_node(book):
                chain = [Plain(f"{book.title}\n")]

                if book.thumbnail:
                    base64_image = await download_and_convert_to_base64(book.thumbnail, proxy=self.proxy)
                    if base64_image and is_base64_image(base64_image):
                        chain.append(Image.fromBase64(base64_image))
                    else:
                        chain.append(Plain("\n"))
                else:
                    chain.append(Plain("\n"))

                chain.append(Plain(f"作者: {book.authors or '未知'}\n"))
                chain.append(Plain(f"出版社: {book.publisher or '未知'}\n"))
                chain.append(Plain(f"年份: {book.publish_date or '未知'}\n"))
                language = book.file_info.language if book.file_info else "未知"
                chain.append(Plain(f"语言: {language}\n"))
                extension = book.file_info.extension if book.file_info else "未知"
                chain.append(Plain(f"格式: {extension}\n"))
                chain.append(Plain(f"ID: A{book.id}"))

                return Node(
                    uin=event.get_self_id(),
                    name="Anna's Archive",
                    content=chain,
                )

            tasks = [construct_node(book) for book in books]
            return await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"[Anna's Archive] Error during book search: {e}")
            return "[Anna's Archive] 搜索电子书时发生错误，请稍后再试。"

    async def download(self, event, book_id: str = None):
        if not self.config.get("enable_annas", False):
            return [event.plain_result("[Anna's Archive] 功能未启用。")]

        if not is_valid_annas_book_id(book_id):
            return [event.plain_result("[Anna's Archive] 请提供有效的书籍 ID。")]

        try:
            book_id = book_id.lstrip("A")
            book_info = get_annas_information(book_id)
            urls = book_info.urls

            if not urls:
                return [event.plain_result("[Anna's Archive] 未找到任何下载链接！")]

            chain = [Plain("Anna's Archive\n目前无法直接下载电子书，可以通过访问下列链接手动下载：")]

            fast_links = [url for url in urls if "Fast Partner Server" in url.title]
            if fast_links:
                chain.append(Plain("\n快速链接（需要付费）：\n"))
                for index, url in enumerate(fast_links, 1):
                    chain.append(Plain(f"{index}. {url.url}\n"))

            slow_links = [url for url in urls if "Slow Partner Server" in url.title]
            if slow_links:
                chain.append(Plain("\n慢速链接（需要等待）：\n"))
                for index, url in enumerate(slow_links, 1):
                    chain.append(Plain(f"{index}. {url.url}\n"))

            other_links = [
                url for url in urls if "Fast Partner Server" not in url.title and "Slow Partner Server" not in url.title
            ]
            if other_links:
                chain.append(Plain("\n第三方链接：\n"))
                for index, url in enumerate(other_links, 1):
                    chain.append(Plain(f"{index}. {url.url}\n"))

            node = Node(uin=event.get_self_id(), name="Anna's Archive", content=chain)
            return [event.chain_result([node])]
        except Exception as e:
            logger.error(f"[Anna's Archive] 下载失败：{e}")
            return [event.plain_result(f"[Anna's Archive] 下载电子书时发生错误，请稍后再试：{e}")]
