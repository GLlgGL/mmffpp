import json
import re
from typing import Dict, Any

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)


class VKExtractor(BaseExtractor):

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:
        """
        VK extractor that returns ONLY DASH MPD links.
        Never returns MP4.
        Never returns full-file type=1/type=3 URLs.
        """

        embed_url = self._normalize(url)
        ajax_url = self._build_ajax_url(embed_url)

        headers = {
            "User-Agent": UA,
            "Referer": "https://vkvideo.ru/",
            "Origin": "https://vkvideo.ru",
            "Cookie": "remixlang=0",
            "X-Requested-With": "XMLHttpRequest",
            "Accept-Encoding": "gzip, deflate, br",
        }

        data = self._build_ajax_data(embed_url)

        # Request data
        response = await self._make_request(
            ajax_url, method="POST", data=data, headers=headers
        )

        text = response.text.lstrip("<!--")

        try:
            js = json.loads(text)
        except:
            raise ExtractorError("VK: invalid JSON payload")

        # ---------------------------------------------------
        # DASH MPD extraction (ONLY allowed output)
        # ---------------------------------------------------
        mpd = self._extract_mpd(js)
        if not mpd:
            raise ExtractorError("VK: No DASH MPD found")

        # ---------------------------------------------------
        # VK MPD returns base URL without `bytes=`
        # We do NOT append bytes. MediaFlow MPD/HLS pipeline handles it.
        # ---------------------------------------------------

        # MUST ensure this is not the full-file URL
        if not self._is_valid_mpd_url(mpd):
            raise ExtractorError("VK: MPD URL is invalid (full-file detected)")

        # Send MPD to MediaFlow DASH → HLS converter
        return {
            "destination_url": mpd,
            "request_headers": headers,
            "mediaflow_endpoint": "mpd_manifest_proxy",
        }

    # =====================================================================
    # Helpers
    # =====================================================================

    def _normalize(self, url: str) -> str:
        if "video_ext.php" in url:
            return url
        m = re.search(r"video(-?\d+)_(\d+)", url)
        if not m:
            return url
        return f"https://vk.com/video_ext.php?oid={m.group(1)}&id={m.group(2)}"

    def _build_ajax_url(self, embed_url: str) -> str:
        host = re.search(r"https?://([^/]+)", embed_url).group(1)
        return f"https://{host}/al_video.php?act=show"

    def _build_ajax_data(self, embed_url: str):
        qs = re.search(r"\?(.*)", embed_url)
        parts = dict(x.split("=") for x in qs.group(1).split("&")) if qs else {}
        return {
            "act": "show",
            "al": "1",
            "video": f"{parts.get('oid')}_{parts.get('id')}",
        }

    # =====================================================================
    # DASH MPD extraction
    # =====================================================================

    def _extract_mpd(self, js: Any) -> str | None:
        payload = []
        for item in js.get("payload", []):
            if isinstance(item, list):
                payload = item

        for item in payload:
            if not isinstance(item, dict):
                continue

            player = item.get("player", {})

            # Type 1: direct MPD
            mpd = player.get("dash_manifest")
            if mpd:
                return mpd

            # Type 2: cached MPD
            mpd2 = player.get("cache", {}).get("data", {}).get("dash")
            if mpd2:
                return mpd2

        return None

    # =====================================================================
    # Validate that MPD URL is NOT full-file MP4 URL
    # =====================================================================

    def _is_valid_mpd_url(self, url: str) -> bool:
        """
        VK full-file URLs contain:
        - no bytes=
        - fromCache=1
        - ch=
        - appId=
        - ct=0 or ct=6
        """

        # MPD should NEVER contain these fields
        forbidden = [
            "fromCache=1",
            "ch=",
            "appId=",
            "ct=0",
            "ct=6",
            "type=1",  # full-file video
            "type=3",  # full-file HD
        ]

        if any(f in url for f in forbidden):
            return False

        return True
