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

        # 先移除 -- 分隔線之後的所有內容（包含推文區的作者留言）
        # 找到最後一個 -- 分隔線，且下一行包含 "※ 發信站"
        separator_element = None
        for element in content.descendants:
            if element.string and element.string.strip() == "--":
                # 檢查下一個兄弟元素是否包含 "※ 發信站"
                next_sibling = element.next_sibling
                while next_sibling:
                    if hasattr(next_sibling, 'get_text'):
                        sibling_text = next_sibling.get_text()
                    elif isinstance(next_sibling, str):
                        sibling_text = next_sibling
                    else:
                        sibling_text = ""
                    
                    if "※ 發信站" in sibling_text:
                        separator_element = element
                        break
                    # 只檢查緊鄰的幾個元素
                    if sibling_text.strip():
                        break
                    next_sibling = next_sibling.next_sibling
        
        # 移除找到的分隔線及之後的所有內容
        if separator_element:
            next_siblings = list(separator_element.next_siblings)
            for sibling in next_siblings:
                if hasattr(sibling, 'decompose'):
                    sibling.decompose()
            if hasattr(separator_element, 'decompose'):
                separator_element.decompose()

        # 移除推文區（如果還有殘留）
        for push in content.select("div.push"):
            push.decompose()

        polling = content.select_one("#article-polling")
        if polling:
            polling.decompose()

        for span in content.select("span.f2"):
            span.decompose()

        imgs: list[str] = []
        img_exts = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp")
        for anchor in content.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href:
                continue
            absolute_href = urljoin(url, href)
            lower = absolute_href.lower().split("?")[0]
            if any(lower.endswith(ext) for ext in img_exts):
                imgs.append(absolute_href)

        inner_html = content.decode_contents()
        markdown_content = MarkdownConverter(heading_style="ATX").convert(inner_html).strip() or None

        raw_text = content.get_text("\n")
        lines = [line.rstrip() for line in raw_text.splitlines()]
        text_lines: list[str] = []
        last_blank = False
        for line in lines:
            stripped = line.strip()
            if stripped == "--":
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
