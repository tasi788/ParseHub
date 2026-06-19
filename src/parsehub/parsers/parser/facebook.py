import re
from urllib.parse import urlparse

from ...provider_api.facebook import FacebookAPI, FacebookException
from ...types import AnyParseResult, ImageParseResult, ImageRef, ParseError
from ...types.platform import Platform
from ..base.ytdlp import YtParser


class FacebookParse(YtParser):
    __platform__ = Platform.FACEBOOK
    __supported_type__ = ["视频", "图文"]
    __match__ = r"^(http(s)?://)?.+facebook.com/.*"

    def __init__(self, *, proxy: str | None = None, cookie: str | dict | None = None) -> None:
        super().__init__(proxy=proxy, cookie=cookie)
        self.fb_api = FacebookAPI(proxy=self.proxy, cookies=self.cookie)

    @staticmethod
    def is_video_url(url: str) -> bool:
        video_patterns = [
            r"/watch\?v=",
            r"/share/r/",
            r"/share/v/",
            r"/videos/",
            r"/reel/",
        ]
        return any(re.search(pattern, url) for pattern in video_patterns)

    @staticmethod
    def is_post_url(url: str) -> bool:
        parsed = urlparse(url)
        post_patterns = [
            r"/posts/",
            r"/permalink\.php",
            r"/story\.php",
            r"/photo",
            r"/groups/.+/permalink/",
            r"/share/p/",
            r"/share/[^/]+$",
        ]
        target = f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path
        return any(re.search(pattern, target) for pattern in post_patterns)

    async def _do_parse(self, raw_url: str) -> AnyParseResult:
        if self.is_video_url(raw_url):
            return await super()._do_parse(raw_url)
        if self.is_post_url(raw_url):
            return await self._parse_post(raw_url)
        return await super()._do_parse(raw_url)

    async def _parse_post(self, url: str) -> ImageParseResult:
        try:
            post = await self.fb_api.parse_post(url)
        except FacebookException as e:
            raise ParseError(f"解析 Facebook 贴文失败: {str(e)}") from e
        except Exception as e:
            raise ParseError(f"解析 Facebook 贴文失败: {str(e)}") from e

        photos = [ImageRef(url=img_url, thumb_url=img_url) for img_url in post.image_links]
        return ImageParseResult(
            title=post.author_name,
            content=post.text,
            photo=photos,
        )


__all__ = ["FacebookParse"]
