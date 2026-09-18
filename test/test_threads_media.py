import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from parsehub import ParseHub
from parsehub.types import ImageRef, VideoRef


def image_post(code="target"):
    return {
        "code": code,
        "caption": {"text": "圖片貼文"},
        "media_type": 1,
        "original_width": 1080,
        "original_height": 1350,
        "image_versions2": {
            "candidates": [{"url": f"https://cdn.example/{code}.jpg", "width": 1080, "height": 1350}]
        },
        "video_versions": None,
    }


def video_post(code="quoted"):
    return {
        "code": code,
        "user": {"username": "quoted_author"},
        "caption": {"text": "引用影片"},
        "media_type": 2,
        "original_width": 720,
        "original_height": 1280,
        "image_versions2": {"candidates": [{"url": f"https://cdn.example/{code}.jpg"}]},
        "video_versions": [{"url": f"https://cdn.example/{code}.mp4"}],
    }


def text_post(code="target", **app_info):
    return {
        "code": code,
        "caption": {"text": "貼文內容"},
        "media_type": 19,
        "text_post_app_info": {"linked_inline_media": None, **app_info},
    }


def target_frame(post):
    # Shape captured from the route-definition response for the reported URLs.
    return {
        "__type": "preloader",
        "id": "adp_BarcelonaPostPageTargetQueryRelayPreloader_fixture",
        "result": {"result": {"data": {"media": post}}},
    }


class TestThreadsMedia(unittest.IsolatedAsyncioTestCase):
    async def parse_frames(self, frames, url="https://www.threads.com/@user/post/target"):
        response = Mock()
        response.text = "".join("for (;;);" + json.dumps(frame) for frame in frames)
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.post.return_value = response

        with patch("parsehub.provider_api.threads.httpx.AsyncClient", return_value=client):
            return await ParseHub().parse(url)

    async def test_target_preloader_extracts_image(self):
        result = await self.parse_frames([target_frame(image_post())])

        self.assertEqual(result.content, "圖片貼文")
        self.assertEqual(len(result.media), 1)
        self.assertIsInstance(result.media[0], ImageRef)
        self.assertEqual(result.media[0].url, "https://cdn.example/target.jpg")
        self.assertEqual((result.media[0].width, result.media[0].height), (1080, 1350))

    async def test_target_preloader_extracts_mixed_carousel_in_order(self):
        post = {
            "code": "target",
            "caption": {"text": "相簿"},
            "media_type": 8,
            "carousel_media": [image_post("first"), video_post("second"), image_post("third")],
        }
        result = await self.parse_frames([target_frame(post)])

        self.assertEqual([type(media) for media in result.media], [ImageRef, VideoRef, ImageRef])
        self.assertEqual(
            [media.url for media in result.media],
            ["https://cdn.example/first.jpg", "https://cdn.example/second.mp4", "https://cdn.example/third.jpg"],
        )

    async def test_reported_quoted_posts_extract_video_and_thumbnail(self):
        cases = [
            ("venus69717", "DdaOMEEgSJ5", "DdZg7zXgrOf"),
            ("victor_laowang", "DdYmgB1j_6s", "DdYKjpNiao4"),
        ]
        for username, code, quoted_code in cases:
            with self.subTest(code=code):
                post = text_post(
                    code,
                    share_info={"quoted_post": None, "quoted_attachment_post": video_post(quoted_code)},
                )
                result = await self.parse_frames(
                    [target_frame(post)], f"https://www.threads.com/@{username}/post/{code}"
                )

                self.assertEqual(len(result.media), 1)
                self.assertIsInstance(result.media[0], VideoRef)
                self.assertEqual(result.media[0].url, f"https://cdn.example/{quoted_code}.mp4")
                self.assertEqual(result.media[0].thumb_url, f"https://cdn.example/{quoted_code}.jpg")
                self.assertIn("@quoted_author:", result.content)
                self.assertIn("引用影片", result.content)
                self.assertTrue(result.content.endswith("貼文內容"))

    async def test_quoted_image_supports_both_attachment_field_names(self):
        for field in ("quoted_attachment_post", "quoted_post"):
            with self.subTest(field=field):
                post = text_post(share_info={field: image_post("quoted")})
                result = await self.parse_frames([target_frame(post)])

                self.assertEqual(len(result.media), 1)
                self.assertIsInstance(result.media[0], ImageRef)
                self.assertEqual(result.media[0].url, "https://cdn.example/quoted.jpg")
                self.assertIn("[圖片] 圖片貼文", result.content)

    async def test_own_media_takes_priority_over_quoted_media(self):
        post = image_post()
        post["text_post_app_info"] = {"share_info": {"quoted_attachment_post": video_post()}}
        result = await self.parse_frames([target_frame(post)])

        self.assertEqual([media.url for media in result.media], ["https://cdn.example/target.jpg"])
        self.assertIn("引用影片", result.content)

    async def test_inline_media_takes_priority_over_quoted_media(self):
        post = text_post(
            linked_inline_media=image_post("inline"),
            share_info={"quoted_attachment_post": video_post()},
        )
        result = await self.parse_frames([target_frame(post)])

        self.assertEqual([media.url for media in result.media], ["https://cdn.example/inline.jpg"])

    async def test_text_reply_does_not_download_parent_media(self):
        frames = [{"thread_items": [{"post": image_post("parent")}, {"post": text_post()}]}]
        result = await self.parse_frames(frames)

        self.assertEqual(result.media, [])
        self.assertIn("[圖片] 圖片貼文", result.content)
        self.assertTrue(result.content.endswith("貼文內容"))

    async def test_unavailable_quote_keeps_text_without_media(self):
        for quote in (None, {"code": "unavailable", "caption": None}):
            with self.subTest(quote=quote):
                post = text_post(share_info={"quoted_post": None, "quoted_attachment_post": quote})
                result = await self.parse_frames([target_frame(post)])

                self.assertEqual(result.media, [])
                self.assertEqual(result.content, "貼文內容")

    async def test_unrelated_posts_do_not_supply_media(self):
        frames = [
            {"thread_items": [{"post": image_post("unrelated")}]},
            target_frame(image_post("wrong_target")),
            target_frame(text_post()),
        ]
        result = await self.parse_frames(frames)

        self.assertEqual(result.media, [])
        self.assertEqual(result.content, "貼文內容")

    async def test_legacy_lightbox_preloader_still_extracts_image(self):
        frames = [
            {
                "__type": "preloader",
                "id": "BarcelonaLightboxDialogRootQueryRelayPreloader_fixture",
                "result": {"result": {"data": {"data": image_post()}}},
            }
        ]
        result = await self.parse_frames(frames)

        self.assertEqual([media.url for media in result.media], ["https://cdn.example/target.jpg"])
