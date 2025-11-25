import asyncio
import os
from typing import Union

from astrbot.api.all import *
from astrbot.api.event.filter import *

from data.plugins.astrbot_plugin_ebooks.annas_source import AnnasSource
from data.plugins.astrbot_plugin_ebooks.archive_source import ArchiveSource
from data.plugins.astrbot_plugin_ebooks.calibre_source import CalibreSource
from data.plugins.astrbot_plugin_ebooks.liber3_source import Liber3Source
from data.plugins.astrbot_plugin_ebooks.utils import (
    is_valid_annas_book_id,
    is_valid_archive_book_url,
    is_valid_calibre_book_url,
    is_valid_liber3_book_id,
    to_event_results,
)
from data.plugins.astrbot_plugin_ebooks.zlib_source import ZlibSource


@register("ebooks", "buding", "一个功能强大的电子书搜索和下载插件", "1.1.3", "https://github.com/zouyonghe/astrbot_plugin_ebooks")
class ebooks(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.proxy = os.environ.get("https_proxy")
        self.TEMP_PATH = os.path.abspath("data/temp")
        os.makedirs(self.TEMP_PATH, exist_ok=True)
        self.max_results = self.config.get("max_results", 20)
        if not isinstance(self.max_results, int) or not (1 <= self.max_results <= 100):
            logger.warning("[ebooks] max_results 配置无效，已重置为 20")
            self.max_results = 20

        if self.config.get("enable_calibre", False) and not self.config.get("calibre_web_url", "").strip():
            self.config["enable_calibre"] = False
            self.config.save_config()
            logger.info("[ebooks] 未设置 Calibre-Web URL，禁用该平台。")

        self.calibre_source = CalibreSource(self.config, self.proxy, self.max_results)
        self.liber3_source = Liber3Source(self.config, self.proxy, self.max_results)
        self.archive_source = ArchiveSource(self.config, self.proxy, self.max_results, self.TEMP_PATH)
        self.zlib_source = ZlibSource(self.config, self.proxy, self.max_results, self.TEMP_PATH)
        self.annas_source = AnnasSource(self.config, self.proxy, self.max_results)

    async def terminate(self):
        await asyncio.gather(
            self.calibre_source.close(),
            self.liber3_source.close(),
            self.archive_source.close(),
            self.zlib_source.terminate(),
        )

    async def _yield_download_results(self, results):
        for item in results:
            yield item

    @command_group("calibre")
    def calibre(self):
        pass

    @calibre.command("search")
    async def search_calibre(self, event: AstrMessageEvent, query: str, limit: str = ""):
        result = await self.calibre_source.search_nodes(event, query, limit)
        for response in to_event_results(event, "Calibre-Web", result):
            yield response

    @calibre.command("download")
    async def download_calibre(self, event: AstrMessageEvent, book_url: str = None):
        results = await self.calibre_source.download(event, book_url)
        async for response in self._yield_download_results(results):
            yield response

    @calibre.command("recommend")
    async def recommend_calibre(self, event: AstrMessageEvent, n: int):
        results = await self.calibre_source.recommend(event, n)
        async for response in self._yield_download_results(results):
            yield response

    # @llm_tool("search_calibre_books")
    async def search_calibre_books(self, event: AstrMessageEvent, query: str):
        """Search books by keywords or title through Calibre-Web.
        When to use:
            Use this method to search for books in the Calibre-Web catalog when the user knows the title or keyword.
            This method cannot be used for downloading books and should only be used for searching purposes.

        Args:
            query (string): The search keyword or title to find books in the Calibre-Web catalog.
        """
        async for result in self.search_calibre(event, query):
            yield result

    # @llm_tool("download_calibre_book")
    async def download_calibre_book(self, event: AstrMessageEvent, book_url: str):
        """Download a book by a precise name or URL through Calibre-Web.
        When to use:
            Use this method to download a specific book by its name or when a direct download link is available.
    
        Args:
            book_url (string): The book name (exact match) or the URL of the book link.

        """
        async for result in self.download_calibre(event, book_url):
            yield result

    @command_group("liber3")
    def liber3(self):
        pass

    @liber3.command("search")
    async def search_liber3(self, event: AstrMessageEvent, query: str = None, limit: str = ""):
        result = await self.liber3_source.search_nodes(event, query, limit)
        for response in to_event_results(event, "Liber3", result):
            yield response

    @liber3.command("download")
    async def download_liber3(self, event: AstrMessageEvent, book_id: str = None):
        results = await self.liber3_source.download(event, book_id)
        async for response in self._yield_download_results(results):
            yield response

    # @llm_tool("search_liber3_books")
    async def search_liber3_books(self, event: AstrMessageEvent, query: str):
        """Search for books using Liber3 API and return a detailed result list.

        When to use:
            Invoke this tool to locate books based on keywords or titles from Liber3's library.

        Args:
            query (string): The keyword or title to search for books.
        """
        async for result in self.search_liber3(event, query):
            yield result

    # @llm_tool("download_liber3_book")
    async def download_liber3_book(self, event: AstrMessageEvent, book_id: str):
        """Download a book using Liber3's API via its unique ID.

        When to use:
            This tool allows you to retrieve a Liber3 book using the unique ID and download it.

        Args:
            book_id (string): A valid Liber3 book ID required to download a book.
        """
        async for result in self.download_liber3(event, book_id):
            yield result

    @command_group("archive")
    def archive(self):
        pass

    @archive.command("search")
    async def search_archive(self, event: AstrMessageEvent, query: str = None, limit: str = ""):
        result = await self.archive_source.search_nodes(event, query, limit)
        for response in to_event_results(event, "archive.org", result):
            yield response

    @archive.command("download")
    async def download_archive(self, event: AstrMessageEvent, book_url: str = None):
        results = await self.archive_source.download(event, book_url)
        async for response in self._yield_download_results(results):
            yield response

    # @llm_tool("search_archive_books")
    async def search_archive_books(self, event: AstrMessageEvent, query: str):
        """Search for eBooks using the archive.org API.
    
        When to use:
            Utilize this method to search books available in supported formats (such as PDF or EPUB) on the archive.org API platform.
    
        Args:
            query (string): The keywords or title to perform the search.
        """
        async for result in self.search_archive(event, query):
            yield result

    # @llm_tool("download_archive_book")
    async def download_archive_book(self, event: AstrMessageEvent, download_url: str):
        """Download an eBook from the archive.org API using its download URL.
    
        When to use:
            Use this method to download a specific book from the archive.org platform using the book's provided download link.
    
        Args:
            download_url (string): A valid and supported archive.org book download URL.
        """
        async for result in self.download_archive(event, download_url):
            yield result

    @command_group("zlib")
    def zlib(self):
        pass

    @zlib.command("search")
    async def search_zlib(self, event: AstrMessageEvent, query: str = None, limit: str = ""):
        result = await self.zlib_source.search_nodes(event, query, limit)
        for response in to_event_results(event, "Z-Library", result):
            yield response

    @zlib.command("download")
    async def download_zlib(self, event: AstrMessageEvent, book_id: str = None, book_hash: Union[str, int] = None):
        results = await self.zlib_source.download(event, book_id, book_hash)
        async for response in self._yield_download_results(results):
            yield response

    # @llm_tool("search_zlib_books")
    async def search_zlib_books(self, event: AstrMessageEvent, query: str):
        """Search Zlibrary for books using given keywords.

        When to use:
            Use this method to locate books by keywords or title in Z-Library's database.

        Args:
            query (string): The search term to perform the lookup.
        """
        async for result in self.search_zlib(event, query):
            yield result

    # @llm_tool("download_zlib_book")
    async def download_zlib_book(self, event: AstrMessageEvent, book_id: str, book_hash: str):
        """Download a book from Z-Library using its book ID and hash.
    
        When to use:
            Use this method for downloading books from Zlibrary with the provided ID and hash.
    
        Args:
            book_id (string): The unique identifier for the book.
            book_hash (string): Hash value required to authorize and retrieve the download.
        """
        async for result in self.download_zlib(event, book_id, book_hash):
            yield result

    @command_group("annas")
    def annas(self):
        pass

    @annas.command("search")
    async def search_annas(self, event: AstrMessageEvent, query: str, limit: str = ""):
        result = await self.annas_source.search_nodes(event, query, limit)
        for response in to_event_results(event, "anna's archive", result):
            yield response

    @annas.command("download")
    async def download_annas(self, event: AstrMessageEvent, book_id: str = None):
        results = await self.annas_source.download(event, book_id)
        async for response in self._yield_download_results(results):
            yield response

    @command_group("ebooks")
    def ebooks(self):
        pass

    @ebooks.command("help")
    async def show_help(self, event: AstrMessageEvent):
        help_msg = [
            "📚 **ebooks 插件使用指南**",
            "",
            "支持通过多平台（Calibre-Web、Liber3、Z-Library、archive.org）搜索、下载电子书。",
            "",
            "---",
            "🔧 **命令列表**:",
            "",
            "- **Calibre-Web**:",
            "  - `/calibre search <关键词> [数量]`：搜索 Calibre-Web 中的电子书。例如：`/calibre search Python 20`。",
            "  - `/calibre download <下载链接/书名>`：通过 Calibre-Web 下载电子书。例如：`/calibre download <URL>`。",
            "  - `/calibre recommend <数量>`：随机推荐指定数量的电子书。",
            "",
            "- **archive.org**:",
            "  - `/archive search <关键词> [数量]`：搜索 archive.org 电子书。例如：`/archive search Python 20`。",
            "  - `/archive download <下载链接>`：通过 archive.org 平台下载电子书。",
            "",
            "- **Z-Library**:",
            "  - `/zlib search <关键词> [数量]`：搜索 Z-Library 的电子书。例如：`/zlib search Python 20`。",
            "  - `/zlib download <ID> <Hash>`：通过 Z-Library 平台下载电子书。",
            "",
            "- **Liber3**:",
            "  - `/liber3 search <关键词> [数量]`：搜索 Liber3 平台上的电子书。例如：`/liber3 search Python 20`。",
            "  - `/liber3 download <ID>`：通过 Liber3 平台下载电子书。",
            "",
            "- **Anna's Archive**:",
            "  - `/annas search <关键词> [数量]`：搜索 Anna's Archive 平台上的电子书。例如：`/annas search Python 20`。",
            "  - `/annas download <ID>`：获取 Anna's Archive 电子书下载链接。",
            "",
            "- **通用命令**:",
            "  - `/ebooks help`：显示当前插件的帮助信息。",
            "  - `/ebooks search <关键词> [数量]`：在所有支持的平台中同时搜索电子书。例如：`/ebooks search Python 20`。",
            "  - `/ebooks download <URL/ID> [Hash]`：通用的电子书下载方式。",
            "",
            "---",
            "📒 **注意事项**:",
            "- `数量` 为可选参数，默认为20，用于限制搜索结果的返回数量，数量超过30会分多个转发发送。",
            "- 下载指令要根据搜索结果，提供有效的 URL、ID 和 Hash 值。",
            "- 推荐功能会从现有书目中随机选择书籍进行展示（目前仅支持Calibre-Web)。",
            "- 目前无法直接从 Anna's Archive 下载电子书。",
            "",
            "---",
            "🌐 **支持平台**:",
            "- Calibre-Web",
            "- Liber3",
            "- Z-Library",
            "- archive.org",
        ]
        yield event.plain_result("\n".join(help_msg))

    @ebooks.command("search")
    async def search_all_platforms(self, event: AstrMessageEvent, query: str = None, limit: str = ""):
        limit = int(limit) if str(limit).isdigit() else int(self.max_results)
        if not query:
            yield event.plain_result("[ebooks] 请提供电子书关键词以进行搜索。")
            return

        if not (1 <= int(limit) <= 50):
            yield event.plain_result("[ebooks] 请确认搜索返回结果数量在 1-100 之间。")
            return

        tasks = []
        if self.config.get("enable_calibre", False):
            tasks.append(("Calibre-Web", self.calibre_source.search_nodes(event, query, limit)))
        if self.config.get("enable_liber3", False):
            tasks.append(("Liber3", self.liber3_source.search_nodes(event, query, limit)))
        if self.config.get("enable_archive", False):
            tasks.append(("archive.org", self.archive_source.search_nodes(event, query, limit)))
        if self.config.get("enable_zlib", False):
            tasks.append(("Z-Library", self.zlib_source.search_nodes(event, query, limit)))
        if self.config.get("enable_annas", False):
            tasks.append(("Anna's Archive", self.annas_source.search_nodes(event, query, limit)))

        try:
            search_results = await asyncio.gather(*[task for _, task in tasks])
            named_results = list(zip([name for name, _ in tasks], search_results))
            if self.config.get("enable_merge_forward", False):
                ns = Nodes([])
                for platform_name, platform_results in named_results:
                    if isinstance(platform_results, str):
                        node = Node(
                            uin=event.get_self_id(),
                            name="ebooks",
                            content=[Plain(platform_results)],
                        )
                        ns.nodes.append(node)
                        continue
                    for i in range(0, len(platform_results), 30):
                        chunk_results = platform_results[i:i + 30]
                        node = Node(
                            uin=event.get_self_id(),
                            name="ebooks",
                            content=chunk_results,
                        )
                        ns.nodes.append(node)
                yield event.chain_result([ns])
            else:
                for platform_name, platform_results in named_results:
                    for response in to_event_results(event, platform_name, platform_results):
                        yield response
        except Exception as e:
            logger.error(f"[ebooks] Error during multi-platform search: {e}")
            yield event.plain_result(f"[ebooks] 搜索电子书时发生错误，请稍后再试。")

    @ebooks.command("download")
    async def download_all_platforms(self, event: AstrMessageEvent, arg1: str = None, arg2: str = None):
        if not arg1:
            yield event.plain_result("[ebooks] 请提供有效的下载链接、ID 或参数！")
            return

        try:
            if arg1 and arg2:
                logger.info("[ebooks] 检测到 Z-Library ID 和 Hash，开始下载...")
                async for result in self.download_zlib(event, arg1, arg2):
                    yield result
                return

            if is_valid_calibre_book_url(arg1):
                logger.info("[ebooks] 检测到 Calibre-Web 链接，开始下载...")
                async for result in self.download_calibre(event, arg1):
                    yield result
                return

            if is_valid_archive_book_url(arg1):
                logger.info("[ebooks] 检测到 archive.org 链接，开始下载...")
                async for result in self.download_archive(event, arg1):
                    yield result
                return

            if is_valid_liber3_book_id(arg1):
                logger.info("[ebooks] ⏳ 检测到 Liber3 ID，开始下载...")
                async for result in self.download_liber3(event, arg1):
                    yield result
                return

            if is_valid_annas_book_id(arg1):
                logger.info("[ebooks] ⏳ 检测到 Annas Archive ID，开始下载...")
                async for result in self.download_annas(event, arg1):
                    yield result
                return

            yield event.plain_result(
                "[ebooks] 未识别的输入格式，请提供以下格式之一：\n"
                "- Calibre-Web 下载链接\n"
                "- archive.org 下载链接\n"
                "- Liber3/Annas Archive 32位 ID\n"
                "- Z-Library 的 ID 和 Hash"
            )
        except Exception:
            yield event.plain_result(f"[ebooks] 下载电子书时发生错误，请稍后再试。")

    @llm_tool("search_ebooks")
    async def search_ebooks(self, event: AstrMessageEvent, query: str):
        async for result in self.search_all_platforms(event, query, limit="20"):
            yield result

    @llm_tool("download_ebook")
    async def download_ebook(self, event: AstrMessageEvent, arg1: str, arg2: str = None):
        async for result in self.download_all_platforms(event, arg1, arg2):
            yield result
