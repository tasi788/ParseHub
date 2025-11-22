import re
from urllib.parse import urlparse

from ..base.yt_dlp_parser import YtParser, YtVideoParseResult
from ...provider_api.facebook import FacebookAPI, FacebookException
from ...types import ImageParseResult, Image, ParseError


class FacebookParse(YtParser):
    __platform_id__ = "facebook"
    __platform__ = "Facebook"
    __supported_type__ = ["视频", "图文"]
    __match__ = r"^(http(s)?://)?.+facebook.com/.*"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fb_api = FacebookAPI(proxy=self.cfg.proxy)

    def is_video_url(self, url: str) -> bool:
        """判断是否為影片連結"""
        video_patterns = [
            r'/watch\?v=',
            r'/share/r/',  # alias reels
            r'/share/v/',  # alias video
            r'/videos/',
            r'/reel/',
        ]
        return any(re.search(pattern, url) for pattern in video_patterns)

    def is_post_url(self, url: str) -> bool:
        """判斷是否為貼文連結"""
        parsed = urlparse(url)
        post_patterns = [
            r'/posts/',
            r'/permalink\.php',
            r'/story\.php',
            r'/photo',
            r'/groups/.+/permalink/',
            r'/share/p/',  # alias post
            r'/share/[^/]+$',  # alias post
        ]
        return any(re.search(pattern, parsed.path) for pattern in post_patterns)

    async def parse(self, url: str):
        url = await self.get_raw_url(url)
        
        # 判斷是影片還是貼文
        if self.is_video_url(url):
            # 使用 yt-dlp 解析影片
            return await super().parse(url)
        elif self.is_post_url(url):
            # 使用 facebed 方式解析貼文
            return await self._parse_post(url)
        else:
            # 預設使用 yt-dlp
            return await super().parse(url)

    async def _parse_post(self, url: str) -> ImageParseResult:
        """解析 Facebook 貼文"""
        try:
            post = await self.fb_api.parse_post(url)
            
            # 構建描述
            desc_parts = [post.text]
            desc = desc_parts[0]
            
            # 處理圖片
            photos = [Image(path=img_url) for img_url in post.image_links]
            
            return ImageParseResult(
                title=post.author_name,
                photo=photos,
                desc=desc,
                raw_url=url
            )
        except FacebookException as e:
            raise ParseError(f"解析 Facebook 貼文失敗: {str(e)}") from e
        except Exception as e:
            raise ParseError(f"解析失敗: {str(e)}") from e


__all__ = ["FacebookParse"]
