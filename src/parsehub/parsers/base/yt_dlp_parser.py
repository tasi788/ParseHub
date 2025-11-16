import asyncio
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from yt_dlp import YoutubeDL

from ...config.config import DownloadConfig, GlobalConfig
from ...types import (
    DownloadError,
    DownloadResult,
    ImageParseResult,
    ParseError,
    Subtitles,
    Video,
    VideoParseResult,
)
from .base import BaseParser

EXC = ProcessPoolExecutor()


def download_video(yto_params: dict, urls: list[str]) -> None:
    """在独立进程中下载视频"""
    try:
        with YoutubeDL(yto_params) as ydl:
            return ydl.download(urls)
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"
        raise RuntimeError(error_msg) from None


class YtParser(BaseParser):
    """yt-dlp解析器"""

    async def parse(self, url: str) -> Union["YtVideoParseResult", "YtImageParseResult"]:
        url = await self.get_raw_url(url)
        video_info = await self._parse(url)
        _d = {
            "title": video_info.title,
            "desc": video_info.description,
            "raw_url": url,
            "dl": video_info,
        }
        return YtVideoParseResult(video=video_info.url, **_d)

    async def _parse(self, url) -> "YtVideoInfo":
        try:
            dl = await asyncio.wait_for(asyncio.to_thread(self._extract_info, url), timeout=30)
        except TimeoutError as e:
            raise ParseError("解析影片資訊逾時") from e
        except Exception as e:
            raise ParseError(f"解析影片資訊失敗: {str(e)}") from e

        if dl.get("_type"):
            dl = dl["entries"][0]
            url = dl["webpage_url"]
        title = dl["title"]
        duration = dl.get("duration", 0) or 0
        thumbnail = dl["thumbnail"]
        description = dl["description"]
        width = dl.get("width", 0) or 0
        height = dl.get("height", 0) or 0
        return YtVideoInfo(
            raw_video_info=dl,
            title=title,
            description=description,
            thumbnail=thumbnail,
            duration=duration,
            url=url,
            width=width,
            height=height,
            paramss=self.params,
        )

    def _extract_info(self, url):
        params = self.params.copy()
        if self.cfg.proxy:
            params["proxy"] = self.cfg.proxy

        try:
            with YoutubeDL(params) as ydl:
                return ydl.extract_info(url, download=False)
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            raise RuntimeError(error_msg) from None

    @property
    def params(self) -> dict:
        params = {
            "format": "mp4+bestvideo[height<=1080]+bestaudio",
            "quiet": True,  # 不输出日志
            # "writethumbnail": True,  # 下载缩略图
            # "postprocessors": [
            #     {
            #         "key": "FFmpegVideoConvertor",
            #         "preferedformat": "mp4",  # 视频格式
            #     }
            # ],
            "playlist_items": "1",  # 分p列表默认解析第一个
        }
        return params


class YtVideoParseResult(VideoParseResult):
    def __init__(
        self,
        title=None,
        video=None,
        desc=None,
        raw_url=None,
        dl: "YtVideoInfo" = None,
    ):
        """dl: yt-dlp解析结果"""
        self.dl = dl
        super().__init__(title=title, video=video, desc=desc, raw_url=raw_url)

    async def download(
        self,
        path: str | Path = None,
        callback: Callable[[int, int, str | None, tuple], Awaitable[None]] = None,
        callback_args: tuple = (),
        config: DownloadConfig = DownloadConfig(),
    ) -> DownloadResult:
        """下载视频"""
        if not self.media.is_url:
            return self.media

        # 创建保存目录
        dir_ = (config.save_dir if path is None else Path(path)).joinpath(f"{time.time_ns()}")
        dir_.mkdir(parents=True, exist_ok=True)

        # 输出模板
        paramss = self.dl.paramss.copy()
        if config.proxy:
            paramss["proxy"] = config.proxy

        paramss["outtmpl"] = f"{dir_.joinpath('ytdlp_%(id)s')}.%(ext)s"

        text = "🗜️下載合併影音畫面中..."
        if GlobalConfig.duration_limit and self.dl.duration > GlobalConfig.duration_limit:
            # 视频超过限制时长，获取最低画质
            text += f"\n影片超過 {GlobalConfig.duration_limit} 秒，獲取最低畫質"
            paramss["format"] = "worstvideo* + worstaudio / worst"

        if callback:
            await callback(0, 0, text, *callback_args)

        await self._download(paramss)

        v = list(dir_.glob("*.mp4")) or list(dir_.glob("*.mkv")) or list(dir_.glob("*.webm"))
        if not v:
            raise DownloadError("找不到下載完成的影片")
        video_path = v[0]
        subtitles = (v := list(dir_.glob("*.ttml"))) and Subtitles.parse(v[0])
        return DownloadResult(
            self,
            Video(
                path=str(video_path),
                subtitles=subtitles,
                thumb_url=self.dl.thumbnail,
                height=self.dl.height,
                width=self.dl.width,
                duration=self.dl.duration,
            ),
            dir_,
        )

    async def _download(self, paramss: dict, count: int = 0) -> None:
        if count > 2:
            raise DownloadError("下载失败")

        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(EXC, download_video, paramss, [self.media.path]),
                timeout=300,
            )
        except TimeoutError as e:
            raise DownloadError("下載逾時") from e
        except RuntimeError as e:
            error = str(e)
            if any(
                msg in error
                for msg in (
                    "Unable to download video subtitles",
                    "Requested format is not available",
                )
            ):
                paramss.pop("writeautomaticsub")
                await self._download(paramss, count + 1)

        except Exception as e:
            raise DownloadError(f"下载失败: {str(e)}") from e


class YtImageParseResult(ImageParseResult):
    def __init__(self, title="", photo=None, desc=None, raw_url=None, dl: "YtVideoInfo" = None):
        """dl: yt-dlp解析结果"""
        self.dl = dl
        super().__init__(title=title, photo=photo, desc=desc, raw_url=raw_url)


@dataclass
class YtVideoInfo:
    """raw_video_info: yt-dlp解析结果"""

    raw_video_info: dict
    title: str
    description: str
    thumbnail: str
    url: str
    duration: int = 0
    width: int = 0
    height: int = 0
    paramss: dict = None
