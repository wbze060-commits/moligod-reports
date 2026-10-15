# -*- coding: utf-8 -*-
"""Refresh verified Delta Force announcements from the public Steam News API."""
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
from urllib.parse import urlparse

APP_ID = 2507950
FEED_NAME = "steam_community_announcements"
API_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
API_PAGE = "https://partner.steamgames.com/doc/webapi/ISteamNews"
NEWS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "news.json")
STATUS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "news_refresh_status.json")
MAX_AGE_DAYS = 30
MAX_HEADLINES = 5
MARKET_TERMS = {
    "ammo": ("ammo", "ammunition", "bullet", "shell", "弹药", "子弹"),
    "balance": ("weapon balance", "balance adjustment", "weapon adjustment", "武器平衡", "枪械平衡"),
    "season": ("season ammo", "season update", "new season", "赛季子弹", "赛季更新"),
    "economy": ("rmt", "trade", "market", "economy", "trading", "交易", "市场", "经济", "处罚"),
}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.suppressed = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.suppressed += 1
        elif tag in ("p", "br", "li", "div", "h1", "h2", "h3"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.suppressed:
            self.suppressed -= 1
        elif tag in ("p", "li", "div"):
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.suppressed:
            self.parts.append(data)


def clean_announcement_text(value):
    parser = _TextExtractor()
    parser.feed(str(value or ""))
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def _utc_now(value=None):
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _relevance_tags(title, summary):
    text = (title + " " + summary).lower()
    return [tag for tag, terms in MARKET_TERMS.items() if any(term in text for term in terms)]


def _safe_article_url(item):
    url = str(item.get("url") or "")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "https" and (
        host == "steamcommunity.com"
        or host == "store.steampowered.com"
        or host.endswith(".akamaihd.net")
    ):
        return url
    gid = str(item.get("gid") or "")
    return "https://steamcommunity.com/app/%d/announcements/detail/%s" % (APP_ID, gid)


def parse_news_payload(payload, now=None, max_age_days=MAX_AGE_DAYS, limit=MAX_HEADLINES):
    current = _utc_now(now)
    appnews = payload.get("appnews") if isinstance(payload, dict) else None
    if not isinstance(appnews, dict) or not isinstance(appnews.get("newsitems"), list):
        raise ValueError("Steam News response is missing appnews.newsitems")

    headlines = []
    for item in appnews["newsitems"]:
        if not isinstance(item, dict) or item.get("feedname") != FEED_NAME:
            continue
        try:
            published = datetime.fromtimestamp(int(item["date"]), timezone.utc)
        except (KeyError, TypeError, ValueError, OSError):
            continue
        age = current - published
        if age < timedelta(hours=-6) or age > timedelta(days=max_age_days):
            continue

        title = clean_announcement_text(item.get("title"))
        summary = clean_announcement_text(item.get("contents"))
        tags = _relevance_tags(title, summary)
        if not title or not tags:
            continue

        headline = {
            "gid": str(item.get("gid") or ""),
            "title": title[:240],
            "summary": summary[:600],
            "source": "Steam Community Announcements",
            "scope": "Steam 国际服",
            "feed": FEED_NAME,
            "tags": tags,
            "url": _safe_article_url(item),
            "published_at": published.isoformat().replace("+00:00", "Z"),
            "fetched_at": current.isoformat().replace("+00:00", "Z"),
            "expires_at": (published + timedelta(days=max_age_days)).isoformat().replace("+00:00", "Z"),
        }
        headlines.append(headline)

    headlines.sort(key=lambda x: x["published_at"], reverse=True)
    return {
        "schema_version": 2,
        "updated": current.isoformat().replace("+00:00", "Z"),
        "source": {
            "name": "Steam Community Announcements",
            "scope": "Steam 国际服；仅作官方事实公告，不自动推断国服价格",
            "app_id": APP_ID,
            "feed": FEED_NAME,
            "api_url": API_URL,
            "documentation_url": API_PAGE,
        },
        "headlines": headlines[:limit],
        "outlook": [],
        "risk": "官方公告不等于价格预测。价格判断只使用报告中的 moligod 行情和滚动统计。",
    }


def fetch_news_payload():
    query = urllib.parse.urlencode({
        "appid": APP_ID,
        "count": 50,
        "maxlength": 4000,
        "feeds": FEED_NAME,
    })
    request = urllib.request.Request(
        API_URL + "?" + query,
        headers={"Accept": "application/json", "User-Agent": "moligod-reports/1.0"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def _write_json_atomic(path, value):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".news-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def refresh_news(news_path=NEWS_PATH, status_path=STATUS_PATH, fetcher=fetch_news_payload, now=None):
    current = _utc_now(now)
    attempted_at = current.isoformat().replace("+00:00", "Z")
    previous_status = {}
    try:
        with open(status_path, encoding="utf-8") as stream:
            previous_status = json.load(stream)
    except (OSError, ValueError):
        pass

    try:
        document = parse_news_payload(fetcher(), now=current)
        _write_json_atomic(news_path, document)
        _write_json_atomic(status_path, {
            "status": "ok",
            "checked_at": attempted_at,
            "last_success_at": document["updated"],
            "headline_count": len(document["headlines"]),
            "error": None,
        })
        print("NEWS_REFRESH_OK headlines=%d" % len(document["headlines"]))
        return True
    except Exception as exc:
        _write_json_atomic(status_path, {
            "status": "error",
            "checked_at": attempted_at,
            "last_success_at": previous_status.get("last_success_at"),
            "headline_count": previous_status.get("headline_count", 0),
            "error": str(exc)[:200],
        })
        print("NEWS_REFRESH_FAILED", type(exc).__name__, str(exc)[:160])
        return False


def main():
    return 0 if refresh_news() else 1


if __name__ == "__main__":
    raise SystemExit(main())
