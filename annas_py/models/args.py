from enum import Enum


class OrderBy(Enum):
    MOST_RELEVANT = ""
    NEWEST = "newest"
    OLDEST = "oldest"
    LARGEST = "largest"
    SMALLEST = "smallest"


class FileType(Enum):
    ANY = ""
    PDF = ".pdf"
    EPUB = ".epub"
    MOBI = ".mobi"
    AZW3 = ".azw3"
    FB2 = ".fb2"
    LIT = ".lit"
    DJVU = ".djvu"
    RTF = ".rtf"
    ZIP = ".zip"
    RAR = ".rar"
    CBR = ".cbr"
    TXT = ".txt"
    CBZ = ".cbz"
    HTML = ".html"
    FB2_ZIP = ".fb2.zip"
    DOC = ".doc"
    HTM = ".htm"
    DOCX = ".docx"
    LRF = ".lrf"
    MHT = ".mht"


class Language(Enum):
    ANY = ""
    EN = "en"
    AR = "ar"
    BE = "be"
    BG = "bg"
    BN = "bn"
    CA = "ca"
    CS = "cs"
    DE = "de"
    EL = "el"
    EO = "eo"
    ES = "es"
    FA = "fa"
    FR = "fr"
    HI = "hi"
    HU = "hu"
    ID = "id"
    IT = "it"
    JA = "ja"
    KO = "ko"
    LT = "lt"
    ML = "ml"
    NL = "nl"
    NO = "no"
    OR = "or"
    PL = "pl"
    PT = "pt"
    RO = "ro"
    RU = "ru"
    SK = "sk"
    SL = "sl"
    SQ = "sq"
    SR = "sr"
    SV = "sv"
    TR = "tr"
    TW = "tw"
    UK = "uk"
    UR = "ur"
    VI = "vi"
    ZH = "zh"
