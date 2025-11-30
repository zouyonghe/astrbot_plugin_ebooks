import asyncio
import os
from typing import Union

from astrbot.api.all import Plain, Image, Node, Nodes, File, logger

from data.plugins.astrbot_plugin_ebooks.Zlibrary import Zlibrary
from data.plugins.astrbot_plugin_ebooks.utils import (
    download_and_convert_to_base64,
    is_base64_image,
    is_url_accessible,
    is_valid_zlib_book_hash,
    is_valid_zlib_book_id,
    truncate_filename,
)

MAX_ZLIB_RETRY_COUNT = 3
MAX_ZLIB_SEARCH_RETRY_COUNT = 3


class ZlibSource:
    def __init__(self, config, proxy: str, max_results: int, temp_path: str):
        self.config = config
        self.proxy = proxy
        self.max_results = max_results
        self.temp_path = temp_path
        self.zlibrary = Zlibrary()
        self._init_login()

    def _init_login(self):
        if self.config.get("enable_zlib", False):
            email = self.config.get("zlib_email", "").strip()
            password = self.config.get("zlib_password", "").strip()

            if email and password:
                try:
                    self.zlibrary = Zlibrary(email=email, password=password)
                    if self.zlibrary.isLoggedIn():
                        logger.info("[ebooks] 已登录 Z-Library。")
                    else:
                        logger.error("登录 Z-Library 失败。")
                except Exception as e:
                    logger.error(f"登录 Z-Library 失败，报错： {e}")
            else:
                self.disable("未设置 Z-Library 账户，禁用该平台。")

    def disable(self, reason: str):
        self.zlibrary = Zlibrary()
        self.config["enable_zlib"] = False
        self.config.save_config()
        logger.info(f"[ebooks] {reason}")

    async def terminate(self):
        if self.zlibrary and self.zlibrary.isLoggedIn():
            self.zlibrary = Zlibrary()

    def _ensure_login(self):
        if self.zlibrary.isLoggedIn():
            return True

        email = self.config.get("zlib_email", "").strip()
        password = self.config.get("zlib_password", "").strip()
        retry_count = 0
        while retry_count < MAX_ZLIB_RETRY_COUNT:
            try:
                self.zlibrary.login(email, password)
                if self.zlibrary.isLoggedIn():
                    return True
            except Exception:
                pass
            retry_count += 1
        return False

    async def search_nodes(self, event, query: str, limit: int = 0):
        if not self.config.get("enable_zlib", False):
            return "[Z-Library] 功能未启用。"

        if not await is_url_accessible("https://z-library.sk", proxy=self.proxy):
            return "[Z-Library] 无法连接到 Z-Library。"

        if not query:
            return "[Z-Library] 请提供电子书关键词以进行搜索。"

        if limit < 1:
            return "[Z-Library] 请确认搜索返回结果数量在 1-60 之间。"
        if limit > 60:
            limit = 60

        try:
            logger.info(f"[Z-Library] Received books search query: {query}, limit: {limit}")

            if not self._ensure_login():
                return "[Z-Library] 登录失败。"

            results = None
            had_exception = False
            for attempt in range(MAX_ZLIB_SEARCH_RETRY_COUNT):
                try:
                    results = self.zlibrary.search(message=query, limit=limit)
                    if results and results.get("books"):
                        break
                except Exception as e:
                    had_exception = True
                    logger.warning(f"[Z-Library] Search attempt {attempt + 1} failed: {e}")
                if attempt < MAX_ZLIB_SEARCH_RETRY_COUNT - 1:
                    await asyncio.sleep(0.5)

            if results and results.get("books"):
                books = results.get("books", [])
            elif had_exception:
                return "[Z-Library] 暂时无法连接到 Z-Library，请稍后再试。"
            else:
                return "[Z-Library] 未找到匹配的电子书。"

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

                chain.append(Plain(f"作者: {book.get('author', '未知')}\n"))
                chain.append(Plain(f"年份: {book.get('year', '未知')}\n"))

                publisher = book.get("publisher", None)
                if not publisher or publisher == "None":
                    publisher = "未知"
                chain.append(Plain(f"出版社: {publisher}\n"))

                chain.append(Plain(f"语言: {book.get('language', '未知')}\n"))

                description = book.get("description", "无简介")
                if isinstance(description, str) and description.strip() != "":
                    description = description.strip()
                    description = description[:150] + "..." if len(description) > 150 else description
                else:
                    description = "无简介"
                chain.append(Plain(f"简介: {description}\n"))

                chain.append(Plain(f"ID(用于下载): {book.get('id')}\n"))
                chain.append(Plain(f"Hash(用于下载): {book.get('hash')}"))

                return Node(
                    uin=event.get_self_id(),
                    name="Z-Library",
                    content=chain,
                )

            tasks = [construct_node(book) for book in books]
            return await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"[Z-Library] Error during book search: {e}")
            return "[Z-Library] 搜索电子书时发生错误，请稍后再试。"

    async def download(self, event, book_id: str = None, book_hash: Union[str, int] = None):
        if not self.config.get("enable_zlib", False):
            return [event.plain_result("[Z-Library] 功能未启用。")]

        if not is_valid_zlib_book_id(book_id) or not is_valid_zlib_book_hash(book_hash):
            return [event.plain_result("[Z-Library] 请使用 /zlib download <id> <hash> 下载。")]

        if not await is_url_accessible("https://z-library.sk", proxy=self.proxy):
            return [event.plain_result("[Z-Library] 无法连接到 Z-Library。")]

        try:
            if not self._ensure_login():
                return [event.plain_result("[Z-Library] 登录失败。")]

            book_details = self.zlibrary.getBookInfo(book_id, hashid=book_hash)
            if not book_details:
                return [event.plain_result("[Z-Library] 无法获取电子书详情，请检查电子书 ID 是否正确。")]

            downloaded_book = self.zlibrary.downloadBook({"id": book_id, "hash": book_hash})
            if downloaded_book:
                book_name, book_content = downloaded_book
                book_name = truncate_filename(book_name)

                temp_file_path = os.path.join(self.temp_path, book_name)
                with open(temp_file_path, "wb") as file:
                    file.write(book_content)

                logger.debug(f"[Z-Library] 文件已下载并保存到临时目录：{temp_file_path}")

                file = File(name=book_name, file=str(temp_file_path))
                asyncio.create_task(self._cleanup_file(temp_file_path))
                return [event.chain_result([file])]
            return [event.plain_result("[Z-Library] 下载电子书时发生错误，请稍后再试。")]
        except Exception as e:
            logger.error(f"[Z-Library] Error during book download: {e}")
            return [event.plain_result("[Z-Library] 下载电子书时发生错误，请稍后再试。")]

    async def _cleanup_file(self, path: str):
        try:
            await asyncio.sleep(5)
            os.remove(path)
        except Exception:
            pass
