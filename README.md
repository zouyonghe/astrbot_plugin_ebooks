# astrbot_plugin_opds

基于OPDS协议搜索电子书，支持下载电子书并发送到QQ。目前主要基于calibre-web实现。

## 功能说明

该插件实现了一个基于 OPDS 的电子书搜索和下载功能，包括以下功能：

- `opds.search <query>`：根据关键词搜索 OPDS 电子书目录。
- `opds.download <ebook_url>`：通过 OPDS 协议下载指定电子书。
- `opds.recommend <n>`：随机推荐 n 本书籍。

## 方法与功能详情

### OPDS 搜索功能

- 通过关键词搜索 OPDS 电子书目录。
- 支持解析 XML 数据并展示书籍详情，包括封面、作者、描述、出版日期、下载链接等。

### 下载功能

- 提供直接下载电子书的功能。
- 自动从响应头中解析电子书文件名。

### 随机推荐

- 随机选择书目（可指定推荐数量）。
- 展示随机推荐的电子书详情。

# 版本信息

- 插件名称：OPDS
- 标识符：buding
- 描述：一个基于 OPDS 的电子书搜索和下载插件
- 版本：1.0.0
- 源码：[GitHub 地址](https://github.com/zouyonghe/astrbot_plugin_opds)

