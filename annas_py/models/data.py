from dataclasses import dataclass


@dataclass(slots=True)
class URL:
    title: str
    url: str


@dataclass(slots=True)
class FileInfo:
    extension: str
    size: str
    language: str | None
    library: str


@dataclass(slots=True)
class RecentDownload:
    id: str
    title: str


@dataclass(slots=True)
class SearchResult:
    id: str
    title: str
    authors: str
    file_info: FileInfo
    thumbnail: str | None
    publisher: str | None
    publish_date: str | None


@dataclass(slots=True)
class Download:
    title: str
    description: str
    authors: str
    file_info: FileInfo
    urls: list[URL]
    thumbnail: str | None
    publisher: str | None
    publish_date: str | None
