import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus, urljoin, unquote

import aiohttp

from astrbot.api.all import *
from astrbot.api.event.filter import *

path = os.getcwd()
download_dir = f"{path}/downloads/"
os.makedirs(download_dir, exist_ok=True)


@register("opds", "Your Name", "一个基于OPDS的电子书搜索和下载插件", "0.0.1", "repo url")
class OPDS(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config

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
            results = await self.search_opds(quote_plus(query))  # 调用搜索方法
            if not results:
                yield event.plain_result("未找到相关的电子书。")
            else:
                chain = [
                    Plain("以下是电子书搜索结果："),
                ]
                for idx, item in enumerate(results):
                    chain.append(
                        Plain(f"\n{idx + 1}. {item['title']} by {item.get('authors', '未知作者')}\n")
                    )
                    if item.get("cover_link"):
                        chain.append(Image.fromURL(item["cover_link"]))
                    chain.append(Plain(f"描述: {item.get('summary', '暂无描述')}\n"))
                    chain.append(Plain(f"下载链接: {item['download_link']}\n"))

                if len(results) <= 3:
                    yield event.chain_result(chain)
                else:
                    node = Node(
                        uin=event.get_self_id(),
                        name="OPDS",
                        content=chain
                    )
                    yield event.chain_result([node])
        except Exception as e:
            logger.error(f"OPDS搜索失败: {e}")
            yield event.plain_result("搜索过程中出现错误，请稍后重试。")

    async def search_opds(self, query: str):
        '''调用 OPDS 目录 API 进行电子书搜索'''
        opds_url = self.config.get("opds_url", "http://127.0.0.1:8083")
        username = self.config.get("opds_username")  # 从配置中获取用户名
        password = self.config.get("opds_password")  # 从配置中获取密码

        search_url = f"{opds_url}/opds/search/{query}"  # 根据实际路径构造 API URL
        auth = aiohttp.BasicAuth(username, password)  # 使用 Basic Authentication

        async with aiohttp.ClientSession(auth=auth) as session:
            async with session.get(search_url) as response:
                if response.status == 200:
                    content_type = response.headers.get("Content-Type", "")
                    if "application/atom+xml" in content_type:
                        data = await response.text()
                        return self.parse_opds_response(data)  # 调用解析方法
                    else:
                        logger.error(f"Unexpected content type: {content_type}")
                        return None
                else:
                    logger.error(f"OPDS搜索失败，状态码: {response.status}")
                    return None

    def parse_opds_response(self, xml_data: str):
        '''解析 OPDS 搜索结果 XML 数据'''
        opds_url = self.config.get("opds_url", "http://127.0.0.1:8083")

        try:
            root = ET.fromstring(xml_data)  # 把 XML 转换为元素树
            namespace = {"default": "http://www.w3.org/2005/Atom"}  # 定义命名空间
            entries = root.findall("default:entry", namespace)  # 查找所有 <entry> 节点

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
                if cover_suffix:
                    cover_link = urljoin(opds_url, cover_suffix)
                else:
                    cover_link = ""

                # 提取图书缩略图链接（rel="http://opds-spec.org/image/thumbnail"）
                thumbnail_element = entry.find("default:link[@rel='http://opds-spec.org/image/thumbnail']", namespace)
                thumbnail_suffix = thumbnail_element.attrib.get("href", "") if thumbnail_element is not None else ""
                if thumbnail_suffix:
                    thumbnail_link = urljoin(opds_url, thumbnail_suffix)
                else:
                    thumbnail_link = ""

                # 提取下载链接及其格式（rel="http://opds-spec.org/acquisition"）
                acquisition_element = entry.find("default:link[@rel='http://opds-spec.org/acquisition']", namespace)
                if acquisition_element is not None:
                    download_suffix = acquisition_element.attrib.get("href", "") if acquisition_element is not None else ""
                    if download_suffix:
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

            return results
        except ET.ParseError as e:
            logger.error(f"解析 OPDS 响应失败: {e}")
            return None

    # @opds.command("download")
    # async def download(self, event: AstrMessageEvent, ebook_url: str = None):
    #     '''下载 OPDS 提供的电子书'''
    #     if not ebook_url:
    #         yield event.plain_result("请输入电子书的下载链接。")
    #         return
    #
    #     username = self.config.get("opds_username")
    #     password = self.config.get("opds_password")
    #
    #     auth = aiohttp.BasicAuth(username, password)
    #
    #     try:
    #         async with aiohttp.ClientSession(auth=auth) as session:
    #             async with session.get(ebook_url) as response:
    #                 if response.status == 200:
    #                     # 从 Content-Disposition 中获取文件名
    #                     content_disposition = response.headers.get("Content-Disposition")
    #                     if content_disposition:
    #                         # 使用正则提取 filename
    #                         file_name_match = re.search(r'filename="(.+?)"', content_disposition)
    #                         file_name = file_name_match.group(1) if file_name_match else None
    #                     else:
    #                         # 如果 Content-Disposition 没有提供 filename，使用默认值
    #                         file_name = f"file_{int(time.time())}.epub"
    #
    #                     # 确保文件名有效
    #                     if not file_name or file_name.strip() == "":
    #                         file_name = f"file_{int(time.time())}.epub"
    #
    #                     # 保存完整路径
    #                     file_path = os.path.join(download_dir, file_name)
    #
    #                     # 保存文件到本地
    #                     with open(file_path, "wb") as file:
    #                         file.write(await response.read())
    #
    #                     logger.info(f"电子书 {file_name} 下载完成。")
    #
    #                     # 返回下载后的文件信息
    #                     file = File(name=file_name, file=file_path)
    #                     yield event.chain_result([file])
    #
    #                     # 删除下载的文件
    #                     try:
    #                         os.remove(file_path)
    #                         logger.info(f"已成功删除文件: {file_path}")
    #                     except OSError as e:
    #                         logger.error(f"删除文件 {file_path} 时出错: {e}")
    #                 else:
    #                     yield event.plain_result(f"无法下载电子书，状态码: {response.status}")
    #     except Exception as e:
    #         logger.error(f"下载失败: {e}")
    #         yield event.plain_result("下载过程中出现错误，请稍后重试。")
    #

    @opds.command("download")
    async def download(self, event: AstrMessageEvent, ebook_url: str = None):
        '''下载 OPDS 提供的电子书'''
        if not ebook_url:
            yield event.plain_result("请输入电子书的下载链接。")
            return

        username = self.config.get("opds_username")
        password = self.config.get("opds_password")

        auth = aiohttp.BasicAuth(username, password)

        try:
            # 创建下载目录
            os.makedirs(download_dir, exist_ok=True)

            async with aiohttp.ClientSession(auth=auth) as session:
                async with session.get(ebook_url) as response:
                    if response.status == 200:
                        # 从 Content-Disposition 提取文件名
                        # content_disposition = response.headers.get("Content-Disposition")
                        # file_name = None
                        #
                        # if content_disposition:
                        #     logger.info(f"Content-Disposition: {content_disposition}")
                        #
                        #     # 先检查是否有 filename*= 条目
                        #     file_name_match = re.search(r'filename\*=(?:UTF-8\'\')?([^;]+)', content_disposition)
                        #     if file_name_match:
                        #         file_name = file_name_match.group(1)
                        #         file_name = unquote(file_name)  # 解码 URL 编码的文件名
                        #     else:
                        #         # 如果没有 filename*，则查找普通的 filename
                        #         file_name_match = re.search(r'filename=["\']?([^;\']+)["\']?', content_disposition)
                        #         if file_name_match:
                        #             file_name = file_name_match.group(1)
                        #
                        # # 如果未获取到文件名，使用默认值
                        # if not file_name or file_name.strip() == "":
                        #     file_name = f"file_{int(time.time())}.epub"

                        # # 确保文件名有效
                        # file_path = os.path.join(download_dir, file_name)
                        #
                        # # 保存文件到本地
                        # with open(file_path, "wb") as file:
                        #     file.write(await response.read())
                        #
                        # logger.info(f"电子书 {file_name} 下载完成，路径: {file_path}")

                        # 发送文件到用户
                        file = File(file=ebook_url)
                        yield event.chain_result([file])

                        # # 删除下载的文件
                        # try:
                        #     os.remove(file_path)
                        #     logger.info(f"已成功删除文件: {file_path}")
                        # except OSError as e:
                        #     logger.error(f"删除文件 {file_path} 时出错: {e}")

                    else:
                        yield event.plain_result(f"无法下载电子书，状态码: {response.status}")
        except Exception as e:
            logger.error(f"下载失败: {e}")
            yield event.plain_result("下载过程中出现错误，请稍后重试。")
