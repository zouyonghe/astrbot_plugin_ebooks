import aiohttp


from astrbot.api.all import *
from astrbot.api.event.filter import *


@register("opds", "Your Name", "一个基于OPDS的电子书搜索和下载插件", "0.0.1", "repo url")
class OPDS(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config

    @command_group("opds")
    def opds(self):
        pass

    # 注册指令的装饰器，用于搜索电子书
    @opds.command("search")
    async def search(self, event: AstrMessageEvent):
        '''搜索 OPDS 电子书目录'''
        query = event.message_str.strip()  # 获取用户输入的查询字符串
        if not query:
            yield event.plain_result("请输入搜索关键词。")
            return

        try:
            results = await self.search_opds(query)  # 调用搜索方法
            if not results:
                yield event.plain_result("未找到相关的电子书。")
            else:
                formatted_results = "\n".join(
                    [f"{idx + 1}. {item['title']} - {item['link']}" for idx, item in enumerate(results)]
                )
                yield event.plain_result(f"搜索结果：\n{formatted_results}")
        except Exception as e:
            logger.error(f"OPDS搜索失败: {e}")
            yield event.plain_result("搜索过程中出现错误，请稍后重试。")

    async def search_opds(self, query: str):
        '''调用 OPDS 目录 API 进行电子书搜索'''
        opds_url = self.config.get("opds_url", "http://127.0.0.1:8083")
        username = self.config.get("opds_username")  # 从配置中获取用户名
        password = self.config.get("opds_password")  # 从配置中获取密码

        opds_api_url = f"{opds_url}/opds/search/{query}"  # 根据实际路径修改

        # 使用 aiohttp 的 Basic Authentication
        auth = aiohttp.BasicAuth(username, password)

        async with aiohttp.ClientSession(auth=auth) as session:
            async with session.get(opds_api_url) as response:
                if response.status == 200:
                    data = await response.json()
                    # 解析 OPDS 搜索结果并返回
                    return [
                        {"title": item.get("title"), "link": item.get("link")}
                        for item in data.get("entries", [])
                    ]
                else:
                    logger.error(f"OPDS搜索失败，状态码: {response.status}")
                    return None

    @opds.command("download")
    async def download(self, event: AstrMessageEvent, ebook_url: str = None):
        '''下载 OPDS 提供的电子书'''
        if not ebook_url:
            yield event.plain_result("请输入电子书的下载链接。")
            return

        username = self.config.get("opds_username")
        password = self.config.get("opds_password")

        # 使用 aiohttp 的 Basic Authentication
        auth = aiohttp.BasicAuth(username, password)

        try:
            async with aiohttp.ClientSession(auth=auth) as session:
                async with session.get(ebook_url) as response:
                    if response.status == 200:
                        # 保存到文件或者进一步处理内容
                        file_name = ebook_url.split("/")[-1]
                        with open(f"./downloads/{file_name}", "wb") as file:
                            file.write(await response.read())
                        logger.info(f"电子书 {file_name} 下载完成。")
                        file = File(name=file_name, file="./downloads/{file_name}")
                        yield event.chain_result([file])
                    else:
                        yield event.plain_result(f"无法下载电子书，状态码: {response.status}")
        except Exception as e:
            logger.error(f"下载失败: {e}")
            yield event.plain_result("下载过程中出现错误，请稍后重试。")
