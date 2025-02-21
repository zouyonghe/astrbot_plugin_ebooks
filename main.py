import random
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus, urljoin, unquote

import aiohttp

from astrbot.api.all import *
from astrbot.api.event.filter import *


@register("opds", "buding", "一个基于OPDS的电子书搜索和下载插件", "1.0.0", "https://github.com/zouyonghe/astrbot_plugin_opds")
class OPDS(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config

    async def _show_result(self, event: AstrMessageEvent, results: list, guidance: str = None):
        if not results:
            yield event.plain_result("未找到相关的电子书。")

        if not guidance:
            chain = []
        else:
            chain = [
                Plain(guidance),
            ]
        if len(results) == 1:
            item = results[0]
            chain.append(
                Plain(f"{item['title']}")
            )
            if item.get("cover_link"):
                chain.append(Image.fromURL(item["cover_link"]))
            else:
                chain.append(Plain("\n"))
            chain.append(Plain(f"作者: {item.get('authors', '未知作者')}"))
            chain.append(Plain(f"\n描述: {item.get('summary', '暂无描述')}"))
            chain.append(Plain(f"\n链接: {item['download_link']}"))
            yield event.chain_result(chain)

        else:
            for idx, item in enumerate(results):
                if idx > 0:  # 从第二个项目开始，每项之间空一行
                    chain.append(Plain("\n\n"))

                chain.append(
                    Plain(f"{item['title']}")
                )
                if item.get("cover_link"):
                    chain.append(Image.fromURL(item["cover_link"]))
                else:
                    chain.append(Plain("\n"))
                chain.append(Plain(f"链接: {item['download_link']}"))

            node = Node(
                uin=event.get_self_id(),
                name="OPDS",
                content=chain
            )
            yield event.chain_result([node])
            # nodes = [Node(uin=event.get_self_id(), name="OPDS", content=guidance)]
            #
            # for idx, item in enumerate(results):
            #     chain = [Plain(f"{idx + 1}. {item['title']}")]
            #     if item.get("cover_link"):
            #         chain.append(Image.fromURL(item["cover_link"]))
            #     chain.append(Plain(f"\n作者: {item.get('authors', '未知作者')}"))
            #     chain.append(Plain(f"\n描述: {item.get('summary', '暂无描述')}"))
            #     chain.append(Plain(f"\n链接: {item['download_link']}"))
            #
            #     node = Node(
            #         uin=event.get_self_id(),
            #         name="OPDS",
            #         content=chain
            #     )
            #     nodes.append(node)
            # yield event.chain_result(nodes)


            # chunk_size = 1  # 每个 node 包含的最大项数
            # nodes = []  # 用于存储所有生成的 node
            # 按 chunk 分割 results 数据
            # for i in range(0, len(results), chunk_size):
            #     chunk = results[i:i + chunk_size]  # 分割数据
            #     chain = [
            #         Plain(f"{guidance}"),
            #     ]
            #     for idx, item in enumerate(chunk):
            #         chain.append(
            #             Plain(f"\n{i + idx + 1}. {item['title']}")  # 注意索引保持全局编号
            #         )
            #         if item.get("cover_link"):
            #             chain.append(Image.fromURL(item["cover_link"]))
            #         else:
            #             chain.append(Plain("\n"))
            #         chain.append(Plain(f"作者: {item.get('authors', '未知作者')}"))
            #         chain.append(Plain(f"\n描述: {item.get('summary', '暂无描述')}"))
            #         chain.append(Plain(f"\n链接: {item['download_link']}\n"))
            #
            #     # 创建一个独立的 node
            #     node = Node(
            #         uin=event.get_self_id(),
            #         name="OPDS",
            #         content=chain
            #     )
            #     nodes.append(node)
            # yield event.chain_result(nodes)

    def to_string(self, results: list) -> str:
        """
        将结果列表中的所有项目拼接为字符串。

        Args:
            results (list): 包含字典的结果列表，其中每个字典表示一个条目。

        Returns:
            str: 拼接后的总字符串表示结果。
        """
        if not results:
            return "没有找到结果。"

        result_strings = []
        for item in results:
            part = f"标题: {item.get('title', '未知标题')}\n"
            part += f"作者: {item.get('authors', '未知作者')}\n"
            part += f"描述: {item.get('summary', '暂无描述')}\n"
            part += f"链接: {item.get('download_link', '无下载链接')}\n"
            result_strings.append(part)

        return "\n\n".join(result_strings)

    @command_group("opds")
    def opds(self):
        pass

    @opds.command("search")
    async def search(self, event: AstrMessageEvent, query: str=None):
        '''搜索 OPDS 电子书目录'''
        if not query:
            yield event.plain_result("请输入搜索关键词。")
            return

        try:
            results = await self._search_opds(quote_plus(query))  # 调用搜索方法
            if not results or len(results) == 0:
                yield event.plain_result("未找到相关的电子书。")
            else:
                async for result in self._show_result(event, results):
                    yield result
        except Exception as e:
            logger.error(f"OPDS搜索失败: {e}")
            yield event.plain_result("搜索过程中出现错误，请稍后重试。")

    async def _search_opds(self, query: str, limit: int = None):
        '''调用 OPDS 目录 API 进行电子书搜索'''
        opds_url = self.config.get("opds_url", "http://127.0.0.1:8083")
        search_url = f"{opds_url}/opds/search/{query}"  # 根据实际路径构造 API URL

        async with aiohttp.ClientSession() as session:
            async with session.get(search_url) as response:
                if response.status == 200:
                    content_type = response.headers.get("Content-Type", "")
                    if "application/atom+xml" in content_type:
                        data = await response.text()
                        return self._parse_opds_response(data, limit)  # 调用解析方法
                    else:
                        logger.error(f"Unexpected content type: {content_type}")
                        return None
                else:
                    logger.error(f"OPDS搜索失败，状态码: {response.status}")
                    return None

    def _parse_opds_response(self, xml_data: str, limit: int = None):
        '''解析 OPDS 搜索结果 XML 数据'''
        opds_url = self.config.get("opds_url", "http://127.0.0.1:8083")

        # 移除非法字符
        xml_data = re.sub(r'[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD]', '', xml_data)
        # 消除多余空格
        xml_data = re.sub(r'\s+', ' ', xml_data)

        try:
            root = ET.fromstring(xml_data)  # 把 XML 转换为元素树
            namespace = {"default": "http://www.w3.org/2005/Atom"}  # 定义命名空间
            entries = root.findall("default:entry", namespace)  # 查找前20个 <entry> 节点

            results = []
            for entry in entries:
                # 提取书籍标题
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
                published_date = published_element.text if published_element is not None else "未知出版日期"

                # 提取语言（<dcterms:language>），需注意 namespace
                lang_element = entry.find("default:dcterms:language", namespace)
                language = lang_element.text if lang_element is not None else "未知语言"

                # 提取图书封面链接（rel="http://opds-spec.org/image"）
                cover_element = entry.find("default:link[@rel='http://opds-spec.org/image']", namespace)
                cover_suffix = cover_element.attrib.get("href", "") if cover_element is not None else ""
                if cover_suffix and re.match(r"^/opds/cover/\d+$", cover_suffix):
                    cover_link = urljoin(opds_url, cover_suffix)
                else:
                    cover_link = ""

                # 提取图书缩略图链接（rel="http://opds-spec.org/image/thumbnail"）
                thumbnail_element = entry.find("default:link[@rel='http://opds-spec.org/image/thumbnail']", namespace)
                thumbnail_suffix = thumbnail_element.attrib.get("href", "") if thumbnail_element is not None else ""
                if thumbnail_suffix and re.match(r"^/opds/cover/\d+$", thumbnail_suffix):
                    thumbnail_link = urljoin(opds_url, thumbnail_suffix)
                else:
                    thumbnail_link = ""

                # 提取下载链接及其格式（rel="http://opds-spec.org/acquisition"）
                acquisition_element = entry.find("default:link[@rel='http://opds-spec.org/acquisition']", namespace)
                if acquisition_element is not None:
                    download_suffix = acquisition_element.attrib.get("href", "") if acquisition_element is not None else ""
                    if download_suffix and re.match(r"^/opds/download/\d+/[\w]+/$", download_suffix):
                        download_link = urljoin(opds_url, download_suffix)
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
                    "published_date": published_date,
                    "language": language,
                    "cover_link": cover_link,
                    "thumbnail_link": thumbnail_link,
                    "download_link": download_link,
                    "file_type": file_type,
                    "file_size": file_size
                })

            return results[:limit]
        except ET.ParseError as e:
            logger.error(f"解析 OPDS 响应失败: {e}")
            return None

    @opds.command("help")
    async def show_help(self, event: AstrMessageEvent):
        '''显示 OPDS 插件帮助信息'''
        help_msg = [
            "📚 OPDS 插件使用指南",
            "该插件通过标准的 OPDS 协议与电子书目录交互，支持搜索、下载和推荐功能。",
            "",
            "🔧 **命令列表**:",
            "- `/opds search [关键词]`：搜索 OPDS 目录中的电子书。例如：`/opds search Python`。",
            "- `/opds download [下载链接/书名]`：通过 OPDS 直接下载电子书。例如：`/opds download http://example.com/path/to/book`。",
            "- `/opds recommend [数量]`：随机推荐指定数量的电子书。例如：`/opds recommend 5`。",
            "- `/opds help`：显示当前插件的帮助信息（即此内容）。",
            "",
            "📒 **注意事项**:",
            "- 下载指令支持直接输入电子书的下载链接或通过精确书名匹配来下载。",
            "- 使用推荐功能时，插件会从现有书目中随机选择书籍。",
        ]
        yield event.plain_result("\n".join(help_msg))

    @opds.command("download")
    async def download(self, event: AstrMessageEvent, ebook_url: str = None):
        '''通过 OPDS 协议下载电子书'''
        if not ebook_url:
            yield event.plain_result("请输入电子书的下载链接。")
            return

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(ebook_url) as response:
                    if response.status == 200:
                        # 从 Content-Disposition 提取文件名
                        content_disposition = response.headers.get("Content-Disposition")
                        book_name = None

                        if content_disposition:
                            logger.debug(f"Content-Disposition: {content_disposition}")

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
                            logger.error(f"无法提取书名，电子书地址: {ebook_url}")
                            yield event.plain_result("无法提取书名，取消发送电子书。")
                            return 
                            
                        # 发送文件到用户
                        file = File(name=book_name, file=ebook_url)
                        yield event.chain_result([file])
                    else:
                        yield event.plain_result(f"无法下载电子书，状态码: {response.status}")
        except Exception as e:
            logger.error(f"下载失败: {e}")
            yield event.plain_result("下载过程中出现错误，请稍后重试。")

    @opds.command("recommend")
    async def recommend(self, event: AstrMessageEvent, n: int):
        '''随机推荐 n 本书籍'''
        try:
            # 调用 OPDS 搜索接口，默认搜索所有书籍
            query = "*"  # 空查询，可以调出完整书目
            results = await self._search_opds(query)

            # 检查是否有书籍可供推荐
            if not results:
                yield event.plain_result("未找到任何可推荐的电子书。")
                return

            # 限制推荐数量，防止超出实际书籍数量
            if n > len(results):
                n = len(results)

            # 随机选择 n 本书籍
            recommended_books = random.sample(results, n)

            # 显示推荐书籍
            guidance = f"如下是随机推荐的 {n} 本电子书：\n"
            async for result in self._show_result(event, recommended_books, guidance):
                yield result

        except Exception as e:
            logger.error(f"推荐书籍时发生错误: {e}")
            yield event.plain_result("推荐随机书籍时出现错误，请稍后重试。")

    @llm_tool("opds_search_books")
    async def search_books(self, event: AstrMessageEvent, query: str):
        """Search books by keywords or title through OPDS.
        When to use:
            Use this method to search for books in the OPDS catalog when user knows the title or keyword.
            This method cannot be used for downloading books and should only be used for searching purposes.
    
        Args:
            query (string): The search keyword or title to find books in the OPDS catalog.
    
        """
        results = await self._search_opds(quote_plus(query), 10)
        if isinstance(results, list):
            return self.to_string(results)
        else:
            return "没有搜索到匹配的电子书。"

    @llm_tool("opds_download_book")
    async def download_book(self, event: AstrMessageEvent, book_identifier: str):
        """Download a book by a precise name or URL through OPDS.
        When to use:
            Use this method to download a specific book by its name or when a direct download link is available.
    
        Args:
            book_identifier (string): The book name (exact match) or the URL of the book link.
    
        """
        try:
            ebook_url = ""
            # First, determine if the identifier is a URL or a book name
            if book_identifier.lower().startswith("http://") or book_identifier.lower().startswith("https://"):
                ebook_url = book_identifier
            else:
                # Search the book by name
                results = await self._search_opds(quote_plus(book_identifier))
                matched_books = [
                    book for book in results if book_identifier.lower() in book["title"].lower()
                ]

                if len(matched_books) == 1:
                    ebook_url = matched_books[0]["download_link"]
                elif len(matched_books) > 1:
                    async for result in self._show_result(event, results, guidance="请使用链接下载电子书。\n"):
                        yield result
                else:
                    yield event.plain_result("未能找到匹配的电子书，请提供准确书名或电子书下载链接。")
                    return
            async for result in self.download(event, ebook_url):
                yield result
        except Exception as e:
            logger.error(f"处理书籍接收过程中出现错误: {e}")
            yield event.plain_result("处理请求时发生错误，请稍后重试或检查输入是否正确。")

    @llm_tool("opds_recommend_books")
    async def recommend_books(self, event: AstrMessageEvent, n: str = "5"):
        """Randomly recommend n books from the OPDS catalog.
        When to use:
            Use this method to get a random selection of books when users are unsure what to read.
    
        Args:
            n (string): Number of books to recommend (default is 5).
        """
        async for result in self.recommend(event, int(n)):
            yield result

