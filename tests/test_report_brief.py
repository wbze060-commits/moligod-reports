import importlib.util
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, mock_open

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from report_brief import brief_for_plan, push_summary, render_brief_section
from report_data import CHINA_TZ

NOW=datetime(2026,10,16,14,0,tzinfo=CHINA_TZ)
META={'completed_at_utc':NOW.astimezone(timezone.utc).isoformat()}

def plan(kind='daily', qualified=False, latest_bar=None):
    start=NOW.replace(hour=6,minute=0) if kind=='daily' else NOW.replace(hour=6,minute=0)
    end=NOW.replace(hour=18,minute=59) if kind=='daily' else NOW.replace(day=18,hour=18,minute=59)
    item={'name':'TestAmmo <script>alert(1)</script>', 'qualified':qualified,
          'qualification':'通过历史筛选' if qualified else '回测样本或表现不足',
          'latest':100,'latest_bar_at':(latest_bar or NOW.replace(hour=13,minute=0)).isoformat(),
          'buy_low':95,'buy_high':100,'sell_target':130,'invalidate_below':95,
          'break_even':115,'break_even_with_slippage':118,'net_per_round':10,
          'net_margin_pct':10,'exit_at_floor_net_loss_pct':19}
    return {'id':kind+'-2026-10-16','region':'CN','kind':kind,'valid_from':start.isoformat(),
            'valid_until':end.isoformat(),'config':{'region':'CN','fee_rate':.13,'sale_slippage':.02,
              'quote_drop_limit':.05,'max_quote_age_minutes':180,'morning_hours':[6,11],'afternoon_hours':[13,18]},
            'risk':'verify CN', 'candidates':[item]}

class BriefTests(unittest.TestCase):
    def test_unqualified_observation_is_not_promoted_to_buy_card(self):
        brief=brief_for_plan(plan(qualified=False),META,NOW)
        self.assertIn('观望',brief['title'])
        self.assertEqual(brief['cards'],[])
        self.assertIn('没有通过筛选',brief['sentence'])

    def test_compact_card_keeps_buy_sell_expiry_and_displays_no_html_injection(self):
        brief=brief_for_plan(plan(qualified=True),META,NOW)
        markup=render_brief_section(brief)
        self.assertIn('买 95–100',markup)
        self.assertIn('卖 ≥130',markup)
        self.assertIn('06–11买',markup)
        self.assertNotIn('<script>alert',markup)

    def test_push_summary_has_at_most_two_cards_and_both_report_links(self):
        item=plan(qualified=True)['candidates'][0]
        p=plan(qualified=True);p['candidates']=[dict(item,name='A'),dict(item,name='B'),dict(item,name='C')]
        brief=brief_for_plan(p,META,NOW)
        text=push_summary(brief,'2026-10-16','https://example.invalid/reports/')
        self.assertEqual(len(brief['cards']),2)
        self.assertIn('[打开精简报告 HTML]',text)
        self.assertIn('[PDF 版]',text)
        self.assertNotIn('**C**',text)
        self.assertLess(len(text),420)

    def test_stale_quotes_pause_and_do_not_show_buy_now(self):
        stale=plan(qualified=True,latest_bar=NOW.replace(hour=7))
        brief=brief_for_plan(stale,META,NOW)
        self.assertEqual(brief['cards'][0]['state'],'STALE')
        self.assertIn('行情待更新',brief['title'])

    def test_qualification_is_required_before_action_state(self):
        stale=plan(qualified=False,latest_bar=NOW.replace(hour=7))
        brief=brief_for_plan(stale,META,NOW)
        self.assertEqual(brief['cards'],[])

    def test_tomorrow_plan_never_says_buy_now_before_the_window(self):
        future=plan(qualified=True)
        future['valid_from']=NOW.replace(day=17,hour=6).isoformat()
        future['valid_until']=NOW.replace(day=17,hour=18,minute=59).isoformat()
        brief=brief_for_plan(future,META,NOW)
        self.assertIn('明日',brief['title'])
        self.assertNotIn('BUY_ZONE',[card['state'] for card in brief['cards']])


