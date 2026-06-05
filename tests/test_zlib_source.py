import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
STUBBED_MODULES = (
    "astrbot",
    "astrbot.api",
    "astrbot.api.all",
    "data",
    "data.plugins",
    "data.plugins.astrbot_plugin_ebooks",
    "data.plugins.astrbot_plugin_ebooks.Zlibrary",
    "data.plugins.astrbot_plugin_ebooks.utils",
    "data.plugins.astrbot_plugin_ebooks.zlib_source",
)
_MISSING = object()
ORIGINAL_MODULES = {name: sys.modules.get(name, _MISSING) for name in STUBBED_MODULES}


class Plain:
    def __init__(self, text):
        self.text = text


class Image:
    @classmethod
    def fromBase64(cls, data):
        return cls()


class Node:
    def __init__(self, uin=None, name=None, content=None):
        self.uin = uin
        self.name = name
        self.content = content or []


class Nodes:
    def __init__(self, nodes=None):
        self.nodes = nodes or []


class File:
    def __init__(self, name=None, file=None):
        self.name = name
        self.file = file


class Logger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


astrbot_all = types.ModuleType("astrbot.api.all")
astrbot_all.Plain = Plain
astrbot_all.Image = Image
astrbot_all.Node = Node
astrbot_all.Nodes = Nodes
astrbot_all.File = File
astrbot_all.logger = Logger()
sys.modules.setdefault("astrbot", types.ModuleType("astrbot"))
sys.modules.setdefault("astrbot.api", types.ModuleType("astrbot.api"))
sys.modules["astrbot.api.all"] = astrbot_all
sys.modules.setdefault("data", types.ModuleType("data"))
sys.modules.setdefault("data.plugins", types.ModuleType("data.plugins"))
plugin_package = types.ModuleType("data.plugins.astrbot_plugin_ebooks")
plugin_package.__path__ = [str(PLUGIN_ROOT)]
sys.modules["data.plugins.astrbot_plugin_ebooks"] = plugin_package


class FakeZlibrary:
    def __init__(self, email=None, password=None):
        self.logged_in = bool(email and password)
        self.search_called = False

    def isLoggedIn(self):
        return self.logged_in

    def login(self, email, password):
        self.logged_in = bool(email and password)
        return {"success": self.logged_in}

    def search(self, message=None, limit=None):
        self.search_called = True
        return {
            "books": [
                {
                    "title": "Million Pound Note",
                    "author": "Mark Twain",
                    "year": "1893",
                    "publisher": None,
                    "language": "English",
                    "description": "A short story.",
                    "id": "12345",
                    "hash": "abcdef",
                }
            ]
        }


zlibrary_module = types.ModuleType("data.plugins.astrbot_plugin_ebooks.Zlibrary")
zlibrary_module.Zlibrary = FakeZlibrary
sys.modules["data.plugins.astrbot_plugin_ebooks.Zlibrary"] = zlibrary_module


utils_module = types.ModuleType("data.plugins.astrbot_plugin_ebooks.utils")


async def no_cover(*args, **kwargs):
    return None


async def fail_url_accessible(*args, **kwargs):
    utils_module.url_accessible_called = True
    raise AssertionError("is_url_accessible() should not be called during Z-Library search")


utils_module.url_accessible_called = False
utils_module.download_and_convert_to_base64 = no_cover
utils_module.is_base64_image = lambda value: False
utils_module.is_url_accessible = fail_url_accessible
utils_module.is_valid_zlib_book_hash = lambda value: True
utils_module.is_valid_zlib_book_id = lambda value: True
utils_module.truncate_filename = lambda value: value
sys.modules["data.plugins.astrbot_plugin_ebooks.utils"] = utils_module

spec = importlib.util.spec_from_file_location(
    "data.plugins.astrbot_plugin_ebooks.zlib_source",
    PLUGIN_ROOT / "zlib_source.py",
)
zlib_source = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = zlib_source
spec.loader.exec_module(zlib_source)
ZlibSource = zlib_source.ZlibSource


class Config(dict):
    def save_config(self):
        pass


class Event:
    def get_self_id(self):
        return "10000"


class ZlibSourceTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def tearDownClass(cls):
        for name, module in ORIGINAL_MODULES.items():
            if module is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    async def test_search_uses_zlibrary_api_without_homepage_probe(self):
        utils_module.url_accessible_called = False
        source = ZlibSource(
            Config(
                {
                    "enable_zlib": True,
                    "zlib_email": "user@example.com",
                    "zlib_password": "password",
                }
            ),
            proxy=None,
            max_results=20,
            temp_path=tempfile.gettempdir(),
        )

        result = await source.search_nodes(Event(), "百万英镑", 20)

        self.assertIsInstance(result, list)
        self.assertEqual(1, len(result))
        self.assertTrue(source.zlibrary.search_called)
        self.assertFalse(utils_module.url_accessible_called)


if __name__ == "__main__":
    unittest.main()
