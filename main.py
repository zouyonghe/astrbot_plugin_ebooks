import asyncio
import io
import random
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional
from urllib.parse import quote_plus, urljoin, unquote, urlparse
from PIL import Image as Img

import aiofiles
import aiohttp
from aiohttp import ClientPayloadError
from bs4 import BeautifulSoup

from data.plugins.astrbot_plugin_ebooks.Zlibrary import Zlibrary
from astrbot.api.all import *
from astrbot.api.event.filter import *


@register("ebooks", "buding", "一个功能强大的电子书搜索和下载插件", "1.0.2", "https://github.com/zouyonghe/astrbot_plugin_ebooks")
class ebooks(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.proxy = os.environ.get("https_proxy")
        self.TEMP_PATH = os.path.abspath("data/temp")
        os.makedirs(self.TEMP_PATH, exist_ok=True)
        self.zlibrary = None

    async def is_url_accessible(self, url: str, proxy: bool=True) -> bool:
        """
        异步检查给定的 URL 是否可访问。

        :param url: 要检查的 URL
        :param proxy: 是否使用代理
        :return: 如果 URL 可访问返回 True，否则返回 False
        """
        try:
            async with aiohttp.ClientSession() as session:
                if proxy:
                    async with session.head(url, timeout=10, proxy=self.proxy, allow_redirects=True) as response:
                        return response.status == 200
                else:
                    async with session.head(url, timeout=10, allow_redirects=True) as response:
                        return response.status == 200
        except:
            return False  # 如果请求失败（超时、连接中断等）则返回 False

    async def download_and_convert_to_base64(self, cover_url):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(cover_url, proxy=self.proxy) as response:
                    if response.status != 200:
                        return None

                    content_type = response.headers.get('Content-Type', '').lower()
                    # 如果 Content-Type 包含 html，则说明可能不是直接的图片
                    if 'html' in content_type:
                        html_content = await response.text()
                        # 使用 BeautifulSoup 提取图片地址
                        soup = BeautifulSoup(html_content, 'html.parser')
                        img_tag = soup.find('meta', attrs={'property': 'og:image'})
                        if img_tag:
                            cover_url = img_tag.get('content')
                            # 再次尝试下载真正的图片地址
                            return await self.download_and_convert_to_base64(cover_url)
                        else:
                            return None

                    # 如果是图片内容，继续下载并转为 Base64
                    content = await response.read()
                    base64_data = base64.b64encode(content).decode("utf-8")
                    return base64_data
        except ClientPayloadError as payload_error:
            # 尝试已接收的数据部分
            if 'content' in locals():  # 如果部分内容已下载
                base64_data = base64.b64encode(content).decode("utf-8")
                if self.is_base64_image(base64_data):  # 检查 Base64 数据是否有效
                    return base64_data
        except:
            return None

    def is_base64_image(self, base64_data: str) -> bool:
        """
        检测 Base64 数据是否为有效图片
        :param base64_data: Base64 编码的字符串
        :return: 如果是图片返回 True，否则返回 False
        """
        try:
            # 解码 Base64 数据
            image_data = base64.b64decode(base64_data)
            # 尝试用 Pillow 打开图片
            image = Img.open(io.BytesIO(image_data))
            # 如果图片能正确被打开，再检查格式是否为支持的图片格式
            image.verify()  # 验证图片
            return True  # Base64 是有效图片
        except Exception:
            return False  # 如果解析失败，说明不是图片

    async def _search_calibre_web(self, query: str, limit: int = None):
        '''Call the Calibre-Web Catalog API to search for eBooks.'''
        calibre_web_url = self.config.get("calibre_web_url", "http://127.0.0.1:8083")
        search_url = f"{calibre_web_url}/opds/search/{query}"  # 根据实际路径构造 API URL

        async with aiohttp.ClientSession() as session:
            async with session.get(search_url) as response:
                if response.status == 200:
                    content_type = response.headers.get("Content-Type", "")
                    if "application/atom+xml" in content_type:
                        data = await response.text()
                        return self._parse_opds_response(data, limit)  # 调用解析方法
                    else:
                        logger.error(f"[Calibre-Web] Unexpected content type: {content_type}")
                        return None
                else:
                    logger.error(
                        f"[Calibre-Web] Error during search: Calibre-Web returned status code {response.status}")
                    return None

    def _parse_opds_response(self, xml_data: str, limit: int = None):
        '''Parse the opds search result XML data.'''
        calibre_web_url = self.config.get("calibre_web_url", "http://127.0.0.1:8083")

        # Remove illegal characters
        xml_data = re.sub(r'[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD]', '', xml_data)
        # 消除多余空格
        xml_data = re.sub(r'\s+', ' ', xml_data)

        try:
            root = ET.fromstring(xml_data)  # 把 XML 转换为元素树
            namespace = {"default": "http://www.w3.org/2005/Atom"}  # 定义命名空间
            entries = root.findall("default:entry", namespace)  # 查找前20个 <entry> 节点

            results = []
            for entry in entries:
                # 提取电子书标题
                title_element = entry.find("default:title", namespace)
                title = title_element.text if title_element is not None else "未知标题"

                # 提取作者，多作者场景
                authors = []
                author_elements = entry.findall("default:author/default:name", namespace)
                for author in author_elements:
                    authors.append(author.text if author is not None else "未知作者")
                authors = ", ".join(authors) if authors else "未知作者"

                # 提取描述（<summary>）
                summary_element = entry.find("default:summary", namespace)
                summary = summary_element.text if summary_element is not None else "暂无描述"

                # 提取出版日期（<published>）
                published_element = entry.find("default:published", namespace)
                #published_date = published_element.text if published_element is not None else "未知出版日期"
                if published_element is not None and published_element.text:
                    try:
                        # 解析日期字符串为 datetime 对象，并提取年份
                        year = datetime.fromisoformat(published_element.text).year
                    except ValueError:
                        year = "未知年份"  # 日期解析失败时处理
                else:
                    year = "未知年份"

                # 提取语言（<dcterms:language>），需注意 namespace
                lang_element = entry.find("default:dcterms:language", namespace)
                language = lang_element.text if lang_element is not None else "未知语言"

                # 提取出版社信息（<publisher>）
                publisher_element = entry.find("default:publisher/default:name", namespace)
                publisher = publisher_element.text if publisher_element is not None else "未知出版社"

                # 提取图书封面链接（rel="http://opds-spec.org/image"）
                cover_element = entry.find("default:link[@rel='http://opds-spec.org/image']", namespace)
                cover_suffix = cover_element.attrib.get("href", "") if cover_element is not None else ""
                if cover_suffix and re.match(r"^/opds/cover/\d+$", cover_suffix):
                    cover_link = urljoin(calibre_web_url, cover_suffix)
                else:
                    cover_link = ""

                # 提取图书缩略图链接（rel="http://opds-spec.org/image/thumbnail"）
                thumbnail_element = entry.find("default:link[@rel='http://opds-spec.org/image/thumbnail']", namespace)
                thumbnail_suffix = thumbnail_element.attrib.get("href", "") if thumbnail_element is not None else ""
                if thumbnail_suffix and re.match(r"^/opds/cover/\d+$", thumbnail_suffix):
                    thumbnail_link = urljoin(calibre_web_url, thumbnail_suffix)
                else:
                    thumbnail_link = ""

                # 提取下载链接及其格式（rel="http://opds-spec.org/acquisition"）
                acquisition_element = entry.find("default:link[@rel='http://opds-spec.org/acquisition']", namespace)
                if acquisition_element is not None:
                    download_suffix = acquisition_element.attrib.get("href", "") if acquisition_element is not None else ""
                    if download_suffix and re.match(r"^/opds/download/\d+/[\w]+/$", download_suffix):
                        download_link = urljoin(calibre_web_url, download_suffix)
                    else:
                        download_link = ""
                    file_type = acquisition_element.attrib.get("type", "未知格式")
                    file_size = acquisition_element.attrib.get("length", "未知大小")
                else:
                    download_link = ""
                    file_type = "未知格式"
                    file_size = "未知格式"

                # 构建结果
                results.append({
                    "title": title,
                    "authors": authors,
                    "summary": summary,
                    "year": year,
                    "publisher": publisher,
                    "language": language,
                    "cover_link": cover_link,
                    "thumbnail_link": thumbnail_link,
                    "download_link": download_link,
                    "file_type": file_type,
                    "file_size": file_size
                })

            return results[:limit]
        except ET.ParseError as e:
            logger.error(f"[Calibre-Web] Error parsing OPDS response: {e}")
            return None

    async def build_book_chain(self, item: dict) -> list:
        """
        构建对应书籍条目的消息链。

        :param item: 包含书籍信息的字典
        :return: 生成的消息链列表
        """
        chain = [Plain(f"{item['title']}")]
        if item.get("cover_link") and await self.is_url_accessible(item.get("cover_link"), False):
            chain.append(Image.fromURL(item["cover_link"]))
        else:
            chain.append(Plain("\n"))
        chain.append(Plain(f"作者: {item.get('authors', '未知')}\n"))
        chain.append(Plain(f"年份: {item.get('year', '未知')}\n"))
        chain.append(Plain(f"出版社: {item.get('publisher', '未知')}\n"))
        description = item.get("summary", "")
        if isinstance(description, str) and description != "":
            description = description.strip()
            description = description[:150] + "..." if len(description) > 150 else description
        else:
            description = "无简介"
        chain.append(Plain(f"简介: {description}\n"))
        chain.append(Plain(f"链接(用于下载): {item.get('download_link', '未知')}"))
        return chain

    async def _show_calibre_result(self, event: AstrMessageEvent, results: list, guidance: str = None):
        if not results:
            yield event.plain_result("[Calibre-Web] 未找到匹配的电子书。")
            return

        ns = Nodes([])
        if guidance:
            ns.nodes.append(Node(uin=event.get_self_id(), name="Calibre-Web", content=guidance))

        for item in results:
            chain = await self.build_book_chain(item)
            node = Node(
                uin=event.get_self_id(),
                name="Calibre-Web",
                content=chain
            )
            ns.nodes.append(node)

        yield event.chain_result([ns])

    def is_valid_calibre_book_url(self, book_url: str) -> bool:
        """检测电子书下载链接格式是否合法"""
        if not book_url:
            return False  # URL 不能为空

        # 检测是否是合法的 URL (基础验证)
        pattern = re.compile(r'^https?://.+/.+$')
        if not pattern.match(book_url):
            return False

        # 检查是否满足特定的结构，例如包含 /opds/download/
        if "/opds/download/" not in book_url:
            return False

        return True

    @command_group("calibre")
    def calibre(self):
        pass

    @calibre.command("search")
    async def search_calibre(self, event: AstrMessageEvent, query: str, limit: str="20"):
        '''搜索 calibre-web 电子书目录'''
        if not self.config.get("enable_calibre", False):
            yield event.plain_result("[Calibre-Web] 功能未启用。")
            return

        if not query:
            yield event.plain_result("[Calibre-Web] 请提供电子书关键词以进行搜索。")
            return

        limit = int(limit) if limit.isdigit() else 20
        if not (1 <= limit <= 50):  # Validate limit
            yield event.plain_result("[Calibre-Web] 请确认搜索返回结果数量在 1-50 之间。")
            return

        try:
            logger.info(f"[Calibre-Web] Received books search query: {query}, limit: {limit}")
            results = await self._search_calibre_web(quote_plus(query), limit)  # 调用搜索方法
            if not results or len(results) == 0:
                yield event.plain_result("[Calibre-Web] 未找到匹配的电子书。")
            else:
                async for result in self._show_calibre_result(event, results):
                    yield result
        except Exception as e:
            logger.error(f"[Calibre-Web] 搜索失败: {e}")
            yield event.plain_result("[Calibre-Web] 搜索电子书时发生错误，请稍后再试。")

    @calibre.command("download")
    async def download_calibre(self, event: AstrMessageEvent, book_url: str = None):
        '''下载 calibre-web 电子书'''
        if not self.config.get("enable_calibre", False):
            yield event.plain_result("[Calibre-Web] 功能未启用。")
            return

        if not self.is_valid_calibre_book_url(book_url):
            yield event.plain_result("[Calibre-Web] 请提供有效的电子书链接。")
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(book_url) as response:
                    if response.status == 200:
                        # 从 Content-Disposition 提取文件名
                        content_disposition = response.headers.get("Content-Disposition")
                        book_name = None

                        if content_disposition:
                            # 先检查是否有 filename*= 条目
                            book_name_match = re.search(r'filename\*=(?:UTF-8\'\')?([^;]+)', content_disposition)
                            if book_name_match:
                                book_name = book_name_match.group(1)
                                book_name = unquote(book_name)  # 解码 URL 编码的文件名
                            else:
                                # 如果没有 filename*，则查找普通的 filename
                                book_name_match = re.search(r'filename=["\']?([^;\']+)["\']?', content_disposition)
                                if book_name:
                                    book_name = book_name_match.group(1)

                        # 如果未获取到文件名，使用默认值
                        if not book_name or book_name.strip() == "":
                            logger.error(f"[Calibre-Web] 无法提取书名，电子书地址: {book_url}")
                            yield event.plain_result("[Calibre-Web] 无法提取书名，取消发送电子书。")
                            return 
                            
                        # 发送文件到用户
                        file = File(name=book_name, file=book_url)
                        yield event.chain_result([file])
                    else:
                        yield event.plain_result(f"[Calibre-Web] 无法下载电子书，状态码: {response.status}")
        except Exception as e:
            logger.error(f"[Calibre-Web] 下载失败: {e}")
            yield event.plain_result("[Calibre-Web] 下载电子书时发生错误，请稍后再试。")

    @calibre.command("recommend")
    async def recommend_calibre(self, event: AstrMessageEvent, n: int):
        '''随机推荐 n 本电子书'''
        if not self.config.get("enable_calibre", False):
            yield event.plain_result("[Calibre-Web] 功能未启用。")
            return

        try:
            # 调用 Calibre-Web 搜索接口，默认搜索所有电子书
            query = "*"  # 空查询，可以调出完整书目
            results = await self._search_calibre_web(query)

            # 检查是否有电子书可供推荐
            if not results:
                yield event.plain_result("[Calibre-Web] 未找到可推荐的电子书。")
                return

            # 限制推荐数量，防止超出实际电子书数量
            if n > len(results):
                n = len(results)

            # 随机选择 n 本电子书
            recommended_books = random.sample(results, n)

            # 显示推荐电子书
            guidance = f"如下是随机推荐的 {n} 本电子书"
            async for result in self._show_calibre_result(event, recommended_books, guidance):
                yield result

        except Exception as e:
            logger.error(f"[Calibre-Web] 推荐电子书时发生错误: {e}")
            yield event.plain_result("[Calibre-Web] 推荐电子书时发生错误，请稍后再试。")

    # @llm_tool("search_calibre_books")
    async def search_calibre_books(self, event: AstrMessageEvent, query: str):
        """Search books by keywords or title through Calibre-Web.
        When to use:
            Use this method to search for books in the Calibre-Web catalog when user knows the title or keyword.
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

    @llm_tool("recommend_books")
    async def recommend_calibre_books(self, event: AstrMessageEvent, n: str = "5"):
        """Randomly recommend n books.
        When to use:
            Use this method to get a random selection of books when users are unsure what to read.
    
        Args:
            n (string): Number of books to recommend (default is 5).
        """
        async for result in self.recommend_calibre(event, int(n)):
            yield result
            
    async def get_liber3_book_details(self, book_ids: list) -> Optional[dict]:
        """通过电子书 ID 获取详细信息"""
        detail_url = "https://lgate.glitternode.ru/v1/book"
        headers = {"Content-Type": "application/json"}
        payload = {"book_ids": book_ids}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(detail_url, headers=headers, json=payload, proxy=self.proxy) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("data", {}).get("book", {})
                    else:
                        logger.error(f"[Liber3] Error during detail request: Status code {response.status}")
                        return None
        except aiohttp.ClientError as e:
            logger.error(f"[Liber3] HTTP client error: {e}")
        except Exception as e:
            logger.error(f"[Liber3] 发生意外错误: {e}")

        return None
    
    async def search_liber3_books_with_details(self, word: str, limit: int = 50) -> Optional[dict]:
        """搜索电子书并获取前 limit 本电子书的详细信息"""
        search_url = "https://lgate.glitternode.ru/v1/searchV2"
        headers = {"Content-Type": "application/json"}
        payload = {
            "address": "",
            "word": word
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(search_url, headers=headers, json=payload, proxy=self.proxy) as response:
                    if response.status == 200:
                        data = await response.json()

                        # 获取电子书 ID 列表
                        book_data = data["data"].get("book", [])
                        if not book_data:
                            logger.info("[Liber3] 未找到匹配的电子书。")
                            return None

                        book_ids = [item.get("id") for item in book_data[:limit]]
                        if not book_ids:
                            logger.info("[Liber3] 未能提取电子书 ID。")
                            return None

                        # 调用详细信息 API
                        detailed_books = await self.get_liber3_book_details(book_ids)
                        if not detailed_books:
                            logger.info("[Liber3] 未获取电子书详细信息。")
                            return None

                        # 返回包含搜索结果及详细信息的数据
                        return {
                            "search_results": book_data[:limit],
                            "detailed_books": detailed_books
                        }

                    else:
                        logger.error(f"[Liber3] 请求电子书搜索失败，状态码: {response.status}")
                        return None
        except aiohttp.ClientError as e:
            logger.error(f"[Liber3] HTTP 客户端错误: {e}")
        except Exception as e:
            logger.error(f"[Liber3] 发生意外错误: {e}")

        return None

    def is_valid_liber3_book_id(self, book_id: str) -> bool:
        """检测 Liber3 的 book_id 是否有效"""
        if not book_id:
            return False  # 不能为空

        # 使用正则表达式验证是否是 32 位大写十六进制字符串
        pattern = re.compile(r'^[a-fA-F0-9]{32}$')
        return bool(pattern.match(book_id))

    @command_group("liber3")
    def liber3(self):
        pass

    @liber3.command("search")
    async def search_liber3(self, event: AstrMessageEvent, query: str = None, limit: str="20"):
        """搜索电子书并输出详细信息"""
        if not self.config.get("enable_liber3", False):
            yield event.plain_result("[Liber3] 功能未启用。")
            return

        if not query:
            yield event.plain_result("[Liber3] 请提供电子书关键词以进行搜索。")
            return

        limit = int(limit) if limit.isdigit() else 20
        if not (1 <= limit <= 50):  # Validate limit
            yield event.plain_result("[Liber3] 请确认搜索返回结果数量在 1-50 之间。")
            return

        logger.info(f"[Liber3] Received books search query: {query}, limit: {limit}")
        results = await self.search_liber3_books_with_details(query, limit)

        if not results:
            yield event.plain_result("[Liber3] 未找到匹配的电子书。")
            return

        # 输出搜索结果和详细信息
        search_results = results.get("search_results", [])
        detailed_books = results.get("detailed_books", {})

        ns = Nodes([])

        for book in search_results:
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
                Plain(f"ID(用于下载): {book_id}"),
            ]

            node = Node(
                uin=event.get_self_id(),
                name="Liber3",
                content=chain
            )
            ns.nodes.append(node)

        yield event.chain_result([ns])

    @liber3.command("download")
    async def download_liber3(self, event: AstrMessageEvent, book_id: str = None):
        if not self.config.get("enable_liber3", False):
            yield event.plain_result("[Liber3] 功能未启用。")
            return

        if not self.is_valid_liber3_book_id(book_id):
            yield event.plain_result("[Liber3] 请提供有效的电子书 ID。")
            return

        # 获取详细的电子书信息
        book_details = await self.get_liber3_book_details([book_id])
        if not book_details or book_id not in book_details:
            yield event.plain_result("[Liber3] 无法获取电子书元信息，请检查电子书 ID 是否正确。")
            return

        # 提取电子书信息
        book_info = book_details[book_id].get("book", {})
        book_name = book_info.get("title", "unknown_book").replace(" ", "_")
        extension = book_info.get("extension", "unknown_extension")
        ipfs_cid = book_info.get("ipfs_cid", "")

        if not ipfs_cid or not extension:
            yield event.plain_result("[Liber3] 电子书信息不足，无法完成下载。")
            return

        # 构造下载链接
        ebook_url = f"https://gateway-ipfs.st/ipfs/{ipfs_cid}?filename={book_name}.{extension}"

        # 使用 File 对象，通过 chain_result 下载
        file = File(name=f"{book_name}.{extension}", file=ebook_url)
        yield event.chain_result([file])

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


    async def _search_archive_books(self, query: str, limit: int = 20):
        """Search for eBooks through the Archive API and filter files in PDF or EPUB formats.
            Args:
                query (str): Search keyword for titles
                limit (int): Maximum number of results to return
            Returns:
                list: A list containing book information and download links that meet the criteria
        """
        base_search_url = "https://archive.org/advancedsearch.php"
        base_metadata_url = "https://archive.org/metadata/"
        formats = ("pdf", "epub")  # 支持的电子书格式

        params = {
            "q": f'title:"{query}" mediatype:texts',  # 根据标题搜索
            "fl[]": "identifier,title",  # 返回 identifier 和 title 字段
            "sort[]": "downloads desc",  # 按下载量排序
            "rows": limit+10,  # 最大结果数量
            "page": 1,
            "output": "json"  # 返回格式为 JSON
        }

        async with aiohttp.ClientSession() as session:
            # 1. 调用 Archive 搜索 API
            response = await session.get(base_search_url, params=params, proxy=self.proxy)
            if response.status != 200:
                logger.error(
                    f"[Archive] Error during search: Archive API returned status code {response.status}")
                return []

            result_data = await response.json()
            docs = result_data.get("response", {}).get("docs", [])
            if not docs:
                logger.info("[Archive] 未找到匹配的电子书。")
                return []

            # 2. 根据 identifier 提取元数据
            tasks = [
                self._fetch_metadata(session, base_metadata_url + doc["identifier"], formats) for doc in docs
            ]
            metadata_results = await asyncio.gather(*tasks)

            # 3. 筛选有效结果并返回
            books = [
                {
                    "title": doc.get("title"),
                    "cover": metadata.get("cover"),
                    "authors": metadata.get("authors"),
                    "language": metadata.get("language"),
                    "year": metadata.get("year"),
                    "publisher": metadata.get("publisher"),
                    "download_url": metadata.get("download_url"),
                    "description": metadata.get("description")
                }
                for doc, metadata in zip(docs, metadata_results) if metadata
            ][:limit]
            return books

    async def _fetch_metadata(self, session: aiohttp.ClientSession, url: str, formats: tuple) -> dict:
        """
            Retrieve specific eBook formats from the Metadata API and extract covers and descriptions.
            Args:
                session (aiohttp.ClientSession): aiohttp session
                url (str): URL of the Metadata API
                formats (tuple): Required formats (e.g., PDF, EPUB)
            Returns:
                dict: A dictionary with download links, file type, cover, and description
        """
        try:
            response = await session.get(url, proxy=self.proxy)
            if response.status != 200:
                logger.error(f"[Archive] Error retrieving Metadata: Status code {response.status}")
                return {}

            book_detail = await response.json()

            identifier = book_detail.get("metadata", {}).get("identifier", None)
            if not identifier:
                return {}
            files = book_detail.get("files", [])
            description = book_detail.get("metadata", {}).get("description", "无简介")
            authors = book_detail.get("metadata", {}).get("creator", "未知")
            language = book_detail.get("metadata", {}).get("language", "未知")
            year = book_detail.get("metadata", {}).get("publicdate", "未知")[:4] if book_detail.get("metadata", {}).get(
                "publicdate", "未知") != "未知" else "未知"
            publisher = book_detail.get("metadata", {}).get("publisher", "未知")

            # 判断并解析简介
            if isinstance(description, str):
                if self._is_html(description):
                    description = self._parse_html_to_text(description)
                else:
                    description = description.strip()
                description = description[:150] + "..." if len(description) > 150 else description
            else:
                description = "无简介"

            # 提取特定格式文件（如 PDF 和 EPUB）
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
            logger.error(f"[Archive] 获取 Metadata 数据时发生错误: {e}")
        return {}

    def _is_html(self, content):
        """Determine whether a string is in HTML format."""
        if not isinstance(content, str):
            return False
        return bool(re.search(r'<[^>]+>', content))

    def _parse_html_to_text(self, html_content):
        """Parse HTML content into plain text."""
        soup = BeautifulSoup(html_content, "html.parser")
        return soup.get_text().strip()

    def is_valid_archive_book_url(self, book_url: str) -> bool:
        """检测 archive.org 下载链接格式是否合法"""
        if not book_url:
            return False  # URL 不能为空

        # 使用正则表达式验证链接格式是否合法
        pattern = re.compile(
            r'^https://archive\.org/download/[^/]+/[^/]+$'
        )

        return bool(pattern.match(book_url))

    @command_group("archive")
    def archive(self):
        pass

    @archive.command("search")
    async def search_archive(self, event: AstrMessageEvent, query: str = None, limit: str = "20"):
        """
            Search for eBooks using the Archive platform, filtering for supported formats.
            Args:
                query (str): The book title or keywords to search for (required).
                limit (str): The result limit, default is 20.
        """
        if not self.config.get("enable_archive", False):
            yield event.plain_result("[Archive] 功能未启用。")
            return

        if not self.is_url_accessible("https://archive.org/advancedsearch.php"):
            yield event.plain_result("[Archive] 无法连接到 Archive.org。")
            return

        if not query:
            yield event.plain_result("[Archive] 请提供电子书关键词以进行搜索。")
            return
        
        limit = int(limit) if limit.isdigit() else 20
        if not (1 <= limit <= 50):  # Validate limit
            yield event.plain_result("[Archive] 请确认搜索返回结果数量在 1-50 之间。")
            return
        try:
            logger.info(f"[Archive] Received books search query: {query}, limit: {limit}")
            results = await self._search_archive_books(limit)

            if not results:
                yield event.plain_result("[Archive] 未找到匹配的电子书。")
                return

            # 返回结果到用户
            ns = Nodes([])
            for book in results:
                chain = [Plain(f"{book.get('title', '未知')}")]
                if book.get("cover") and await self.is_url_accessible(book.get("cover")):
                    base64_image = await self.download_and_convert_to_base64(book.get("cover"))
                    if base64_image:
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

                node = Node(uin=event.get_self_id(), name="Archive", content=chain)
                ns.nodes.append(node)

            yield event.chain_result([ns])

        except Exception as e:
            logger.error(f"[Archive] Error processing Archive search request: {e}")
            yield event.plain_result("[Archive] 搜索电子书时发生错误，请稍后再试。")

    @archive.command("download")
    async def download_archive(self, event: AstrMessageEvent, book_url: str = None):
        """Download an eBook from the Archive platform using a provided link.
            Args:
                book_url (str): The download URL of the eBook.
        """
        if not self.config.get("enable_archive", False):
            yield event.plain_result("[Archive] 功能未启用。")
            return

        if not self.is_url_accessible("https://archive.org/advancedsearch.php"):
            yield event.plain_result("[Archive] 无法连接到 Archive.org。")
            return

        if not self.is_valid_archive_book_url(book_url):
            yield event.plain_result("[Archive] 请提供有效的下载链接。")
            return

        try:
            async with aiohttp.ClientSession() as session:
                # 发出 GET 请求并跟随跳转
                async with session.get(book_url, allow_redirects=True, proxy=self.proxy) as response:
                    if response.status == 200:
                        ebook_url = str(response.url)
                        logger.debug(f"[Archive] 跳转后的下载地址: {ebook_url}")

                        # 从 Content-Disposition 提取文件名
                        content_disposition = response.headers.get("Content-Disposition", "")
                        book_name = None

                        # 提取文件名
                        if content_disposition:
                            book_name_match = re.search(r'filename\*=(?:UTF-8\'\')?([^;]+)', content_disposition)
                            if book_name_match:
                                book_name = unquote(book_name_match.group(1))
                            else:
                                book_name_match = re.search(r'filename=["\']?([^;\']+)["\']?', content_disposition)
                                if book_name_match:
                                    book_name = book_name_match.group(1)

                        # 如果未提取到文件名，尝试从 URL 提取
                        if not book_name or book_name.strip() == "":
                            parsed_url = urlparse(ebook_url)
                            book_name = os.path.basename(parsed_url.path) or "unknown_book"

                        # 构造临时文件路径
                        temp_file_path = os.path.join(self.TEMP_PATH, book_name)

                        # 保存下载文件到本地
                        async with aiofiles.open(temp_file_path, "wb") as temp_file:
                            await temp_file.write(await response.read())

                        # 打印日志确认保存成功
                        logger.info(f"[Archive] 文件已下载并保存到临时目录：{temp_file_path}")

                        # 直接传递本地文件路径
                        file = File(name=book_name, file=temp_file_path)
                        yield event.chain_result([file])
                        os.remove(temp_file_path)

                        # file = File(name=book_name, file=ebook_url)
                        # yield event.chain_result([file])
                    else:
                        yield event.plain_result(f"[Archive] 无法下载电子书，状态码: {response.status}")
        except Exception as e:
            logger.error(f"[Archive] 下载失败: {e}")
            yield event.plain_result(f"[Archive] 下载电子书时发生错误，请稍后再试。")

    # @llm_tool("search_archive_books")
    async def search_archive_books(self, event: AstrMessageEvent, query: str):
        """Search for eBooks using the Archive API.
    
        When to use:
            Utilize this method to search books available in supported formats (such as PDF or EPUB) on the Archive API platform.
    
        Args:
            query (string): The keywords or title to perform the search.
        """
        async for result in self.search_archive(event, query):
            yield result

    # @llm_tool("download_archive_book")
    async def download_archive_book(self, event: AstrMessageEvent, download_url: str):
        """Download an eBook from the Archive API using its download URL.
    
        When to use:
            Use this method to download a specific book from the Archive platform using the book's provided download link.
    
        Args:
            download_url (string): A valid and supported Archive book download URL.
        """
        async for result in self.download_archive(event, download_url):
            yield result

    def is_valid_zlib_book_id(self, book_id: str) -> bool:
        """检测 zlib ID 是否为纯数字"""
        if not book_id:
            return False
        return book_id.isdigit()

    def is_valid_zlib_book_hash(self, hash: str) -> bool:
        """检测 zlib Hash 是否为 6 位十六进制"""
        if not hash:
            return False
        pattern = re.compile(r'^[a-f0-9]{6}$', re.IGNORECASE)  # 忽略大小写
        return bool(pattern.match(hash))

    @command_group("zlib")
    def zlib(self):
        pass

    @zlib.command("search")
    async def search_zlib(self, event: AstrMessageEvent, query: str = None, limit: str = "20"):
        """搜索 Zlibrary 电子书并输出详细信息"""
        if not self.config.get("enable_zlib", False):
            yield event.plain_result("[Z-Library] 功能未启用。")
            return

        if not await self.is_url_accessible("https://z-library.sk"):
            yield event.plain_result("[Z-Library] 无法连接到 Z-Library。")
            return

        if not query:
            yield event.plain_result("[Z-Library] 请提供电子书关键词以进行搜索。")
            return

        try:
            limit = int(limit) if limit.isdigit() else 20
            if not (1 <= limit <= 50):  # Validate limit
                yield event.plain_result("[Z-Library] 请确认搜索返回结果数量在 1-50 之间。")
                return

            logger.info(f"[Z-Library] Received books search query: {query}, limit: {limit}")

            if not self.zlibrary:
                self.zlibrary = Zlibrary(email=self.config["zlib_email"], password=self.config["zlib_password"])

            # 调用 Zlibrary 的 search 方法进行搜索
            results = self.zlibrary.search(message=query, limit=limit)

            if not results or not results.get("books"):
                yield event.plain_result("[Z-Library] 未找到匹配的电子书。")
                return

            # 处理搜索结果
            books = results.get("books", [])
            ns = Nodes([])

            for book in books:
                chain = [Plain(f"{book.get('title', '未知')}")]
                if book.get("cover") and await self.is_url_accessible(book.get("cover")):
                    base64_image = await self.download_and_convert_to_base64(book.get("cover"))
                    if base64_image:
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
                if isinstance(description, str) and description != "":
                    description = description.strip()
                    description = description[:150] + "..." if len(description) > 150 else description
                else:
                    description = "无简介"
                chain.append(Plain(f"简介: {description}\n"))
                chain.append(Plain(f"ID(用于下载): {book.get('id')}\n"))
                chain.append(Plain(f"Hash(用于下载): {book.get('hash')}"))

                node = Node(
                    uin=event.get_self_id(),
                    name="Z-Library",
                    content=chain,
                )
                ns.nodes.append(node)

            yield event.chain_result([ns])

        except Exception as e:
            logger.error(f"[Z-Library] Error during book search: {e}")
            yield event.plain_result("[Z-Library] 搜索电子书时发生错误，请稍后再试。")

    @zlib.command("download")
    async def download_zlib(self, event: AstrMessageEvent, book_id: str = None, book_hash: str = None):
        """下载 Z-Library 电子书"""
        if not self.config.get("enable_zlib", False):
            yield event.plain_result("[Z-Library] 功能未启用。")
            return

        if not await self.is_url_accessible("https://z-library.sk"):
            yield event.plain_result("[Z-Library] 无法连接到 Z-Library。")
            return

        if not self.is_valid_zlib_book_id(book_id) or not self.is_valid_zlib_book_hash(book_hash):
            yield event.plain_result("[Z-Library] 请使用 /zlib download <id> <hash> 下载。")
            return

        try:
            if not self.zlibrary:
                self.zlibrary = Zlibrary(email=self.config["zlib_email"], password=self.config["zlib_password"])

            # 获取电子书详情，确保 ID 合法
            book_details = self.zlibrary.getBookInfo(book_id, hashid=book_hash)
            if not book_details:
                yield event.plain_result("[Z-Library] 无法获取电子书详情，请检查电子书 ID 是否正确。")
                return

            # 下载电子书
            downloaded_book = self.zlibrary.downloadBook({"id": book_id, "hash": book_hash})
            if downloaded_book:
                book_name, book_content = downloaded_book
                # 构造临时文件路径
                temp_file_path = os.path.join(self.TEMP_PATH, book_name)

                # 保存电子书文件
                with open(temp_file_path, "wb") as file:
                    file.write(book_content)

                # 打印日志确认保存成功
                logger.debug(f"[Z-Library] 文件已下载并保存到临时目录：{temp_file_path}")

                # 提醒用户下载完成
                file = File(name=book_name, file=str(temp_file_path))
                yield event.chain_result([file])
                os.remove(temp_file_path)
            else:
                yield event.plain_result("[Z-Library] 下载电子书时发生错误，请稍后再试。")

        except Exception as e:
            logger.error(f"[Z-Library] Error during book download: {e}")
            yield event.plain_result("[Z-Library] 下载电子书时发生错误，请稍后再试。")

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
    
    @command_group("ebooks")
    def ebooks(self):
        pass
    
    @ebooks.command("help")
    async def show_help(self, event: AstrMessageEvent):
        '''显示 Calibre-Web 插件帮助信息'''
        help_msg = [
            "📚 **ebooks 插件使用指南**",
            "",
            "支持通过多平台（Calibre-Web、Liber3、Z-Library、Archive.org）搜索、下载电子书。",
            "",
            "---",
            "🔧 **命令列表**:",
            "",
            "- **Calibre-Web**:",
            "  - `/calibre search <关键词> [数量]`：搜索 Calibre-Web 中的电子书。例如：`/calibre search Python 20`。",
            "  - `/calibre download <下载链接/书名>`：通过 Calibre-Web 下载电子书。例如：`/calibre download <URL>`。",
            "  - `/calibre recommend <数量>`：随机推荐指定数量的电子书。",
            "",
            "- **Archive.org**:",
            "  - `/archive search <关键词> [数量]`：搜索 Archive.org 电子书。例如：`/archive search Python 20`。",
            "  - `/archive download <下载链接>`：通过 Archive.org 平台下载电子书。",
            "",
            "- **Z-Library**:",
            "  - `/zlib search <关键词> [数量]`：搜索 Z-Library 的电子书。例如：`/zlib search Python 20`。",
            "  - `/zlib download <ID> <Hash>`：通过 Z-Library 平台下载电子书。",
            "",
            "- **Liber3**:",
            "  - `/liber3 search <关键词> [数量]`：搜索 Liber3 平台上的电子书。例如：`/liber3 search Python 20`。",
            "  - `/liber3 download <ID>`：通过 Liber3 平台下载电子书。",
            "",
            "- **通用命令**:",
            "  - `/ebooks help`：显示当前插件的帮助信息。",
            "  - `/ebooks search <关键词> [数量]`：在所有支持的平台中同时搜索电子书。例如：`/ebooks search Python 20`。",
            "  - `/ebooks download <URL/ID> [Hash]`：通用的电子书下载方式。"
            "",
            "---",
            "📒 **注意事项**:",
            "- `数量` 为可选参数，默认为20，用于限制搜索结果的返回数量，数量过大可能导致构造转发消息失败。",
            "- 下载指令要根据搜索结果，提供有效的 URL、ID 和 Hash 值。",
            "- 推荐功能会从现有书目中随机选择书籍进行展示。（仅支持Calibre-Web)",
            "",
            "---",
            "🌐 **支持平台**:",
            "- Calibre-Web",
            "- Liber3",
            "- Z-Library",
            "- Archive.org",
        ]
        yield event.plain_result("\n".join(help_msg))

    @ebooks.command("search")
    async def search_all_platforms(self, event: AstrMessageEvent, query: str = None, limit: str = "20"):
        """
        同时在所有支持的平台中搜索电子书，异步运行，每个平台返回自己的搜索结果格式。
        """
        if not query:
            yield event.plain_result("[ebooks] 请提供电子书关键词以进行搜索。")
            return

        if not (1 <= int(limit) <= 50):  # Validate limit
            yield event.plain_result("[ebooks] 请确认搜索返回结果数量在 1-50 之间。")
            return

        async def consume_generator_async(gen):
            """将异步生成器转化为标准协程并返回结果，以确保类型正确"""
            return [item async for item in gen]

        tasks = []
        if self.config.get("enable_calibre", False):
            tasks.append(consume_generator_async(self.search_calibre(event, query, limit)))
        if self.config.get("enable_liber3", False):
            tasks.append(consume_generator_async(self.search_liber3(event, query, limit)))
        if self.config.get("enable_archive", False):
            tasks.append(consume_generator_async(self.search_archive(event, query, limit)))
        if self.config.get("enable_zlib", False):
            tasks.append(consume_generator_async(self.search_zlib(event, query, limit)))

        try:
            # 并发运行所有任务
            for search_results in asyncio.as_completed(tasks):
                try:
                    # 将任务结果逐一发送
                    for platform_results in search_results:  # 遍历每个平台结果
                        for result in platform_results:  # 遍历具体某个平台的单个结果
                            try:
                                yield result
                            except Exception as e:
                                logger.error(f"[ebooks] 处理结果时出现异常: {e}")
                                continue
                except Exception as e:
                    logger.error(f"[ebooks] 执行任务时出现异常: {e}")

        except Exception as e:
            logger.error(f"[ebooks] Error during multi-platform search: {e}")
            yield event.plain_result(f"[ebooks] 搜索电子书时发生错误，请稍后再试。")

    @ebooks.command("download")
    async def download_all_platforms(self, event: AstrMessageEvent, arg1: str = None, arg2: str = None):
        """
        自动解析并识别输入，调用对应的平台下载实现，完成电子书的下载和发送。

        :param arg1: 主参数，可能是链接、ID 或其他标识符
        :param arg2: 可选参数，用于补充 Z-Library 下载中的 Hash 值
        """
        if not arg1:
            yield event.plain_result("[ebooks] 请提供有效的下载链接、ID 或参数！")
            return

        try:
            # Z-Library 下载 (基于 ID 和 Hash)
            if arg1 and arg2:  # 检查两个参数是否都存在
                try:
                    logger.info("[ebooks] 检测到 Z-Library ID 和 Hash，开始下载...")
                    async for result in self.download_zlib(event, arg1, arg2):
                        yield result
                except Exception as e:
                    yield event.plain_result(f"[ebooks] Z-Library 参数解析失败：{e}")
                return

            # Calibre-Web 下载 (基于 OPDS 链接)
            if arg1.startswith("http://") or arg1.startswith("https://"):
                if "/opds/download/" in arg1:
                    logger.info("[ebooks] 检测到 Calibre-Web 链接，开始下载...")
                    async for result in self.download_calibre(event, arg1):
                        yield result
                    return

                # Archive.org 下载
                if "archive.org/download/" in arg1:
                    logger.info("[ebooks] 检测到 Archive.org 链接，开始下载...")
                    async for result in self.download_archive(event, arg1):
                        yield result
                    return

            # Liber3 下载
            if len(arg1) == 32 and re.match(r"^[A-Fa-f0-9]{32}$", arg1):  # 符合 Liber3 的 ID 格式
                logger.info("[ebooks] ⏳ 检测到 Liber3 ID，开始下载...")
                async for result in self.download_liber3(event, arg1):
                    yield result
                return

            # 未知来源的输入
            yield event.plain_result(
                "[ebooks] 未识别的输入格式，请提供以下格式之一：\n"
                "- Calibre-Web 下载链接\n"
                "- Archive.org 下载链接\n"
                "- Liber3 32位 ID\n"
                "- Z-Library 的 ID 和 Hash"
            )

        except Exception:
            # 捕获并处理运行时错误
            yield event.plain_result(f"[ebooks] 下载电子书时发生错误，请稍后再试。")

    @llm_tool("search_ebooks")
    async def search_ebooks(self, event: AstrMessageEvent, query: str):
        """Search for eBooks across all supported platforms.

        When to use:
            This method performs a unified search across multiple platforms supported by this plugin,
            allowing users to find ebooks by title or keyword.
            Unless a specific platform is explicitly mentioned, this function should be used as the default means for searching books.


        Args:
            query (string): The keyword or book title for searching.
        """
        async for result in self.search_all_platforms(event, query, limit="20"):
            yield result

    @llm_tool("download_ebook")
    async def download_ebook(self, event: AstrMessageEvent, arg1: str, arg2: str = None):
        """Download eBooks by dispatching to the appropriate platform's download method.

        When to use:
            This method facilitates downloading of ebooks by automatically identifying the platform
            from the provided identifier (ID, URL, or Hash), and then calling the corresponding platform's download function.
            Unless the platform is specifically mentioned, this function serves as the default for downloading ebooks.

        Args:
            arg1 (string): Primary identifier, such as a URL or book ID.
            arg2 (string): Secondary input, such as a hash, required for Z-Library downloads.
        """
        async for result in self.download_all_platforms(event, arg1, arg2):
            yield result

    @command("test")
    async def test(self, event: AstrMessageEvent):
        yield event.chain_result([Image.fromURL("https://s3proxy.cdn-zlib.sk/covers400/c ollections/genesis/52f375b13029a198139b8101a6977c9aec5c4ad3e18ff8beaf4ea3c15615db9a.jpg ")])