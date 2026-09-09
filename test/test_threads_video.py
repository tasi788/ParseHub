import unittest
from unittest.mock import AsyncMock, Mock, patch

from parsehub import ParseHub
from parsehub.types import VideoRef


class TestThreadsVideoUrl(unittest.IsolatedAsyncioTestCase):
    async def test_video_url_extracts_video_through_provider(self):
        url = "https://www.threads.com/@onyourch__loe/video/DdDmhIokdZC/video-%E8%B7%9F/"
        response = Mock()
        response.text = '''for (;;);{"thread_items":[{"post":{
            "code":"DdDmhIokdZC","caption":{"text":"影片貼文"},
            "media_type":2,"original_width":720,"original_height":1280,
            "image_versions2":{"candidates":[{"url":"https://cdn.example/thumb.jpg"}]},
            "video_versions":[{"url":"https://cdn.example/video.mp4"}]
        }}]}'''
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.post.return_value = response

        with patch("parsehub.provider_api.threads.httpx.AsyncClient", return_value=client):
            result = await ParseHub().parse(url)

        self.assertEqual(result.content, "影片貼文")
        self.assertEqual(len(result.media), 1)
        self.assertIsInstance(result.media[0], VideoRef)
        self.assertEqual(result.media[0].url, "https://cdn.example/video.mp4")
        self.assertEqual(
            client.post.await_args.kwargs["data"]["route_url"],
            "/onyourch__loe/post/DdDmhIokdZC",
        )
