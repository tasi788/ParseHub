from __future__ import annotations

import asyncio
import json
from typing import Any, NamedTuple, cast

try:
    import stealth_requests as requests
except ImportError:
    import requests
from bs4 import BeautifulSoup


class FacebookPost(NamedTuple):
    author_name: str
    text: str
    image_links: list[str]
    url: str
    date: int
    likes: str
    comments: str
    shares: str


class FacebookException(Exception):
    pass


class Jq:
    @staticmethod
    def enumerate(obj: dict[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []

        def collect(value: object) -> None:
            if isinstance(value, dict):
                result.append(cast(dict[str, Any], value))
                for item in value.values():
                    if isinstance(item, list):
                        collect(item)
                for item in value.values():
                    if isinstance(item, dict):
                        collect(item)
                for item in value.values():
                    if not isinstance(item, dict | list):
                        collect(item)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        collect(item)
                for item in value:
                    if isinstance(item, list):
                        collect(item)
                for item in value:
                    if not isinstance(item, dict | list):
                        collect(item)

        collect(obj)
        return result

    @staticmethod
    def iterate(obj: dict[str, Any], key: str, first: bool = False) -> list[Any] | Any | None:
        result: list[Any] = []
        for item in Jq.enumerate(obj):
            if key in item:
                if first:
                    return item[key]
                result.append(item[key])
        return result

    @staticmethod
    def all(obj: dict[str, Any], key: str) -> list[Any]:
        result = Jq.iterate(obj, key, first=False)
        return result if isinstance(result, list) else []

    @staticmethod
    def first(obj: dict[str, Any], key: str) -> Any:
        value = Jq.iterate(obj, key, first=True)
        if value is None:
            raise FacebookException(f"cannot find {key}")
        return value


class FacebookAPI:
    WWWFB = "https://www.facebook.com"

    def __init__(self, proxy: str | None = None, cookies: dict[str, str] | None = None):
        self.proxy = proxy
        self.cookies = cookies or {}

    @staticmethod
    def get_headers() -> dict[str, str]:
        return {
            "accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/jxl,image/avif,image/webp,image/apng,*/*;q=0.8"
            ),
            "accept-language": "en-US,en;q=0.9",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        }

    @staticmethod
    def get_json_blocks(html_parser: BeautifulSoup, sort: bool = True) -> list[str]:
        script_elements = html_parser.find_all(
            "script",
            attrs={"type": "application/json", "data-content-len": True, "data-sjs": True},
        )
        if sort:
            script_elements.sort(
                key=lambda element: int(cast(str, element.attrs["data-content-len"])),
                reverse=True,
            )
        return [element.text for element in script_elements]

    @staticmethod
    def get_post_json(html_parser: BeautifulSoup) -> dict[str, Any]:
        for json_block in FacebookAPI.get_json_blocks(html_parser):
            if "i18n_reaction_count" in json_block:
                bloc = json.loads(json_block)
                if bloc:
                    return cast(dict[str, Any], bloc)
        raise FacebookException("cannot find post json")

    @staticmethod
    def get_interaction_counts(post_json: dict[str, Any]) -> tuple[str, str, str]:
        post_feedback = cast(dict[str, Any], Jq.first(post_json, "comet_ufi_summary_and_actions_renderer"))
        feedback = post_feedback["feedback"]
        reactions = feedback["i18n_reaction_count"]
        shares = feedback["i18n_share_count"]
        comments = feedback["comment_rendering_instance"]["comments"]["total_count"]
        return str(reactions), str(comments), str(shares)

    @staticmethod
    def get_root_node(post_json: dict[str, Any]) -> dict[str, Any]:
        def work_normal_post() -> dict[str, Any]:
            data_blob = cast(dict[str, Any], Jq.first(post_json, "data"))
            if "comet_ufi_summary_and_actions_renderer" in data_blob:
                return data_blob
            if "node" in data_blob:
                return cast(dict[str, Any], data_blob["node"]["comet_sections"])
            if "node_v2" in data_blob:
                return cast(dict[str, Any], data_blob["node_v2"]["comet_sections"])
            return cast(dict[str, Any], data_blob["node"]["comet_sections"])

        def work_group_post() -> dict[str, Any]:
            hoisted_feed = cast(dict[str, Any], Jq.first(post_json, "group_hoisted_feed"))
            return cast(dict[str, Any], Jq.first(hoisted_feed, "comet_sections"))

        for method in (work_normal_post, work_group_post):
            try:
                ret = method()
            except (StopIteration, KeyError, FacebookException):
                continue
            if ret:
                return ret
        raise FacebookException("Cannot process post")

    @staticmethod
    def get_image_links(post_json: dict[str, Any]) -> list[str]:
        all_attachments = Jq.all(post_json, "attachment")
        for attachment_set in all_attachments:
            if not isinstance(attachment_set, dict):
                continue
            if any(key.endswith("subattachments") for key in attachment_set):
                subsets = [
                    value
                    for key, value in attachment_set.items()
                    if key.endswith("subattachments") and isinstance(value, dict) and "nodes" in value
                ]
                if not subsets:
                    continue
                typed_subsets = [cast(dict[str, Any], subset) for subset in subsets]
                max_image_count = len(max(typed_subsets, key=lambda item: len(item["nodes"]))["nodes"])
                subsets = [
                    subset
                    for subset in typed_subsets
                    if len(subset["nodes"]) == max_image_count and Jq.all(subset, "viewer_image")
                ]
                if subsets:
                    images = [item["uri"] for item in Jq.all(subsets[0], "viewer_image")]
                    if images:
                        return images
            elif "media" in attachment_set and "'__typename': 'Sticker'" not in str(attachment_set):
                simple_set = [item["uri"] for item in Jq.all(attachment_set, "photo_image")]
                if simple_set:
                    return simple_set

        for attachment in Jq.all(post_json, "comet_photo_attachment_resolution_renderer"):
            return [attachment["image"]["uri"]]
        return []

    def _fetch_post_sync(self, url: str) -> str:
        proxies = None
        if self.proxy:
            proxies = {
                "http": self.proxy,
                "https": self.proxy,
            }

        response = requests.get(
            url,
            headers=self.get_headers(),
            cookies=self.cookies,
            proxies=proxies,
            timeout=30,
            allow_redirects=True,
        )
        response.raise_for_status()
        return str(response.text)

    async def parse_post(self, url: str) -> FacebookPost:
        if not url.startswith(self.WWWFB):
            url = f"{self.WWWFB}/{url.removeprefix('/')}"

        html_text = await asyncio.to_thread(self._fetch_post_sync, url)
        html_parser = BeautifulSoup(html_text, "html.parser")

        post_json = self.get_root_node(self.get_post_json(html_parser))
        likes, comments, shares = self.get_interaction_counts(post_json)
        post_date = int(
            cast(
                int | str,
                Jq.first(
                    cast(dict[str, Any], post_json["context_layout"]["story"]["comet_sections"]["metadata"]),
                    "creation_time",
                ),
            )
        )
        story = cast(dict[str, Any], post_json["content"]["story"])

        author_name = story["actors"][0]["name"]
        text = story["message"]["text"] if story.get("message") and "text" in story["message"] else ""
        image_links = self.get_image_links(story)
        post_url = story["wwwURL"]

        return FacebookPost(
            author_name=author_name,
            text=text,
            image_links=image_links,
            url=post_url,
            date=post_date,
            likes=likes,
            comments=comments,
            shares=shares,
        )


__all__ = ["FacebookAPI", "FacebookPost", "FacebookException"]