class ReportDensityTests(unittest.TestCase):
    def test_full_market_search_is_collapsed_and_has_keyboard_controls(self):
        from cloud_report_all import render_daily
        rows=[{'name':'bullet %d'%i,'grade':str(i%3+3),'latest':i+10,'chg':i/10,
               'amp':None} for i in range(67)]
        html=render_daily(rows,'2026-10-16')
        self.assertIn('<details class="secondary-section" id="market-details">',html)
        self.assertIn('id="ammo-search"',html)
        self.assertIn('aria-live="polite"',html)
        self.assertIn('data-grade-filter="3"',html)
        self.assertEqual(html.count('<table'),2)
        self.assertIn('67/67款',html)
        self.assertNotIn('振幅 TOP5',html)

    def test_rendered_page_adds_mobile_layout_and_brief_precedes_appendix(self):
        from cloud_report_all import main
        from report_data import CHINA_TZ
        from datetime import datetime, timedelta
        now=datetime.now(CHINA_TZ)
        start=now+timedelta(days=1)
        base=plan(qualified=False)
        base['valid_from']=start.replace(hour=6,minute=0,second=0,microsecond=0).isoformat()
        base['valid_until']=start.replace(hour=18,minute=59,second=0,microsecond=0).isoformat()
        loaded={'catalog.json':{'1':{'name':'Fixture','grade':'3','latest':100}},
                'history_latest.json':{},'market_meta.json':META,'news.json':{'region':'CN','source':{'name':'CN'}},
                'news_refresh_status.json':{'status':'manual_only'}}
        writer=mock_open()
        with patch('cloud_report_all.load_json',side_effect=lambda name:loaded.get(name)), \
             patch('cloud_report_all.get_plan',return_value=(base,META)), \
             patch('cloud_report_all.open',writer,create=True), \
             patch('cloud_report_all.sys.argv',['cloud_report_all.py','daily',str(ROOT/'unused-daily.html')]):
            main()
        rendered=''.join(call.args[0] for call in writer().write.call_args_list)
        self.assertIn('name="viewport"',rendered)
        self.assertLess(rendered.index('class="daily-brief"'),rendered.index('id="market-details"'))
        self.assertIn('明日先观望',rendered)
        self.assertEqual(rendered.count('<table'),4)
        self.assertIn('13%手续费',rendered)

    def test_monthly_report_does_not_request_a_weekly_trade_plan(self):
        from cloud_report_all import main
        loaded={'catalog.json':{'1':{'name':'Fixture','grade':'3','latest':100}},
                'history_latest.json':{},'market_meta.json':META,'news.json':{},'news_refresh_status.json':{}}
        writer=mock_open()
        with patch('cloud_report_all.load_json',side_effect=lambda name:loaded.get(name)), \
             patch('cloud_report_all.get_plan',side_effect=AssertionError('monthly should not create a weekly plan')), \
             patch('cloud_report_all.open',writer,create=True), \
             patch('cloud_report_all.sys.argv',['cloud_report_all.py','monthly',str(ROOT/'unused-monthly.html')]):
            main()
        rendered=''.join(call.args[0] for call in writer().write.call_args_list)
        self.assertNotIn('周抛买卖计划',rendered)
        self.assertIn('国服公告',rendered)

    def test_push_uses_brief_and_legacy_report_is_link_only(self):
        from cloud_push import extract_report_brief
        from report_brief import push_summary, render_brief_section
        briefing=brief_for_plan(plan(qualified=True),META,NOW)
        markup=render_brief_section(briefing)
        decoded=extract_report_brief(markup)
        self.assertEqual(decoded['plan_id'],briefing['plan_id'])
        summary=push_summary(decoded,'2026-10-16','https://example.invalid/reports/')
        self.assertIn('买95–100',summary)
        self.assertIn('卖≥130',summary)
        self.assertNotIn('涨幅 TOP3',summary)

if __name__=='__main__':
    unittest.main(verbosity=2)
