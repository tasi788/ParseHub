from dataclasses import dataclass
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from markdownify import MarkdownConverter

from ..config import GlobalConfig


@dataclass
class PTTCC:
    title: str | None = None
    markdown_content: str | None = None
    text_content: str | None = None
    imgs: list[str] | None = None

    @classmethod
    async def parse(cls, url: str, proxy: str = None, cookies: dict | None = None) -> "PTTCC":
        request_cookies = {"over18": "1"}
        if isinstance(cookies, dict):
            request_cookies.update(cookies)

        async with httpx.AsyncClient(
            headers={"User-Agent": GlobalConfig.ua}, proxy=proxy, cookies=request_cookies
        ) as client:
            response = await client.get(url)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        main = soup.select_one("#main-content")
        if not main:
            raise ValueError("获取内容失败")

        content_soup = BeautifulSoup(str(main), "html.parser")
        content = content_soup.select_one("#main-content") or content_soup

        title = None
        for metaline in content.select(".article-metaline, .article-metaline-right"):
            tag = metaline.select_one(".article-meta-tag")
            value = metaline.select_one(".article-meta-value")
            if tag and value and tag.text.strip() == "標題":
                title = value.text.strip()
            metaline.decompose()

        for push in content.select("div.push"):
            push.decompose()

        polling = content.select_one("#article-polling")
        if polling:
            polling.decompose()

        for span in content.select("span.f2"):
            span.decompose()

        imgs: list[str] = []
        for img in content.find_all("img", src=True):
            src = img["src"].strip()
            if not src:
                continue
            absolute_src = urljoin(url, src)
            if absolute_src not in imgs:
                imgs.append(absolute_src)

        img_exts = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
        for anchor in content.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href:
                continue
            absolute_href = urljoin(url, href)
            lower = absolute_href.lower().split("?")[0]
            if any(lower.endswith(ext) for ext in img_exts):
                anchor.decompose()

        inner_html = content.decode_contents()
        markdown_content = MarkdownConverter(heading_style="ATX").convert(inner_html).strip() or None

        raw_text = content.get_text("\n")
        for anchor in content.find_all("a", href=True):
            href = anchor["href"].strip()
            if href:
                raw_text = raw_text.replace(href, "")
        lines = [line.rstrip() for line in raw_text.splitlines()]
        text_lines: list[str] = []
        last_blank = False
        image_set = set(imgs)
        for line in lines:
            stripped = line.strip()
            if stripped == "--":
                continue
            normalized = stripped.strip("<>")
            if normalized and normalized in image_set:
                continue
            if not stripped:
                if not last_blank:
                    text_lines.append("")
                last_blank = True
                continue
            text_lines.append(stripped)
            last_blank = False

        while text_lines and text_lines[-1] == "":
            text_lines.pop()
        text_content = "\n".join(text_lines).strip() or None

        if not title and soup.title:
            title = soup.title.text.strip()

        if not (text_content or imgs):
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and (desc := meta_desc.get("content", "").strip()):
                text_content = desc

        if title or text_content or imgs:
            return cls(title=title, markdown_content=markdown_content, text_content=text_content, imgs=imgs or None)

        raise ValueError("获取内容失败")
