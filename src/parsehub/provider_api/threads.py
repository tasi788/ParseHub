from __future__ import annotations

import json
import random
import re
import string
from dataclasses import dataclass
from enum import Enum

import httpx

from ..config.config import GlobalConfig


class ThreadsAPI:
    def __init__(self, proxy: str | None = None):
        self.proxy = proxy

    async def parse(self, url: str) -> ThreadsPost:
        lsd = self.random_lsd()
        headers = {
            "content-type": "application/x-www-form-urlencoded",
            "sec-fetch-site": "same-origin",
            "user-agent": GlobalConfig.ua,
            "x-fb-lsd": lsd,
        }

        target_id = self.get_post_id_by_url(url)
        data = {
            "route_url": f"/{self.get_username_by_url(url)}/post/{target_id}",
            "routing_namespace": "barcelona_web",
            "__user": "0",
            "__a": "1",
            "__req": "m",
            "__comet_req": "29",
            "lsd": lsd,
        }

        async with httpx.AsyncClient(proxy=self.proxy) as client:
            response = await client.post("https://www.threads.com/ajax/route-definition", headers=headers, data=data)
            response.raise_for_status()
            jsonp = [json.loads(j.strip()) for j in response.text.strip().split("for (;;);") if j]
            return ThreadsPost.parse(jsonp, target_id)

    @staticmethod
    def get_username_by_url(url: str) -> str:
        u = re.search(r"/(?:@)?([\w.]+)/post/", url)
        if not u:
            raise ValueError("从 URL 中获取用户名失败")
        return u[1]

    @staticmethod
    def get_post_id_by_url(url: str) -> str:
        p = re.search(r"/post/([\w-]+)", url)
        if not p:
            raise ValueError("从 URL 中获取帖子 ID 失败")
        return p[1]

    @staticmethod
    def random_lsd() -> str:
        return "".join(random.sample(string.ascii_letters + string.digits, 11))


class ThreadsMediaType(Enum):
    IMAGE = "image"
    VIDEO = "video"


@dataclass
class ThreadsMedia:
    type: ThreadsMediaType
    url: str
    thumb_url: str | None = None
    width: int = 0
    height: int = 0


@dataclass
class ThreadsPost:
    content: str
    media: ThreadsMedia | list[ThreadsMedia] | None = None

    @classmethod
    def parse(cls, jsonp: list[dict], target_id: str) -> ThreadsPost:
        content = ""
        media: ThreadsMedia | list[ThreadsMedia] | None = []

        target_post, quote_post = cls._extract_target_and_quote(jsonp, target_id)
        if target_post:
            content = (target_post.get("caption") or {}).get("text", "")
            media = cls._fetch_media(target_post)

            if quote_post:
                quote_author = quote_post.get("user", {}).get("username", "user")
                quote_text = (quote_post.get("caption") or {}).get("text", "")
                if cls._fetch_media(quote_post):
                    quote_text = f"[圖片] {quote_text}" if quote_text else "[圖片]"
                if quote_text:
                    if len(quote_text) > 600:
                        quote_text = quote_text[:600] + "......"
                    content = f"<blockquote expandable>@{quote_author}:\n{quote_text}</blockquote>\n\n{content}"
        else:
            for j in jsonp:
                match j.get("__type"):
                    case "first_response":
                        content = cls._fetch_content(j)
                    case "preloader":
                        if "BarcelonaLightboxDialogRootQueryRelayPreloader" in (j.get("id") or ""):
                            media = cls._fetch_media(j)
                    case "last_response":
                        ...

        return cls(content=content, media=media)

    @classmethod
    def _extract_target_and_quote(cls, jsonp: list[dict], target_id: str) -> tuple[dict | None, dict | None]:
        target_post = None
        quote_post = None

        def find_thread_items(data: dict | list) -> list[list[dict]]:
            results: list[list[dict]] = []
            if isinstance(data, dict):
                if "thread_items" in data and isinstance(data["thread_items"], list):
                    results.append(data["thread_items"])
                for value in data.values():
                    results.extend(find_thread_items(value))
            elif isinstance(data, list):
                for item in data:
                    results.extend(find_thread_items(item))
            return results

        for items in find_thread_items(jsonp):
            for index, item in enumerate(items):
                post = item.get("post", {})
                if post.get("code") == target_id:
                    target_post = post
                    if index > 0:
                        quote_post = items[index - 1].get("post", {})
                    break
            if target_post:
                break

        if target_post and not quote_post:
            share_info = target_post.get("text_post_app_info", {}).get("share_info", {})
            quote_post = share_info.get("quoted_post")

        return target_post, quote_post

    @staticmethod
    def _fetch_content(data: dict) -> str:
        payload = data.get("payload", {})
        result = payload.get("result", {})
        # 尝试从 redirect_result 获取（用户更改名称后的情况）
        meta = result.get("redirect_result", {}).get("exports", {}).get("meta")
        # 如果没有 redirect_result，则从正常路径获取
        if not meta:
            meta = result.get("exports", {}).get("meta")
        if not meta:
            return ""
        return str(meta["title"])

    @staticmethod
    def _fetch_media(data: dict) -> ThreadsMedia | list[ThreadsMedia]:
        if "result" in data:
            data = data.get("result", {}).get("result", {}).get("data", {}).get("data")
        if not data:
            return []

        def fn(d: dict) -> ThreadsMedia | list[ThreadsMedia]:
            media: ThreadsMedia | list[ThreadsMedia]
            match d["media_type"]:
                case 1:  # 单张图片
                    image = d["image_versions2"]["candidates"][0]
                    media = ThreadsMedia(
                        type=ThreadsMediaType.IMAGE,
                        url=image["url"],
                        thumb_url=image["url"],
                        width=image["width"],
                        height=image["height"],
                    )
                case 2:  # 单个视频
                    thumb = d["image_versions2"]["candidates"][0]["url"]
                    video = d["video_versions"][0]["url"]
                    media = ThreadsMedia(
                        type=ThreadsMediaType.VIDEO,
                        url=video,
                        thumb_url=thumb,
                        width=d["original_width"],
                        height=d["original_height"],
                    )
                case 8:  # 多图/视频
                    carousel_media = d["carousel_media"]
                    media = []
                    for m in carousel_media:
                        if m["video_versions"]:
                            thumb = m["image_versions2"]["candidates"][0]["url"]
                            video = m["video_versions"][0]["url"]
                            media.append(
                                ThreadsMedia(
                                    type=ThreadsMediaType.VIDEO,
                                    url=video,
                                    thumb_url=thumb,
                                    width=m["original_width"],
                                    height=m["original_height"],
                                )
                            )
                        else:
                            image = m["image_versions2"]["candidates"][0]["url"]
                            media.append(
                                ThreadsMedia(
                                    type=ThreadsMediaType.IMAGE,
                                    url=image,
                                    thumb_url=image,
                                    width=m["original_width"],
                                    height=m["original_height"],
                                )
                            )
                case 19:  # 纯文本/外部链接
                    if linked_inline_media := d["text_post_app_info"]["linked_inline_media"]:
                        media = fn(linked_inline_media)
                    else:
                        media = []
                case _:
                    media = []
            return media

        return fn(data)
