import re
import json
from typing import Dict, Any

from mediaflow_proxy.extractors.base import BaseExtractor, ExtractorError

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)


class VKExtractor(BaseExtractor):

    async def extract(self, url: str, **kwargs) -> Dict[str, Any]:

        # Normalize URL
        embed_url = self._normalize(url)
        ajax_url = self._get_ajax_url(embed_url)
        ajax_data = self._get_ajax_data(embed_url)

        headers = {
            "User-Agent": UA,
            "Referer": "https://vkvideo.ru/",
            "Origin": "https://vkvideo.ru",
            "Cookie": "remixlang=0",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
        }

        # 1️⃣ CALL act=show TO GET DASH URL
        response = await self._make_request(
            ajax_url,
            method="POST",
            data=ajax_data,
            headers=headers
        )

        raw = (response.text or "").lstrip("<!--")
        try:
            js = json.loads(raw)
        except:
            raise ExtractorError("VK: invalid JSON payload")

        # 2️⃣ EXTRACT DASH MPD FROM PAYLOAD
        mpd_url = self._extract_dash(js)
        if not mpd_url:
            raise ExtractorError("VK: No DASH MPD found")

        # MPD URL is missing the host → add it (vkvideo CDN server)
        full_mpd = self._complete_mpd(embed_url, mpd_url)

        return {
            "destination_url": full_mpd,
            "request_headers": headers,
            "mediaflow_endpoint": "mpd_manifest_proxy",
        }

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    def _normalize(self, url: str) -> str:
        if "video_ext.php" in url:
            return url

        m = re.search(r"video(-?\d+)_(\d+)", url)
        if not m:
            return url

        oid, vid = m.group(1), m.group(2)
        return f"https://vkvideo.ru/video_ext.php?oid={oid}&id={vid}"

    def _get_ajax_url(self, embed_url: str) -> str:
        host = re.search(r"https?://([^/]+)", embed_url).group(1)
        return f"https://{host}/al_video.php?act=show"

    def _get_ajax_data(self, embed_url: str):
        qs = re.findall(r"([a-zA-Z0-9_]+)=([^&]+)", embed_url)
        qs = dict(qs)

        return {
            "act": "show",
            "al": 1,
            "video": f"{qs.get('oid')}_{qs.get('id')}"
        }

    # ------------------------------------------------------------
    # PARSE DASH URL
    # ------------------------------------------------------------

    def _extract_dash(self, js):
        """
        Looks inside:
        payload → player → cache → data → dash
        """
        payload = []

        for item in js.get("payload", []):
            if isinstance(item, list):
                payload = item

        for item in payload:
            if not isinstance(item, dict):
                continue

            player = item.get("player", {})
            cache = player.get("cache", {}).get("data", {})

            # MAIN DASH SOURCE
            dash = cache.get("dash")
            if dash:
                return dash

            # SOME VK RETURNS dash_manifest instead
            dash2 = player.get("dash_manifest")
            if dash2:
                return dash2

        return None

    # ------------------------------------------------------------
    # COMPLETE MPD URL
    # ------------------------------------------------------------

    def _complete_mpd(self, embed_url: str, mpd: str) -> str:
        """
        VK returns MPD starting with ?expires=...
        Add correct host of video_ext.php file.
        """
        host = re.search(r"https?://([^/]+)", embed_url).group(1)
        origin = f"https://{host}/"

        if mpd.startswith("?"):
            return origin + mpd

        return mpd
