import re
import json
import asyncio
from typing import NamedTuple
from urllib.parse import urlparse

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
    """JSON query helper from facebed"""
    
    @staticmethod
    def enumerate(obj: dict):
        result = []

        def collect(value):
            if isinstance(value, dict):
                result.append(value)
                for v in value.values():
                    if isinstance(v, list):
                        collect(v)
                for v in value.values():
                    if isinstance(v, dict):
                        collect(v)
                for v in value.values():
                    if not isinstance(v, (dict, list)):
                        collect(v)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        collect(item)
                for item in value:
                    if isinstance(item, list):
                        collect(item)
                for item in value:
                    if not isinstance(item, (dict, list)):
                        collect(item)

        collect(obj)
        return result

    @staticmethod
    def iterate(obj: dict, key: str, first: bool = False):
        result = []
        for oo in Jq.enumerate(obj):
            if key in oo:
                if first:
                    return oo[key]
                else:
                    result.append(oo[key])
        return result

    @staticmethod
    def all(obj: dict, key: str) -> list[dict]:
        return Jq.iterate(obj, key, first=False)

    @staticmethod
    def first(obj: dict, key: str) -> dict:
        return Jq.iterate(obj, key, first=True)


class FacebookAPI:
    """Facebook API using facebed approach"""
    
    WWWFB = 'https://www.facebook.com'
    
    def __init__(self, proxy: str | None = None, cookies: dict | None = None):
        self.proxy = proxy
        self.cookies = cookies or {}
    
    @staticmethod
    def get_headers() -> dict:
        return {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/jxl,image/avif,image/webp,image/apng,*/*;q=0.8',
            'accept-language': 'en-US,en;q=0.9',
            'cache-control': 'no-cache',
            'pragma': 'no-cache',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
    
    @staticmethod
    def get_json_blocks(html_parser: BeautifulSoup, sort=True) -> list[str]:
        script_elements = html_parser.find_all('script', attrs={'type': 'application/json', 'data-content-len': True, 'data-sjs': True})
        if sort:
            script_elements.sort(key=lambda e: int(e.attrs['data-content-len']), reverse=True)
        return [e.text for e in script_elements]
    
    @staticmethod
    def get_post_json(html_parser: BeautifulSoup) -> dict:
        for json_block in FacebookAPI.get_json_blocks(html_parser):
            if 'i18n_reaction_count' in json_block:
                bloc = json.loads(json_block)
                assert bloc
                return bloc
        raise FacebookException('cannot find post json')
    
    @staticmethod
    def get_interaction_counts(post_json: dict) -> tuple[str, str, str]:
        assert post_json
        post_feedback = Jq.first(post_json, 'comet_ufi_summary_and_actions_renderer')
        assert post_feedback
        reactions = post_feedback['feedback']['i18n_reaction_count']
        shares = post_feedback['feedback']['i18n_share_count']
        comments = post_feedback['feedback']['comment_rendering_instance']['comments']['total_count']
        return str(reactions), str(comments), str(shares)
    
    @staticmethod
    def get_root_node(post_json: dict) -> dict:
        def work_normal_post() -> dict:
            data_blob = Jq.first(post_json, 'data')
            if 'comet_ufi_summary_and_actions_renderer' in data_blob:
                return data_blob
            else:
                return data_blob['node']['comet_sections']

        def work_group_post() -> dict:
            hoisted_feed = Jq.first(post_json, 'group_hoisted_feed')
            comet_section = Jq.first(hoisted_feed, 'comet_sections')
            return comet_section

        methods = [work_normal_post, work_group_post]

        for method in methods:
            try:
                ret = method()
                if ret:
                    return ret
                else:
                    continue
            except (StopIteration, KeyError):
                continue

        raise FacebookException('Cannot process post')
    
    @staticmethod
    def get_image_links(post_json: dict) -> list[str]:
        all_attachments = Jq.all(post_json, 'attachment')
        for attachment_set in all_attachments:
            if any([k.endswith('subattachments') for k in attachment_set]):
                subsets = [v for k, v in attachment_set.items() if k.endswith('subattachments') and 'nodes' in v]
                max_image_count = len(max(subsets, key=lambda it: len(it['nodes']))['nodes'])
                subsets = [subset for subset in subsets if
                           len(subset['nodes']) == max_image_count and Jq.all(subset, 'viewer_image')]
                images = [x['uri'] for x in Jq.all(subsets[0], 'viewer_image')]
                if images:
                    return images
            elif 'media' in attachment_set and "'__typename': 'Sticker'" not in str(attachment_set):
                simple_set = [x['uri'] for x in Jq.all(attachment_set, 'photo_image')]
                if simple_set:
                    return simple_set
        
        # Fallback for single image
        for aa in Jq.all(post_json, 'comet_photo_attachment_resolution_renderer'):
            return [aa['image']['uri']]
        return []
    
    def _fetch_post_sync(self, url: str) -> str:
        """Synchronous fetch using stealth_requests"""
        # 設置 proxies
        proxies = None
        if self.proxy:
            proxies = {
                'http': self.proxy,
                'https': self.proxy
            }
        
        # 使用 stealth_requests 發送請求
        response = requests.get(
            url,
            headers=self.get_headers(),
            cookies=self.cookies,
            proxies=proxies,
            timeout=30,
            allow_redirects=True
        )
        response.raise_for_status()
        return response.text
    
    async def parse_post(self, url: str) -> FacebookPost:
        """Parse Facebook post"""
        if not url.startswith(self.WWWFB):
            url = f"{self.WWWFB}/{url.removeprefix('/')}"
        
        # 在線程池中執行同步請求
        html_text = await asyncio.to_thread(self._fetch_post_sync, url)
        html_parser = BeautifulSoup(html_text, 'html.parser')
        
        post_json = self.get_root_node(self.get_post_json(html_parser))
        likes, cmts, shares = self.get_interaction_counts(post_json)
        post_date = int(Jq.first(post_json['context_layout']['story']['comet_sections']['metadata'], 'creation_time'))
        post_json = post_json['content']['story']
        
        author_name = post_json['actors'][0]['name']
        text = post_json['message']['text'] if (post_json['message'] and 'text' in post_json['message']) else ''
        image_links = self.get_image_links(post_json)
        post_url = post_json['wwwURL']
        
        return FacebookPost(
            author_name=author_name,
            text=text,
            image_links=image_links,
            url=post_url,
            date=post_date,
            likes=likes,
            comments=cmts,
            shares=shares
        )


__all__ = ["FacebookAPI", "FacebookPost", "FacebookException"]
