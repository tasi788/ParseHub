import json
import random
import re
import string
from dataclasses import dataclass
from enum import Enum

import httpx

from ..config.config import GlobalConfig


class ThreadsAPI:
    def __init__(self, proxy: str = None):
        self.proxy = proxy

    async def parse(self, url: str):
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
    def random_lsd():
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
    media: ThreadsMedia | list[ThreadsMedia] = None

    @classmethod
    def parse(cls, jsonp: list[dict], target_id: str):
        content = ""
        media = []
        
        # 尋找目標貼文與其父貼文 (Reply) 或 Quote
        target_post, quote_post = cls._extract_target_and_quote(jsonp, target_id)
        
        if target_post:
            content = target_post.get("caption", {}).get("text", "")
            media = cls._fetch_media(target_post)
            
            # 若為引用的貼文，則將其文字加到主文前面
            if quote_post:
                quote_author = quote_post.get("user", {}).get("username", "user")
                quote_text = quote_post.get("caption", {}).get("text", "")
                
                # 若父文章有媒體，在文字開頭加上 [圖片]
                if cls._fetch_media(quote_post):
                    quote_text = f"[圖片] {quote_text}" if quote_text else "[圖片]"
                    
                if quote_text:
                    if len(quote_text) > 600:
                        quote_text = quote_text[:600] + "......"
                    content = f"<blockquote expandable>@{quote_author}:\n{quote_text}</blockquote>\n\n{content}"
        else:
            # Fallback 到舊版解析邏輯，避免某些結構無法解析
            for j in jsonp:
                match j.get("__type"):
                    case "first_response":
                        content = cls._fetch_content(j)
                    case "preloader":
                        if "BarcelonaLightboxDialogRootQueryRelayPreloader" in j.get("id", ""):
                            media = cls._fetch_media(j)

        return cls(content=content, media=media)
        
    @classmethod
    def _extract_target_and_quote(cls, jsonp: list[dict], target_id: str):
        target_post = None
        quote_post = None
        
        def find_thread_items(d):
            results = []
            if isinstance(d, dict):
                if "thread_items" in d and isinstance(d["thread_items"], list):
                    results.append(d["thread_items"])
                for k, v in d.items():
                    results.extend(find_thread_items(v))
            elif isinstance(d, list):
                for item in d:
                    results.extend(find_thread_items(item))
            return results

        all_items = find_thread_items(jsonp)
        for items in all_items:
            for i, item in enumerate(items):
                post = item.get("post", {})
                if post.get("code") == target_id:
                    target_post = post
                    # 如果是回覆，上一篇就是引用的文章
                    if i > 0:
                        quote_post = items[i-1].get("post", {})
                    break
            if target_post:
                break
                
        # 檢查是否為顯式引用 (Quote feature)
        if target_post and not quote_post:
            explicit_quote = target_post.get("text_post_app_info", {}).get("share_info", {}).get("quoted_post")
            if explicit_quote:
                quote_post = explicit_quote
                
        return target_post, quote_post

    @staticmethod
    def _fetch_media(data: dict):
        # 兼容舊版 preloader wrapper
        if "result" in data:
            data = data.get("result", {}).get("result", {}).get("data", {}).get("data")
            
        if not data:
            return []

        def fn(d):
            media = []
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
