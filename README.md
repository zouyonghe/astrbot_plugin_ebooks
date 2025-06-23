# astrbot_plugin_ebooks

一个功能强大的电子书搜索和下载插件，提供多种平台支持，包括 Calibre-Web、Liber3、Z-Library 和 Archive。

## 功能说明

该插件支持通过多种电子书目录协议（例如 OPDS）进行电子书的搜索、下载和推荐操作，具体包括以下功能：

### 电子书搜索

支持以下平台的电子书搜索：

- **Calibre-Web**
- **Liber3**
- **Z-Library**
- **Archive.org**
- **Anna‘s Archive**

通过搜索关键词，可以快速找到对应的电子书信息，返回的结果包括标题、作者、简介、封面、出版年份、文件类型和下载链接等。

### 电子书下载

提供高效的电子书下载功能：

- 支持通过下载链接、电子书 ID 或哈希值进行下载。
- 自动从响应头解析文件名并保存到本地。
- 支持常见的电子书格式（如 PDF、EPUB 等）。

### 随机推荐

随机从现有的电子书目录中推荐 n 本书籍，展示推荐的电子书详情，包括封面、作者、简介和下载链接。

## 支持平台

1. **Calibre-Web**
    - 支持通过 OPDS 协议进行搜索与下载。
    - 提供随机推荐功能。

2. **Liber3**
    - 支持电子书的详细信息（如语言、文件大小等）。
    - 通过电子书 ID 进行下载。

3. **Z-Library**
    - 搜索和下载全球最大的免费电子书数据库。
    - 支持通过 ID 或哈希值下载电子书。

4. **Archive.org**
    - 通过高级搜索 API 搜索电子书。
    - 过滤支持的格式（如 PDF/EPUB）。

5. **Anna‘s Archive**
    - 暂不支持下载，只提供下载链接

## 使用指南

### LLM函数调用（推荐）

- 发送`/搜索电子书 linux`等，调用多平台整合搜索
- 发送`/下载电子书 <link or ID,Hash>`，自动识别下载信息下载电子书
- 发送`推荐10本电子书`，暂只支持从calibre-web随机推荐指定数量电子书

### 命令参考

以下为插件提供的命令与相关功能（支持在 AstrBot 中调用）：

#### 帮助信息

`ebooks help`：显示插件帮助信息

#### 整合搜索即下载

- `ebooks search <linux> [10]`： 最后的数字可选，代表每个平台搜索的数量，默认为20

- `ebooks download <link or ID,Hash>`：下载指定标识的电子书电子书

#### **Calibre-Web**

- `/calibre search <关键词>`：搜索 Calibre-Web 中的电子书。例如：
  ```
  /calibre search Python
  ```

- `/calibre download <下载链接/书名>`：通过 Calibre-Web 下载电子书。例如：
  ```
  /calibre download <URL>
  ```

- `/calibre recommend <数量>`：随机推荐指定数量的电子书。例如：
  ```
  /calibre recommend 5
  ```

#### **Liber3**

- `/liber3 search <关键词>`：搜索 Liber3 平台的电子书。例如：
  ```
  /liber3 search Python
  ```

- `/liber3 download <ID>`：通过 Liber3 下载电子书。例如：
  ```
  /liber3 download 12345
  ```

#### **Z-Library**

- `/zlib search <关键词> [数量(可选)]`：搜索 Z-Library 的电子书。例如：
  ```
  /zlib search Python (10)
  ```

- `/zlib download <ID> <Hash>`：通过 Z-Library 平台下载电子书。例如：
  ```
  /zlib download 12345 abcde12345
  ```

#### **Archive**

- `/archive search <关键词> [数量(可选)]`：搜索 Archive 平台的电子书。例如：
  ```
  /archive search Python (10)
  ```

- `/archive download <下载链接>`：通过 Archive 平台提供的下载 URL 下载电子书。例如：
  ```
  /archive download <URL>
  ```

#### 帮助命令

- `/ebooks help`：显示当前插件的帮助信息。

### 输出展示

- **文本格式**：使用转发消息格式，展示书籍详情，包括封面、标题、作者、简介和链接等。
- **推荐功能**：随机展示指定数量的推荐书籍。

## 注意事项

1. 所有下载指令均要求提供有效的 ID、哈希值或下载链接。
2. 推荐的书籍数量需在 1 到 50 之间，以避免生成失败。
3. 一些功能需要配置环境变量或插件参数（如 Calibre-Web 访问地址和代理设置等）。

## 版本信息

- **插件名称**：ebooks
- **标识符**：buding
- **描述**：一个功能强大的电子书搜索和下载插件
- **版本**：1.0.10
- **源码**：[GitHub 地址](https://github.com/zouyonghe/astrbot_plugin_ebooks)
