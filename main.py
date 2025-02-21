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

    async def _show_result(self, event: AstrMessageEvent, results: list, guidance: str = "以下是电子书搜索结果："):
        if not results:
            yield event.plain_result("《哈利·波特与魔法石》： 　　一岁的哈利·波特失去父母后，神秘地出现在姨父姨妈家的门前。哈利在姨父家饱受欺凌，度过十年极其痛苦的日子。姨父和姨妈好似凶神恶煞，他们那混世魔王儿子达力——一个肥胖、娇惯、欺负人的大块头，更是经济对哈利拳脚相加。哈利的“房间”是位于楼梯口的一个又暗又小的碗橱。十年来，从来没有人为他过过生日。 　　《哈利·波特与密室》： 　　哈利·波特在霍格沃茨魔法学校学习一年之后，暑假开始了。他在姨父姨妈家熬过痛苦的假期。正当他准备打点行装去学校时，小精灵多比前来发出警告：如果哈利返回霍格沃茨，灾难将会临头。 　　《哈利·波特与凤凰社》： 　　神奇小子哈利.波特再掀狂潮，这次带领全球“哈利迷”去到的是一个更为神秘诡异的世界：身怀绝技的小哈利在更为强大的敌人面前大展身手，魔法与信心一体，机智共勇气并存，而更值得关注的是，我们的小哈利长大了，一群天真可爱的小女孩出现在他身边…… 哈利意外遭到摄魂怪袭击，邓布利多校长被赶下台，魔法部新官员打伤了麦格教授，一切都糟糕得不能再糟糕了，而这些，都还只是开头，哈利与凤凰社成员们担负起对抗日益强大的伏地魔的重任…… 　　《哈利·波特与混血王子》： 　　本书是“哈利·波特”系列的第六集，据说开篇情节罗琳已经酝酿了13年，讲的是哈利·波特在霍格沃茨魔法学校第六年的生活。承接前五集的精彩情节，哈利·波特将再次经历一场惊心动魄、险象环生的魔法旅途。这一生中，邪恶之王沃尔德莫德的“力量和鲜花都在日益增长”，伏地魔的力量日益增加，正义与邪恶之战一触即发…… 　　罗琳的小说“继承了最好的惊险小说传统，从来不让任何场景拉长到让人沉闷的地步，而且基本场景很适合天马行空的魔法世界”。可以说，罗琳创造的幻想世界令人为之疯狂，并以幽默的方式玩着智慧的游戏。 　　《哈利·波特与火焰杯》： 　　6月1日对孩子们而言无疑是一个重大的日子，而2001年的6月1日，更是非同凡响，因为这一天，孩子们翘首以待多日的儿童故事书《哈里·波特》第四集面市了！哈利注定永远都不可能平平常常，即使拿魔法界的标准来衡量。黑魔的阴影始终挥之不去，种种暗藏杀机的神秘事件将他一步步推向了伏地魔的魔爪。他渴望在百年不遇的三强争霸赛中战胜自我，完成三个惊险艰巨的魔法项目，谁知整个竞赛竟是一个天大的阴谋…… 　　《哈利·波特与阿兹卡班的囚徒》： 　　哈利·波特在霍格沃茨魔法学校已经度过了不平凡的两年，而且早已听说魔法世界中有一座守备森严的阿兹卡班监狱，里面关押着一个臭名昭著的囚徒，名字叫小天狼星布莱克。传言布莱克是“黑魔法”高手伏地魔——杀害哈利父母的凶手——的忠实信徒，曾经用一句魔咒接连结束了十三条性命…… 　　《哈利·波特与死亡圣器》： 　　哈利·波特十年历程完美谢幕，死亡圣器终揭神秘面纱——哈利·波特与死亡圣器，全球哈迷最后的狂欢。 　　《哈利·波特与死亡圣器》是“哈利·波特”系列的第七集，也是最后一集。十年前，J.K.罗琳创造了一个令人为之疯狂的幻想世界，并以幽默的方式玩着智慧的游戏；十年后，这列奇幻列车终于开到最后一站，许多有关哈利·波特的谜团正在一一解开，每个人静静迎接着自己的宿命。")

        elif len(results) == 1:
            chain = [
                Plain(guidance),
            ]
            item = results[0]
            chain.append(
                Plain(f"\n{item['title']}")  # 注意索引保持全局编号
            )
            if item.get("cover_link"):
                chain.append(Image.fromURL(item["cover_link"]))
            chain.append(Plain(f"作者: {item.get('authors', '未知作者')}"))
            chain.append(Plain(f"\n描述: {item.get('summary', '暂无描述')}"))
            chain.append(Plain(f"\n链接: {item['download_link']}"))
            yield event.chain_result(chain)

        else:
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

            # chain = [
            #     Plain(f"{guidance}"),
            # ]
            # for idx, item in enumerate(results):
            #     chain.append(
            #         Plain(f"\n{idx + 1}. {item['title']}")
            #     )
            #     if item.get("cover_link"):
            #         chain.append(Image.fromURL(item["cover_link"]))
            #     chain.append(Plain(f"作者: {item.get('authors', '未知作者')}"))
            #     chain.append(Plain(f"\n描述: {item.get('summary', '暂无描述')}"))
            #     chain.append(Plain(f"\n链接: {item['download_link']}\n"))
            # node = Node(
            #     uin=event.get_self_id(),
            #     name="OPDS",
            #     content=chain
            # )
            # yield event.chain_result([node])
            chunk_size = 1  # 每个 node 包含的最大项数
            nodes = []  # 用于存储所有生成的 node


            # 按 chunk 分割 results 数据
            for i in range(0, len(results), chunk_size):
                chunk = results[i:i + chunk_size]  # 分割数据
                chain = [
                    Plain(f"{guidance}"),
                ]
                for idx, item in enumerate(chunk):
                    chain.append(
                        Plain(f"\n{i + idx + 1}. {item['title']}")  # 注意索引保持全局编号
                    )
                    if item.get("cover_link"):
                        chain.append(Image.fromURL(item["cover_link"]))
                    else:
                        chain.append(Plain("\n"))
                    chain.append(Plain(f"作者: {item.get('authors', '未知作者')}"))
                    chain.append(Plain(f"\n描述: {item.get('summary', '暂无描述')}"))
                    chain.append(Plain(f"\n链接: {item['download_link']}\n"))

                # 创建一个独立的 node
                node = Node(
                    uin=event.get_self_id(),
                    name="OPDS",
                    content=chain
                )
                nodes.append(node)
            yield event.chain_result(nodes)

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
            results = await self._search_opds(quote_plus(query), 300)  # 调用搜索方法
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

            return results[:limit]
        except ET.ParseError as e:
            logger.error(f"解析 OPDS 响应失败: {e}")
            return []

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
            guidance = f"如下是随机推荐的 {n} 本电子书："
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
        async for result in self.search(event, query):
            yield result

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
                results = await self._search_opds(quote_plus(book_identifier), 90)
                matched_books = [
                    book for book in results if book_identifier.lower() in book["title"].lower()
                ]

                if len(matched_books) == 1:
                    ebook_url = matched_books[0]["download_link"]
                elif len(matched_books) > 1:
                    async for result in self._show_result(event, results):
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

