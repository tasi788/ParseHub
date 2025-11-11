from ..base.base import BaseParser
from ...types import Image, ImageParseResult
from ...provider_api.pttcc import PTTCC
from ...config import DownloadConfig, GlobalConfig
from collections.abc import Awaitable, Callable
from pathlib import Path
from ...types import DownloadResult, ImageParseResult

class PTTParser(BaseParser):
    __platform_id__ = "ptt"
    __platform__ = "PTT"
    __supported_type__ = ["图文"]
    __match__ = r"^(http(s)?://)?.+ptt.cc/bbs/.*"

    async def parse(self, url: str) -> "PTTImageParseResult":
        url = await self.get_raw_url(url)
        parsed = await PTTCC.parse(url, proxy=self.cfg.proxy, cookies=self.cfg.cookie)
        media = [Image(path=img, thumb_url=img) for img in (parsed.imgs or [])]
        return PTTImageParseResult(
            title=parsed.title or "",
            photo=media,
            desc=parsed.text_content or parsed.markdown_content or "",
            raw_url=url,
            pttcc=parsed,
        )


class PTTImageParseResult(ImageParseResult):
    def __init__(self, title: str, photo: list[str], desc: str, raw_url: str, pttcc: "PTTCC"):
        super().__init__(title, photo, desc, raw_url)
        self.pttcc = pttcc
    
    async def download(
        self,
        path: str | Path = None,
        callback: Callable[[int, int, str | None, tuple], Awaitable[None]] = None,
        callback_args: tuple = (),
        config: DownloadConfig = DownloadConfig(),
    ) -> DownloadResult:
        headers = config.headers or {"User-Agent": GlobalConfig.ua}
        headers["Accept"] = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
        )
        config.headers = headers
        return await super().download(path, callback, callback_args, config)

__all__ = ["PTTParser", "PTTImageParseResult"]
