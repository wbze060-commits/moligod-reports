# -*- coding: utf-8 -*-
"""CN announcement entry point; overseas feeds are not a fallback."""
from cn_news import clean_announcement_text, fetch_news_payload, main, parse_news_payload, refresh_news

if __name__ == '__main__':
    raise SystemExit(main())
