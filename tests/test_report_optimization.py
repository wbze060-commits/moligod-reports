import json
import os
import sys
import unittest
from io import StringIO
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(os.environ["PROJECT_ROOT"])
sys.path.insert(0, str(PROJECT))

import cloud_report_all

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


class NewsRefreshTests(unittest.TestCase):
    def test_official_market_news_is_normalized_and_stale_or_external_items_are_dropped(self):
        import cloud_news
        payload = {"region":"CN", "headlines":[
            {"title":"Ammo update", "summary":"Official ammunition patch", "region":"CN",
             "published_at":(NOW-timedelta(days=1)).isoformat(), "url":"https://df.qq.com/news/example.html"},
            {"title":"Old", "region":"CN", "published_at":(NOW-timedelta(days=40)).isoformat(),
             "url":"https://df.qq.com/news/old.html"},
            {"title":"Overseas ammo", "region":"GLOBAL", "published_at":NOW.isoformat(),
             "url":"https://steamcommunity.com/news"}]}
        doc = cloud_news.parse_news_payload(payload, now=NOW)
        self.assertEqual([item["title"] for item in doc["headlines"]], ["Ammo update"])
        self.assertEqual(doc["region"], "CN")
        self.assertIn("expires_at", doc["headlines"][0])

    def test_html_script_content_is_removed_from_announcement_text(self):
        import cloud_news
        text = cloud_news.clean_announcement_text("<p>Ammo update</p><script>bad()</script>")
        self.assertEqual(text, "Ammo update")

    def test_expired_and_legacy_outlook_is_hidden(self):
        data = {
            "headlines":[
                {"title":"fresh","expires_at":(NOW+timedelta(days=1)).isoformat()},
                {"title":"expired","expires_at":(NOW-timedelta(seconds=1)).isoformat()}],
            "outlook":[
                {"line":"current view","expires_at":(NOW+timedelta(days=1)).isoformat()},
                {"line":"expired view","expires_at":(NOW-timedelta(days=1)).isoformat()},
                {"line":"legacy view"}]}
        result = cloud_report_all.filter_fresh_news(data, now=NOW)
        self.assertEqual([x["title"] for x in result["headlines"]], ["fresh"])
        self.assertEqual([x["line"] for x in result["outlook"]], ["current view"])

    def test_refresh_failure_preserves_last_successful_news(self):
        import cn_news
        original = {"updated":"2026-10-01T00:00:00Z","headlines":[{"title":"last good"}]}
        stored = {'news.json': json.dumps(original)}
        writes = {}
        def fail_fetch():
            raise OSError("offline")
        with patch.object(cn_news, '_write', side_effect=lambda path, value: writes.update({Path(path).name: value})):
            ok = cn_news.refresh_news('news.json', 'status.json', fetcher=fail_fetch, now=NOW)
        self.assertFalse(ok)
        self.assertEqual(json.loads(stored['news.json']), original)
        self.assertEqual(writes['status.json']['status'], 'error')
