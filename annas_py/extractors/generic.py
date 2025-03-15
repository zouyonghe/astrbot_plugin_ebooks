from ..models.data import FileInfo

MAX_SIZE_DESCRIPTION_LENGHT = len("123.4MB")


def extract_file_info(raw: str) -> FileInfo:
    # Extract file info from raw string given from the website
    # it assumes that the string will always have the file format
    # and size, but can have language and file name too
    # > Cases:
    #     Language, format, size and file name is provided;
    #     Language, format and size is provided;
    #     Format and size is provided.

    # sample data:
    # German [de], .azw3, 🚀/zlib, 1.0MB, 📗 Book (unknown)
    info_list = raw.split(", ")

    language_parts = []
    while "[" in info_list[0] and "]" in info_list[0]:
        language_parts.append(info_list.pop(0))
    language = ", ".join(language_parts) if language_parts else None

    extension = info_list.pop(0).lstrip(".")
    library = info_list.pop(0).split("/")[-1]
    size = info_list.pop(0)
    #_type = info_list.pop(0)
    return FileInfo(extension, size, language, library)


def extract_publish_info(raw: str) -> tuple[str | None, str | None]:
    # Sample data:
    #  John Wiley and Sons; Wiley (Blackwell Publishing); Blackwell Publishing Inc.; Wiley; JSTOR (ISSN 0020-6598), International Economic Review, #2, 45, pages 327-350, 2004 may
    #  Cambridge University Press, 10.1017/CBO9780511510854, 2001
    #  Cambridge University Press, 1, 2008
    #  Cambridge University Press, 2014 feb 16
    #  1, 2008
    #  2008
    raw = raw.strip()
    if not raw:
        return (None, None)
    info = raw.split(", ")
    publisher = info[0] if not info[0].isdecimal() else None
    date = info[-1] if info[-1].split()[0].isdecimal() else None
    return (publisher, date)
