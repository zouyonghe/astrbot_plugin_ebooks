import asyncio
import random
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote_plus, urljoin, unquote

from astrbot.api.all import Plain, Image, Node, Nodes, File, logger
from data.plugins.astrbot_plugin_ebooks.utils import (
    SharedSession,
    download_and_convert_to_base64,
    is_base64_image,
    is_valid_calibre_book_url,
)


class CalibreSource(SharedSession):
    def __init__(self, config, proxy: str, max_results: int):
        super().__init__(proxy)
        self.config = config
        self.max_results = max_results
        self.cover_semaphore = asyncio.Semaphore(5)

    async def _search_calibre_web(self, query: str, limit: int = None):
        calibre_web_url = self.config.get("calibre_web_url", "http://127.0.0.1:8083")
        search_url = f"{calibre_web_url}/opds/search/{query}"

        session = await self.get_session()
        async with session.get(search_url, proxy=self.proxy) as response:
            if response.status == 200:
                content_type = response.headers.get("Content-Type", "")
                if "application/atom+xml" in content_type:
                    data = await response.text()
                    return self._parse_opds_response(data, limit)
                logger.error(f"[Calibre-Web] Unexpected content type: {content_type}")
            else:
                logger.error(
                    f"[Calibre-Web] Error during search: Calibre-Web returned status code {response.status}"
                )
            return None

    def _parse_opds_response(self, xml_data: str, limit: int = None):
        calibre_web_url = self.config.get("calibre_web_url", "http://127.0.0.1:8083")
        xml_data = re.sub(r"[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD]", "", xml_data)
        xml_data = re.sub(r"\s+", " ", xml_data)

        try:
            root = ET.fromstring(xml_data)
            namespace = {"default": "http://www.w3.org/2005/Atom"}
            entries = root.findall("default:entry", namespace)

            results = []
            for entry in entries:
                title_element = entry.find("default:title", namespace)
                title = title_element.text if title_element is not None else "未知"

                authors = []
                author_elements = entry.findall("default:author/default:name", namespace)
                for author in author_elements:
                    authors.append(author.text if author is not None else "未知")
                authors = ", ".join(authors) if authors else "未知"

                summary_element = entry.find("default:summary", namespace)
                summary = summary_element.text if summary_element is not None else "无描述"

                published_element = entry.find("default:published", namespace)
                if published_element is not None and published_element.text:
                    try:
                        year = datetime.fromisoformat(published_element.text).year
                    except ValueError:
                        year = "未知"
                else:
                    year = "未知"

                lang_element = entry.find("default:dcterms:language", namespace)
                language = lang_element.text if lang_element is not None else "未知"

                publisher_element = entry.find("default:publisher/default:name", namespace)
                publisher = publisher_element.text if publisher_element is not None else "未知"

                cover_element = entry.find("default:link[@rel='http://opds-spec.org/image']", namespace)
                cover_suffix = cover_element.attrib.get("href", "") if cover_element is not None else ""
                if cover_suffix and re.match(r"^/opds/cover/\d+$", cover_suffix):
                    cover_link = urljoin(calibre_web_url, cover_suffix)
                else:
                    cover_link = ""

                thumbnail_element = entry.find(
                    "default:link[@rel='http://opds-spec.org/image/thumbnail']",
                    namespace,
                )
                thumbnail_suffix = thumbnail_element.attrib.get("href", "") if thumbnail_element is not None else ""
                if thumbnail_suffix and re.match(r"^/opds/cover/\d+$", thumbnail_suffix):
                    thumbnail_link = urljoin(calibre_web_url, thumbnail_suffix)
                else:
                    thumbnail_link = ""

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

                results.append(
                    {
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
                        "file_size": file_size,
                    }
                )

            return results[:limit]
        except ET.ParseError as e:
            logger.error(f"[Calibre-Web] Error parsing OPDS response: {e}")
            return None

    async def _build_book_chain(self, item: dict) -> list:
        chain = [Plain(f"{item['title']}")]
        if item.get("cover_link"):
            async with self.cover_semaphore:
                base64_image = await download_and_convert_to_base64(
                    item["cover_link"],
                    proxy=self.proxy,
                    session=await self.get_session(),
                )
            if is_base64_image(base64_image):
                chain.append(Image.fromBase64(base64_image))
            else:
                chain.append(Plain("\n"))
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

    async def _convert_calibre_results_to_nodes(self, event, results: list):
        if not results:
            return "[Calibre-Web] 未找到匹配的电子书。"

        async def construct_node(book):
            chain = await self._build_book_chain(book)
            return Node(
                uin=event.get_self_id(),
                name="Calibre-Web",
                content=chain,
            )

        tasks = [construct_node(book) for book in results]
        return await asyncio.gather(*tasks)

    async def search_nodes(self, event, query: str, limit: str|int = ""):
        if not self.config.get("enable_calibre", False):
            return "[Calibre-Web] 功能未启用。"

        if not query:
            return "[Calibre-Web] 请提供电子书关键词以进行搜索。"

        limit = int(limit) if str(limit).isdigit() else int(self.max_results)
        if not (1 <= limit <= 100):
            return "[Calibre-Web] 请确认搜索返回结果数量在 1-100 之间。"

        try:
            logger.info(f"[Calibre-Web] Received books search query: {query}, limit: {limit}")
            results = await self._search_calibre_web(quote_plus(query), limit)
            if not results or len(results) == 0:
                return "[Calibre-Web] 未找到匹配的电子书。"
            return await self._convert_calibre_results_to_nodes(event, results)
        except Exception as e:
            logger.error(f"[Calibre-Web] 搜索失败: {e}")
            return "Calibre-Web] 搜索失败，请检查控制台输出"

    async def download(self, event, book_url: str = None):
        if not self.config.get("enable_calibre", False):
            return [event.plain_result("[Calibre-Web] 功能未启用。")]

        if not is_valid_calibre_book_url(book_url):
            return [event.plain_result("[Calibre-Web] 请提供有效的电子书链接。")]

        try:
            session = await self.get_session()
            async with session.get(book_url, proxy=self.proxy) as response:
                if response.status == 200:
                    content_disposition = response.headers.get("Content-Disposition")
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
                        logger.error(f"[Calibre-Web] 无法提取书名，电子书地址: {book_url}")
                        return [event.plain_result("[Calibre-Web] 无法提取书名，取消发送电子书。")]

                    file = File(name=book_name, url=book_url)
                    return [event.chain_result([file])]
                return [event.plain_result(f"[Calibre-Web] 无法下载电子书，状态码: {response.status}")]
        except Exception as e:
            logger.error(f"[Calibre-Web] 下载失败: {e}")
            return [event.plain_result("[Calibre-Web] 下载电子书时发生错误，请稍后再试。")]

    async def recommend(self, event, n: int):
        if not self.config.get("enable_calibre", False):
            return [event.plain_result("[Calibre-Web] 功能未启用。")]

        try:
            query = "*"
            results = await self._search_calibre_web(query)
            if not results:
                return [event.plain_result("[Calibre-Web] 未找到可推荐的电子书。")]

            if n > len(results):
                n = len(results)

            recommended_books = random.sample(results, n)
            result = await self._convert_calibre_results_to_nodes(event, recommended_books)

            if isinstance(result, str):
                return [event.plain_result(result)]
            if isinstance(result, list):
                guidance = f"[Calibre-Web] 如下是随机推荐的 {n} 本电子书。"
                nodes = [Node(uin=event.get_self_id(), name="Calibre-Web", content=[Plain(guidance)])]
                nodes.extend(result)
                ns = Nodes([])
                ns.nodes = nodes
                return [event.chain_result([ns])]
            return [event.plain_result("[Calibre-Web] 生成结果失败。")]
        except Exception as e:
            logger.error(f"[Calibre-Web] 推荐电子书时发生错误: {e}")
            return [event.plain_result("[Calibre-Web] 推荐电子书时发生错误，请稍后再试。")]

    async def close(self):
        await self.close_session()
