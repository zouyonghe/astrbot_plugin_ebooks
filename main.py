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

from data.plugins.astrbot_plugin_ebooks.annas_py.models.args import Language
from data.plugins.astrbot_plugin_ebooks.Zlibrary import Zlibrary
from data.plugins.astrbot_plugin_ebooks.annas_py import search as annas_search
from data.plugins.astrbot_plugin_ebooks.annas_py import get_information as get_annas_information
from astrbot.api.all import *
from astrbot.api.event.filter import *

MAX_ZLIB_RETRY_COUNT = 3

@register("ebooks", "buding", "一个功能强大的电子书搜索和下载插件", "1.0.10", "https://github.com/zouyonghe/astrbot_plugin_ebooks")
class ebooks(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.proxy = os.environ.get("https_proxy")
        self.TEMP_PATH = os.path.abspath("data/temp")
        os.makedirs(self.TEMP_PATH, exist_ok=True)

        # 初始化 Calibre 配置
        if self.config.get("enable_calibre", False) and not self.config.get("calibre_web_url", "").strip():
            self.config["enable_calibre"] = False
            self.config.save_config()
            logger.info("[ebooks] 未设置 Calibre-Web URL，禁用该平台。")

        # 初始化 Z-Library 配置
        self.zlibrary = Zlibrary()
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
                self._disable_zlib("未设置 Z-Library 账户，禁用该平台。")

    def _disable_zlib(self, reason: str):
        """禁用 Z-Library 平台并保存配置"""
        self.zlibrary = Zlibrary()
        self.config["enable_zlib"] = False
        self.config.save_config()
        logger.info(f"[ebooks] {reason}")

    async def terminate(self):
        if self.zlibrary and self.zlibrary.isLoggedIn():
            self.zlibrary = Zlibrary()


    async def _is_url_accessible(self, url: str, proxy: bool=True) -> bool:
        """
        异步检查给定的 URL 是否可访问。

        :param url: 要检查的 URL
        :param proxy: 是否使用代理
        :return: 如果 URL 可访问返回 True，否则返回 False
        """
        try:
            async with aiohttp.ClientSession() as session:
                if proxy:
                    async with session.head(url, timeout=5, proxy=self.proxy, allow_redirects=True) as response:
                        return response.status == 200
                else:
                    async with session.head(url, timeout=5, allow_redirects=True) as response:
                        return response.status == 200
        except:
            return False  # 如果请求失败（超时、连接中断等）则返回 False

    async def _download_and_convert_to_base64(self, cover_url):
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
                            return await self._download_and_convert_to_base64(cover_url)
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
                if self._is_base64_image(base64_data):  # 检查 Base64 数据是否有效
                    return base64_data
        except:
            return None

    def _is_base64_image(self, base64_data: str) -> bool:
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

    def _truncate_filename(self, filename, max_length=100):
        # 保留文件扩展名
        base, ext = os.path.splitext(filename)
        if len(filename.encode('utf-8')) > max_length:
            # 根据最大长度截取文件名，确保文件扩展名完整
            truncated = base[:max_length - len(ext.encode('utf-8')) - 7] + " <省略>"
            return f"{truncated}{ext}"
        return filename

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
                title = title_element.text if title_element is not None else "未知"

                # 提取作者，多作者场景
                authors = []
                author_elements = entry.findall("default:author/default:name", namespace)
                for author in author_elements:
                    authors.append(author.text if author is not None else "未知")
                authors = ", ".join(authors) if authors else "未知"

                # 提取描述（<summary>）
                summary_element = entry.find("default:summary", namespace)
                summary = summary_element.text if summary_element is not None else "无描述"

                # 提取出版日期（<published>）
                published_element = entry.find("default:published", namespace)
                #published_date = published_element.text if published_element is not None else "未知出版日期"
                if published_element is not None and published_element.text:
                    try:
                        # 解析日期字符串为 datetime 对象，并提取年份
                        year = datetime.fromisoformat(published_element.text).year
                    except ValueError:
                        year = "未知"  # 日期解析失败时处理
                else:
                    year = "未知"

                # 提取语言（<dcterms:language>），需注意 namespace
                lang_element = entry.find("default:dcterms:language", namespace)
                language = lang_element.text if lang_element is not None else "未知"

                # 提取出版社信息（<publisher>）
                publisher_element = entry.find("default:publisher/default:name", namespace)
                publisher = publisher_element.text if publisher_element is not None else "未知"

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
                    file_type = acquisition_element.attrib.get("type", "未知")
                    file_size = acquisition_element.attrib.get("length", "未知")
                else:
                    download_link = ""
                    file_type = "未知"
                    file_size = "未知"

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

    async def _build_book_chain(self, item: dict) -> list:
        """
        构建对应书籍条目的消息链。

        :param item: 包含书籍信息的字典
        :return: 生成的消息链列表
        """
        chain = [Plain(f"{item['title']}")]
        if item.get("cover_link"):
            base64_image = await self._download_and_convert_to_base64(item["cover_link"])
            if self._is_base64_image(base64_image):
                chain.append(Image.fromBase64(base64_image))
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

    async def _convert_calibre_results_to_nodes(self, event: AstrMessageEvent, results: list):
        if not results:
            return "[Calibre-Web] 未找到匹配的电子书。"

        async def construct_node(book):
            """异步构造单个节点"""
            chain = await self._build_book_chain(book)
            return Node(
                uin=event.get_self_id(),
                name="Calibre-Web",
                content=chain
            )

        tasks = [construct_node(book) for book in results]
        return await asyncio.gather(*tasks)

    async def _search_calibre_nodes(self, event: AstrMessageEvent, query: str, limit: str = "20"):
        if not self.config.get("enable_calibre", False):
            return "[Calibre-Web] 功能未启用。"

        if not query:
            return "[Calibre-Web] 请提供电子书关键词以进行搜索。"

        limit = int(limit) if limit.isdigit() else 20
        if not (1 <= limit <= 100):  # Validate limit
            return "[Calibre-Web] 请确认搜索返回结果数量在 1-100 之间。"

        try:
            logger.info(f"[Calibre-Web] Received books search query: {query}, limit: {limit}")
            results = await self._search_calibre_web(quote_plus(query), limit)  # 调用搜索方法
            if not results or len(results) == 0:
                return "[Calibre-Web] 未找到匹配的电子书。"
            else:
                return await self._convert_calibre_results_to_nodes(event, results)
        except Exception as e:
            logger.error(f"[Calibre-Web] 搜索失败: {e}")
            return "Calibre-Web] 搜索失败，请检查控制台输出"

    def _is_valid_calibre_book_url(self, book_url: str) -> bool:
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
        """搜索 calibre-web 电子书"""
        result = await self._search_calibre_nodes(event, query, limit)
        if isinstance(result, str):
            yield event.plain_result(result)
        elif isinstance(result, list):
            if len(result) <= 30:
                ns = Nodes(result)
                yield event.chain_result([ns])
            else:
                ns = Nodes([])
                for i in range(0, len(result), 30):  # 每30条数据分割成一个node
                    chunk_results = result[i:i + 30]
                    node = Node(
                        uin=event.get_self_id(),
                        name="Calibre-Web",
                        content=chunk_results,
                    )
                    ns.nodes.append(node)
                yield event.chain_result([ns])
        else:
            raise ValueError("Unknown result type.")

    @calibre.command("download")
    async def download_calibre(self, event: AstrMessageEvent, book_url: str = None):
        """下载 calibre-web 电子书"""
        if not self.config.get("enable_calibre", False):
            yield event.plain_result("[Calibre-Web] 功能未启用。")
            return

        if not self._is_valid_calibre_book_url(book_url):
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
            result = await self._convert_calibre_results_to_nodes(event, recommended_books)

            if isinstance(result, str):
                yield event.plain_result(result)
            elif isinstance(result, list):
                guidance = f"[Calibre-Web] 如下是随机推荐的 {n} 本电子书。"
                nodes = [Node(uin=event.get_self_id(), name="Calibre-Web", content=guidance)]
                nodes.extend(result)
                ns = Nodes([])
                ns.nodes = nodes
                yield event.chain_result([ns])
            else:
                yield event.plain_result("[Calibre-Web] 生成结果失败。")

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
            
    async def _get_liber3_book_details(self, book_ids: list) -> Optional[dict]:
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
    
    async def _search_liber3_books_with_details(self, word: str, limit: int = 50) -> Optional[dict]:
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
                        detailed_books = await self._get_liber3_book_details(book_ids)
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

    async def _search_liber3_nodes(self, event: AstrMessageEvent, query: str, limit: str = "20"):
        # 检查功能是否启用
        if not self.config.get("enable_liber3", False):
            return "[Liber3] 功能未启用。"

        # 检查是否提供查询关键词
        if not query:
            return "[Liber3] 请提供电子书关键词以进行搜索。"

        # 校验 limit 参数
        limit = int(limit) if limit.isdigit() else 20
        if not (1 <= limit <= 100):  # 确保返回的结果数量有效
            return "[Liber3] 请确认搜索返回结果数量在 1-100 之间。"

        try:
            # 打印日志
            logger.info(f"[Liber3] Received books search query: {query}, limit: {limit}")

            # 通过 Liber3 API 搜索获得结果
            results = await self._search_liber3_books_with_details(query, limit)
            if not results:
                return "[Liber3] 未找到匹配的电子书。"

            # 提取搜索结果和详细信息
            search_results = results.get("search_results", [])
            detailed_books = results.get("detailed_books", {})

            async def construct_node(book):
                """异步构造单个节点"""
                book_id = book.get("id")
                detail = detailed_books.get(book_id, {}).get("book", {})

                # 构建电子书信息内容
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

                # 构造节点
                return Node(
                    uin=event.get_self_id(),
                    name="Liber3",
                    content=chain
                )
            tasks = [construct_node(book) for book in search_results]
            return await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"[Liber3] 搜索失败: {e}")
            return "[Liber3] 发生错误，请稍后再试。"

    def _is_valid_liber3_book_id(self, book_id: str) -> bool:
        """检测 Liber3 的 book_id 是否有效"""
        if not book_id:
            return False  # 不能为空

        # 使用正则表达式验证是否是以 L 开头后接 32 位十六进制字符串
        pattern = re.compile(r'^L[a-fA-F0-9]{32}$')
        return bool(pattern.match(book_id))

    @command_group("liber3")
    def liber3(self):
        pass

    @liber3.command("search")
    async def search_liber3(self, event: AstrMessageEvent, query: str = None, limit: str="20"):
        """搜索 Liber3 电子书"""
        result = await self._search_liber3_nodes(event, query, limit)

        # 根据返回值类型处理结果
        if isinstance(result, str):
            yield event.plain_result(result)
        elif isinstance(result, list):
            if len(result) <= 30:
                ns = Nodes(result)
                yield event.chain_result([ns])
            else:
                ns = Nodes([])
                for i in range(0, len(result), 30):  # 每30条数据分割成一个node
                    chunk_results = result[i:i + 30]
                    node = Node(
                        uin=event.get_self_id(),
                        name="Liber3",
                        content=chunk_results,
                    )
                    ns.nodes.append(node)
                yield event.chain_result([ns])
        else:
            raise ValueError("Unknown result type.")

    @liber3.command("download")
    async def download_liber3(self, event: AstrMessageEvent, book_id: str = None):
        """下载 liber3 电子书"""

        if not self.config.get("enable_liber3", False):
            yield event.plain_result("[Liber3] 功能未启用。")
            return

        if not self._is_valid_liber3_book_id(book_id):
            yield event.plain_result("[Liber3] 请提供有效的电子书 ID。")
            return

        book_id = book_id.lstrip("L")

        # 获取详细的电子书信息
        book_details = await self._get_liber3_book_details([book_id])
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
        """Search for eBooks through the archive.org API and filter files in PDF or EPUB formats.
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
            # 1. 调用 archive.org 搜索 API
            response = await session.get(base_search_url, params=params, proxy=self.proxy)
            if response.status != 200:
                logger.error(
                    f"[archive.org] Error during search: archive.org API returned status code {response.status}")
                return []

            result_data = await response.json()
            docs = result_data.get("response", {}).get("docs", [])
            if not docs:
                logger.info("[archive.org] 未找到匹配的电子书。")
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
            logger.error(f"[archive.org] 获取 Metadata 数据时发生错误: {e}")
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

    def _is_valid_archive_book_url(self, book_url: str) -> bool:
        """检测 archive.org 下载链接格式是否合法"""
        if not book_url:
            return False  # URL 不能为空

        # 使用正则表达式验证链接格式是否合法
        pattern = re.compile(
            r'^https://archive\.org/download/[^/]+/[^/]+$'
        )

        return bool(pattern.match(book_url))

    async def _search_archive_nodes(self, event: AstrMessageEvent, query: str = None, limit: str = "20"):
        if not self.config.get("enable_archive", False):
            return "[archive.org] 功能未启用。"

        if not query:
            return "[archive.org] 请提供电子书关键词以进行搜索。"

        if not await self._is_url_accessible("https://archive.org"):
            return "[archive.org] 无法连接到 archive.org。"

        limit = int(limit) if limit.isdigit() else 20
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
                """异步构造单个节点"""
                chain = [Plain(f"{book.get('title', '未知')}")]

                # 异步下载和处理封面图片
                if book.get("cover"):
                    base64_image = await self._download_and_convert_to_base64(book.get("cover"))
                    if base64_image and self._is_base64_image(base64_image):
                        chain.append(Image.fromBase64(base64_image))
                    else:
                        chain.append(Plain("\n"))
                else:
                    chain.append(Plain("\n"))

                # 添加其他信息
                chain.append(Plain(f"作者: {book.get('authors', '未知')}\n"))
                chain.append(Plain(f"年份: {book.get('year', '未知')}\n"))
                chain.append(Plain(f"出版社: {book.get('publisher', '未知')}\n"))
                chain.append(Plain(f"语言: {book.get('language', '未知')}\n"))
                chain.append(Plain(f"简介: {book.get('description', '无简介')}\n"))
                chain.append(Plain(f"链接(用于下载): {book.get('download_url', '未知')}"))

                # 构造 Node
                return Node(
                    uin=event.get_self_id(),
                    name="archive.org",
                    content=chain
                )
            tasks = [construct_node(book) for book in results]
            return await asyncio.gather(*tasks)  # 并发执行所有任务

            # return nodes
        except Exception as e:
            logger.error(f"[archive.org] Error processing archive.org search request: {e}")
            return "[archive.org] 搜索电子书时发生错误，请稍后再试。"

    @command_group("archive")
    def archive(self):
        pass

    @archive.command("search")
    async def search_archive(self, event: AstrMessageEvent, query: str = None, limit: str = "20"):
        """搜索 archive.org 电子书"""
        result = await self._search_archive_nodes(event, query, limit)

        # 根据返回值类型处理结果
        if isinstance(result, str):
            yield event.plain_result(result)
        elif isinstance(result, list):
            if len(result) <= 30:
                ns = Nodes(result)
                yield event.chain_result([ns])
            else:
                ns = Nodes([])
                for i in range(0, len(result), 30):  # 每30条数据分割成一个node
                    chunk_results = result[i:i + 30]
                    node = Node(
                        uin=event.get_self_id(),
                        name="archive.org",
                        content=chunk_results,
                    )
                    ns.nodes.append(node)
                yield event.chain_result([ns])
        else:
            raise ValueError("Unknown result type.")

    @archive.command("download")
    async def download_archive(self, event: AstrMessageEvent, book_url: str = None):
        """下载 archive.org 电子书"""
        if not self.config.get("enable_archive", False):
            yield event.plain_result("[archive.org] 功能未启用。")
            return

        if not self._is_valid_archive_book_url(book_url):
            yield event.plain_result("[archive.org] 请提供有效的下载链接。")
            return

        if not await self._is_url_accessible("https://archive.org"):
            yield event.plain_result("[archive.org] 无法连接到 archive.org")
            return

        try:
            async with aiohttp.ClientSession() as session:
                # 发出 GET 请求并跟随跳转
                async with session.get(book_url, allow_redirects=True, proxy=self.proxy, timeout=300) as response:
                    if response.status == 200:
                        ebook_url = str(response.url)
                        logger.debug(f"[archive.org] 跳转后的下载地址: {ebook_url}")

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

                        book_name = self._truncate_filename(book_name)

                        # 构造临时文件路径
                        temp_file_path = os.path.join(self.TEMP_PATH, book_name)

                        # 保存下载文件到本地
                        async with aiofiles.open(temp_file_path, "wb") as temp_file:
                            await temp_file.write(await response.read())

                        # 打印日志确认保存成功
                        logger.info(f"[archive.org] 文件已下载并保存到临时目录：{temp_file_path}")

                        # 直接传递本地文件路径
                        file = File(name=book_name, file=temp_file_path)
                        yield event.chain_result([file])
                        os.remove(temp_file_path)

                        # file = File(name=book_name, file=ebook_url)
                        # yield event.chain_result([file])
                    else:
                        yield event.plain_result(f"[archive.org] 无法下载电子书，状态码: {response.status}")
        except Exception as e:
            logger.error(f"[archive.org] 下载失败: {e}")
            yield event.plain_result(f"[archive.org] 下载电子书时发生错误，请稍后再试。")

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

    async def _search_zlib_nodes(self,event: AstrMessageEvent, query: str, limit: str = "20"):
        if not self.config.get("enable_zlib", False):
            return "[Z-Library] 功能未启用。"

        if not await self._is_url_accessible("https://z-library.sk"):
            return "[Z-Library] 无法连接到 Z-Library。"

        if not query:
            return "[Z-Library] 请提供电子书关键词以进行搜索。"

        limit = int(limit) if limit.isdigit() else 20
        if limit < 1:
            return "[Z-Library] 请确认搜索返回结果数量在 1-60 之间。"
        if limit > 60:
            limit = 60

        try:
            logger.info(f"[Z-Library] Received books search query: {query}, limit: {limit}")

            if not self.zlibrary.isLoggedIn():
                email = self.config.get("zlib_email", "").strip()
                password = self.config.get("zlib_password", "").strip()
                retry_count = 0
                while retry_count < MAX_ZLIB_RETRY_COUNT:
                    try:
                        self.zlibrary.login(email, password)  # 尝试登录
                        if self.zlibrary.isLoggedIn():  # 检查是否登录成功
                            break
                    except:  # 捕获登录过程中的异常
                        pass
                    retry_count += 1  # 增加重试计数
                    if retry_count >= MAX_ZLIB_RETRY_COUNT:  # 超过最大重试次数
                        return "[Z-Library] 登录失败。"

            # 调用 Zlibrary 的 search 方法进行搜索
            results = self.zlibrary.search(message=query, limit=limit)

            if not results or not results.get("books"):
                return "[Z-Library] 未找到匹配的电子书。"

            # 处理搜索结果
            books = results.get("books", [])
            async def construct_node(book):
                """异步构造单个节点"""
                chain = [Plain(f"{book.get('title', '未知')}")]

                # 异步处理封面图片
                if book.get("cover"):
                    base64_image = await self._download_and_convert_to_base64(book.get("cover"))
                    if base64_image and self._is_base64_image(base64_image):
                        chain.append(Image.fromBase64(base64_image))
                    else:
                        chain.append(Plain("\n"))
                else:
                    chain.append(Plain("\n"))

                # 添加书籍信息
                chain.append(Plain(f"作者: {book.get('author', '未知')}\n"))
                chain.append(Plain(f"年份: {book.get('year', '未知')}\n"))

                # 处理出版社信息
                publisher = book.get("publisher", None)
                if not publisher or publisher == "None":
                    publisher = "未知"
                chain.append(Plain(f"出版社: {publisher}\n"))

                # 语言信息
                chain.append(Plain(f"语言: {book.get('language', '未知')}\n"))

                # 处理简介
                description = book.get("description", "无简介")
                if isinstance(description, str) and description.strip() != "":
                    description = description.strip()
                    description = description[:150] + "..." if len(description) > 150 else description
                else:
                    description = "无简介"
                chain.append(Plain(f"简介: {description}\n"))

                # ID 和 Hash 信息
                chain.append(Plain(f"ID(用于下载): {book.get('id')}\n"))
                chain.append(Plain(f"Hash(用于下载): {book.get('hash')}"))

                # 构造节点
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

    def _is_valid_zlib_book_id(self, book_id: str) -> bool:
        """检测 zlib ID 是否为纯数字"""
        if not book_id:
            return False
        return book_id.isdigit()

    def _is_valid_zlib_book_hash(self, hash: str) -> bool:
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
        """搜索 Zlibrary 电子书"""
        result = await self._search_zlib_nodes(event, query, limit)

        # 根据返回值类型处理结果
        if isinstance(result, str):
            yield event.plain_result(result)
        elif isinstance(result, list):
            if len(result) <= 30:
                ns = Nodes(result)
                yield event.chain_result([ns])
            else:
                ns = Nodes([])
                for i in range(0, len(result), 30):  # 每30条数据分割成一个node
                    chunk_results = result[i:i + 30]
                    node = Node(
                        uin=event.get_self_id(),
                        name="Z-Library",
                        content=chunk_results,
                    )
                    ns.nodes.append(node)
                yield event.chain_result([ns])
        else:
            raise ValueError("Unknown result type.")

    @zlib.command("download")
    async def download_zlib(self, event: AstrMessageEvent, book_id: str = None, book_hash: str = None):
        """下载 Z-Library 电子书"""
        if not self.config.get("enable_zlib", False):
            yield event.plain_result("[Z-Library] 功能未启用。")
            return

        if not self._is_valid_zlib_book_id(book_id) or not self._is_valid_zlib_book_hash(book_hash):
            yield event.plain_result("[Z-Library] 请使用 /zlib download <id> <hash> 下载。")
            return

        if not await self._is_url_accessible("https://z-library.sk"):
            yield event.plain_result("[Z-Library] 无法连接到 Z-Library。")
            return

        try:
            if not self.zlibrary.isLoggedIn():
                email = self.config.get("zlib_email", "").strip()
                password = self.config.get("zlib_password", "").strip()
                retry_count = 0
                while retry_count < MAX_ZLIB_RETRY_COUNT:
                    try:
                        self.zlibrary.login(email, password)  # 尝试登录
                        if self.zlibrary.isLoggedIn():  # 检查是否登录成功
                            break
                    except:  # 捕获登录过程中的异常
                        pass
                    retry_count += 1  # 增加重试计数
                    if retry_count >= MAX_ZLIB_RETRY_COUNT:  # 超过最大重试次数
                        yield event.plain_result("[Z-Library] 登录失败。")
                        return

            # 获取电子书详情，确保 ID 合法
            book_details = self.zlibrary.getBookInfo(book_id, hashid=book_hash)
            if not book_details:
                yield event.plain_result("[Z-Library] 无法获取电子书详情，请检查电子书 ID 是否正确。")
                return

            # 下载电子书
            downloaded_book = self.zlibrary.downloadBook({"id": book_id, "hash": book_hash})
            if downloaded_book:
                book_name, book_content = downloaded_book
                book_name = self._truncate_filename(book_name)

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

    async def _search_annas_nodes(self, event: AstrMessageEvent, query: str, limit: str = "20"):
        if not self.config.get("enable_annas", False):
            return "[Anna's Archive] 功能未启用。"

        if not await self._is_url_accessible("https://annas-archive.org"):
            return "[Anna's Archive] 无法连接到 Anna's Archive。"

        if not query:
            return "[Anna's Archive] 请提供电子书关键词以进行搜索。"

        limit = int(limit) if limit.isdigit() else 20
        if limit < 1:
            return "[Anna's Archive] 请确认搜索返回结果数量在 1-60 之间。"
        if limit > 60:
            limit = 60

        try:
            logger.info(f"[Anna's Archive] Received books search query: {query}, limit: {limit}")

            # 调用 annas_search 查询
            results = annas_search(query, Language.ZH)
            if not results or len(results) == 0:
                return "[Anna's Archive] 未找到匹配的电子书。"

            # 处理搜索结果
            books = results[:limit]  # 截取前 limit 条结果

            async def construct_node(book):
                """异步构造单个节点"""
                chain = [Plain(f"{book.title}\n")]

                # 异步处理封面图片
                if book.thumbnail:
                    base64_image = await self._download_and_convert_to_base64(book.thumbnail)
                    if base64_image and self._is_base64_image(base64_image):
                        chain.append(Image.fromBase64(base64_image))
                    else:
                        chain.append(Plain("\n"))
                else:
                    chain.append(Plain("\n"))

                # 添加书籍信息
                chain.append(Plain(f"作者: {book.authors or '未知'}\n"))
                chain.append(Plain(f"出版社: {book.publisher or '未知'}\n"))
                chain.append(Plain(f"年份: {book.publish_date or '未知'}\n"))

                # 语言信息
                language = book.file_info.language if book.file_info else "未知"
                chain.append(Plain(f"语言: {language}\n"))

                # 附加文件信息
                extension = book.file_info.extension if book.file_info else "未知"
                chain.append(Plain(f"格式: {extension}\n"))

                # ID 信息
                chain.append(Plain(f"ID: A{book.id}"))

                # 构造最终节点
                return Node(
                    uin=event.get_self_id(),
                    name="Anna's Archive",
                    content=chain,
                )

            # 遍历所有书籍，构造节点任务
            tasks = [construct_node(book) for book in books]
            return await asyncio.gather(*tasks)

        except Exception as e:
            logger.error(f"[Anna's Archive] Error during book search: {e}")
            return "[Anna's Archive] 搜索电子书时发生错误，请稍后再试。"

    def _is_valid_annas_book_id(self, book_id: str) -> bool:
        """检测 Liber3 的 book_id 是否有效"""
        if not book_id:
            return False  # 不能为空

        # 使用正则表达式验证是否是以 A 开头后接 32 位十六进制字符串
        pattern = re.compile(r'^A[a-fA-F0-9]{32}$')
        return bool(pattern.match(book_id))

    @command_group("annas")
    def annas(self):
        pass

    @annas.command("search")
    async def search_annas(self, event: AstrMessageEvent, query: str, limit: str = "20"):
        """搜索 anna's archive 电子书"""
        result = await self._search_annas_nodes(event, query, limit)

        # 根据返回值类型处理结果
        if isinstance(result, str):
            yield event.plain_result(result)
        elif isinstance(result, list):
            if len(result) <= 30:
                ns = Nodes(result)
                yield event.chain_result([ns])
            else:
                ns = Nodes([])
                for i in range(0, len(result), 30):  # 每30条数据分割成一个node
                    chunk_results = result[i:i + 30]
                    node = Node(
                        uin=event.get_self_id(),
                        name="anna's archive",
                        content=chunk_results,
                    )
                    ns.nodes.append(node)
                yield event.chain_result([ns])
        else:
            raise ValueError("Unknown result type.")

    @annas.command("download")
    async def download_annas(self, event: AstrMessageEvent, book_id: str = None):
        """从 Anna's Archive 下载电子书"""
        if not self.config.get("enable_annas", False):
            yield event.plain_result("[Anna's Archive] 功能未启用。")
            return

        if not book_id:
            yield event.plain_result("[Anna's Archive] 请提供有效的书籍 ID。")
            return

        try:
            book_id = book_id.lstrip("A")
            # 获取 Anna's Archive 的书籍信息
            book_info = get_annas_information(book_id)
            urls = book_info.urls

            if not urls:
                yield event.plain_result("[Anna's Archive] 未找到任何下载链接！")
                return

            chain = [Plain("Anna's Archive\n目前无法直接下载电子书，可以通过访问下列链接手动下载：")]

            # 快速链接（需要付费）
            fast_links = [url for url in urls if "Fast Partner Server" in url.title]
            if fast_links:
                chain.append(Plain("\n快速链接（需要付费）：\n"))
                for index, url in enumerate(fast_links, 1):
                    chain.append(Plain(f"{index}. {url.url}\n"))

            # 慢速链接（需要等待）
            slow_links = [url for url in urls if "Slow Partner Server" in url.title]
            if slow_links:
                chain.append(Plain("\n慢速链接（需要等待）：\n"))
                for index, url in enumerate(slow_links, 1):
                    chain.append(Plain(f"{index}. {url.url}\n"))

            # 第三方链接
            other_links = [url for url in urls if
                           "Fast Partner Server" not in url.title and "Slow Partner Server" not in url.title]
            if other_links:
                chain.append(Plain("\n第三方链接：\n"))
                for index, url in enumerate(other_links, 1):
                    chain.append(Plain(f"{index}. {url.url}\n"))

            yield event.chain_result([Node(uin=event.get_self_id(), name="Anna's Archive", content=chain)])

        except Exception as e:
            logger.error(f"[Anna's Archive] 下载失败：{e}")
            yield event.plain_result(f"[Anna's Archive] 下载电子书时发生错误，请稍后再试：{e}")


    @command_group("ebooks")
    def ebooks(self):
            pass
    
    @ebooks.command("help")
    async def show_help(self, event: AstrMessageEvent):
        '''显示 Calibre-Web 插件帮助信息'''
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
            "  - `/ebooks download <URL/ID> [Hash]`：通用的电子书下载方式。"
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
    async def search_all_platforms(self, event: AstrMessageEvent, query: str = None, limit: str = "20"):
        """
        同时在所有支持的平台中搜索电子书，异步运行，每个平台返回自己的搜索结果格式。
        """
        if not query:
            yield event.plain_result("[ebooks] 请提供电子书关键词以进行搜索。")
            return

        if not (1 <= int(limit) <= 100):  # Validate limit
            yield event.plain_result("[ebooks] 请确认搜索返回结果数量在 1-100 之间。")
            return

        async def consume_async(coro_or_gen):
            """兼容协程或异步生成器"""
            if hasattr(coro_or_gen, "__aiter__"):  # 如果是异步生成器
                return [item async for item in coro_or_gen]
            # 普通协程直接返回
            return await coro_or_gen

        tasks = []
        if self.config.get("enable_calibre", False):
            tasks.append(consume_async(self._search_calibre_nodes(event, query, limit)))
        if self.config.get("enable_liber3", False):
            tasks.append(consume_async(self._search_liber3_nodes(event, query, limit)))
        if self.config.get("enable_archive", False):
            tasks.append(consume_async(self._search_archive_nodes(event, query, limit)))
        if self.config.get("enable_zlib", False):
            tasks.append(consume_async(self._search_zlib_nodes(event, query, limit)))
        if self.config.get("enable_annas", False):
            tasks.append(consume_async(self._search_annas_nodes(event, query, limit)))

        try:
            # 并发运行所有任务
            search_results = await asyncio.gather(*tasks)
            # 将任务结果逐一发送
            ns = Nodes([])

            for platform_results in search_results:  # 遍历每个平台结果
                if isinstance(platform_results, str):
                    node = Node(
                        uin=event.get_self_id(),
                        name="ebooks",
                        content=[Plain(platform_results)],
                    )
                    ns.nodes.append(node)
                    continue
                for i in range(0, len(platform_results), 30):  # 每30条数据分割成一个node
                    # 创建新的 node 包含不超过 20 条结果
                    chunk_results = platform_results[i:i + 30]
                    node = Node(
                        uin=event.get_self_id(),
                        name="ebooks",
                        content=chunk_results,
                    )
                    ns.nodes.append(node)
            yield event.chain_result([ns])

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

                # archive.org 下载
                if "archive.org/download/" in arg1:
                    logger.info("[ebooks] 检测到 archive.org 链接，开始下载...")
                    async for result in self.download_archive(event, arg1):
                        yield result
                    return

            # Liber3 下载
            if len(arg1) == 33 and re.match(r"^L[A-Fa-f0-9]{32}$", arg1):
                logger.info("[ebooks] ⏳ 检测到 Liber3 ID，开始下载...")
                async for result in self.download_liber3(event, arg1):
                    yield result
                return

            # Annas Archive 下载
            if len(arg1) == 33 and re.match(r"^A[A-Fa-f0-9]{32}$", arg1):
                logger.info("[ebooks] ⏳ 检测到 Annas Archive ID，开始下载...")
                async for result in self.download_annas(event, arg1):
                    yield result
                return

            # 未知来源的输入
            yield event.plain_result(
                "[ebooks] 未识别的输入格式，请提供以下格式之一：\n"
                "- Calibre-Web 下载链接\n"
                "- archive.org 下载链接\n"
                "- Liber3/Annas Archive 32位 ID\n"
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
