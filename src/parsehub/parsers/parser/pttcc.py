from __future__ import annotations

from pathlib import Path

from ...config import GlobalConfig
from ...provider_api.pttcc import PTTCC
from ...types import DownloadResult, ImageRef, ProgressCallback, RichTextParseResult
from ...types.platform import Platform
from ..base.base import BaseParser


class PTTRichTextParseResult(RichTextParseResult):
    def __init__(
        self,
        *,
        title: str | None = "",
        media: list[ImageRef] | None = None,
        markdown_content: str | None = "",
        proxy: str | None = None,
    ):
        self.parse_proxy = proxy
        super().__init__(title=title, media=media, markdown_content=markdown_content)

    async def _do_download(
        self,
        *,
        output_dir: str | Path,
        callback: ProgressCallback | None = None,
        callback_args: tuple = (),
        callback_kwargs: dict | None = None,
        proxy: str | None = None,
        headers: dict | None = None,
    ) -> DownloadResult:
        resolved_proxy = proxy or self.parse_proxy
        resolved_headers = {"User-Agent": GlobalConfig.ua}
        if headers:
            resolved_headers.update(headers)
        return await super()._do_download(
            output_dir=output_dir,
            callback=callback,
            callback_args=callback_args,
            callback_kwargs=callback_kwargs,
            proxy=resolved_proxy,
            headers=resolved_headers,
        )


class PTTParser(BaseParser):
    __platform__ = Platform.PTT
    __supported_type__ = ["图文"]
    __match__ = r"^(http(s)?://)?.+ptt\.cc/bbs/.*"

    async def _do_parse(self, raw_url: str) -> PTTRichTextParseResult:
        parsed = await PTTCC.parse(raw_url, proxy=self.proxy, cookies=self.cookie)
        media = [ImageRef(url=img, thumb_url=img) for img in (parsed.imgs or [])]
        return PTTRichTextParseResult(
            title=parsed.title or "",
            media=media,
            markdown_content=parsed.markdown_content or parsed.text_content or "",
            proxy=self.proxy,
        )


__all__ = ["PTTParser", "PTTRichTextParseResult"]
