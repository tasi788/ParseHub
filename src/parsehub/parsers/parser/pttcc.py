from ..base.base import BaseParser
from ...types import Image, ImageParseResult
from ...provider_api.pttcc import PTTCC

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

__all__ = ["PTTParser", "PTTImageParseResult"]