class RollingMarketTests(unittest.TestCase):
    def test_date_parser_handles_iso_and_month_day_rollover(self):
        as_of = datetime(2026, 1, 3).date()
        self.assertEqual(cloud_report_all.parse_history_date("2025-12-31",as_of),datetime(2025,12,31).date())
        self.assertEqual(cloud_report_all.parse_history_date("12-31",as_of),datetime(2025,12,31).date())
        self.assertEqual(cloud_report_all.parse_history_date("01-02",as_of),datetime(2026,1,2).date())

    def test_overlapping_ranges_do_not_double_count_a_day(self):
        as_of = datetime(2026,10,15).date()
        history = {
            "r30":[{"time":"2026-10-15","min":90,"max":110,"avg":100,"last":105}],
            "r15":[{"time":"2026-10-15","min":20,"max":30,"avg":25,"last":25}],
            "r7":[{"time":"2026-10-15","min":5,"max":10,"avg":8,"last":8}]}
        days = cloud_report_all.collect_daily(history,as_of=as_of)
        self.assertEqual(days["2026-10-15"]["avg"],100)

    def test_rolling_seven_day_vs_previous_twenty_three_day_stats(self):
        as_of = datetime(2026,10,15).date()
        days={}
        for i in range(30):
            day=as_of-timedelta(days=29-i)
            value=i+1
            days[day.isoformat()]={"low":value-1,"high":value+1,"avg":value,"avg_n":1,"last":value}
        stats=cloud_report_all.rolling_stats(days,as_of=as_of,recent_days=7,baseline_days=23)
        self.assertEqual(stats["recent"]["start"],"2026-10-09")
        self.assertEqual(stats["recent"]["end"],"2026-10-15")
        self.assertEqual(stats["recent"]["avg"],27)
        self.assertEqual(stats["baseline"]["start"],"2026-09-16")
        self.assertEqual(stats["baseline"]["end"],"2026-10-08")
        self.assertEqual(stats["baseline"]["avg"],12)

    def test_report_shows_market_collection_time_and_rolling_basis(self):
        meta={"source":"moligod.com","completed_at_utc":"2026-10-15T12:00:00Z"}
        line=cloud_report_all.format_market_meta(meta)
        self.assertIn("采集时间",line)
        self.assertIn("北京时间",line)
        self.assertIn("7天",line)
        self.assertIn("前23天",line)



class ReportRenderingTests(unittest.TestCase):
    def test_stale_news_is_hidden_and_current_source_is_escaped(self):
        fresh = {
            "region":"CN", "source":{"name":"三角洲行动国服官网","scope":"国服"},
            "updated":"2026-10-15T12:00:00Z",
            "headlines":[
                {"title":"<Ammo update>","summary":"<b>official</b>",
                 "source":"三角洲行动国服官网","scope":"国服","region":"CN",
                 "tags":["ammo"],"url":"https://steamcommunity.com/app/2507950/announcements/detail/1",
                 "published_at":"2026-10-15T11:00:00Z","expires_at":"2026-11-14T11:00:00Z"},
                {"title":"old rumor","summary":"old","source":"unknown",
                 "expires_at":"2026-10-14T00:00:00Z"}],
            "outlook":[],"risk":"facts only"}
        from cloud_report_all import render_news_section
        rendered = render_news_section(fresh,{"status":"ok","last_success_at":"2026-10-15T12:00:00Z"},now=NOW)
        self.assertIn("&lt;Ammo update&gt;",rendered)
        self.assertNotIn("old rumor",rendered)
        self.assertIn("国服",rendered)
        self.assertIn("查看来源",rendered)

    def test_weekly_renderer_does_not_duplicate_shared_rolling_table(self):
        from cloud_report_all import render_weekly_monthly
        rendered = render_weekly_monthly([], "weekly", "2026-10-15")
        self.assertNotIn("滚动行情比较",rendered)



class PushSummaryTests(unittest.TestCase):
    def test_wechat_summary_extracts_new_official_announcement_cards(self):
        from cloud_push import extract_news
        html = (
            '<h2>官方公告与有效观点</h2>'
            '<article class="news-item"><b>Fresh official ammo update</b>'
            '<div>Steam Community Announcements</div><p>Season ammunition changes</p></article>'
            '<article class="news-item"><b>Second announcement</b><p>Balance update</p></article>'
        )
        extracted = extract_news(html, limit=1)
        self.assertEqual(len(extracted), 1)
        self.assertIn("Fresh official ammo update", extracted[0])
        self.assertIn("Season ammunition changes", extracted[0])


class WorkflowIntegrationTests(unittest.TestCase):
    def test_all_report_workflows_refresh_news_before_rendering(self):
        for name in ("daily-report.yml","weekly-report.yml","monthly-report.yml"):
            with self.subTest(workflow=name):
                text=(PROJECT/".github"/"workflows"/name).read_text(encoding="utf-8")
                self.assertIn("cloud_news.py",text)
                self.assertLess(text.index("cloud_news.py"),text.index("cloud_report_all.py"))
                self.assertIn("continue-on-error: true",text)
                self.assertIn("workflow_dispatch:",text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
