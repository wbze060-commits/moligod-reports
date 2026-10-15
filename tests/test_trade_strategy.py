import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('PROJECT_ROOT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
from report_data import CHINA_TZ, collect_daily, collect_hourly, parse_history_time
import trade_strategy as trade

NOW = datetime(2026, 10, 15, 8, tzinfo=CHINA_TZ)
META = {'completed_at_utc': NOW.astimezone(timezone.utc).isoformat()}


def history_fixture():
    points = []
    for day in range(15, 0, -1):
        date = (NOW - timedelta(days=day)).date()
        for hour in range(24):
            price = 100 if hour <= 11 else 130
            points.append({'time': date.isoformat() + ' %02d:00' % hour,
                           'avg': price, 'min': price - 1, 'max': price + 1, 'last': price})
    return {'r30': [], 'r15': points, 'r7': []}


def candidate():
    return {'item_id':'1', 'name':'TEST CN', 'grade':'3', 'qualified':True, 'qualification':'通过历史筛选',
            'buy_low':95, 'buy_high':100, 'sell_target':130, 'invalidate_below':95,
            'latest_bar_at':NOW.replace(hour=7).isoformat(), 'latest':100,
            'break_even':115, 'break_even_with_slippage':118, 'net_per_round':10.84,
            'net_margin_pct':10.84, 'exit_at_floor_net_loss_pct':19.0}


def plan_fixture(kind='daily'):
    return {'id':kind+'-2026-10-15','kind':kind,'region':'CN','config':trade.settings(),
            'valid_from':NOW.replace(hour=6).isoformat(),'valid_until':NOW.replace(hour=18, minute=59).isoformat(),
            'candidates':[candidate()], 'risk':'fixtures'}


class HistoryTests(unittest.TestCase):
    def test_archive_backfill_keeps_recent_snapshot_and_calendar_window(self):
        from cloud_fetch import archived_daily
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            folder=Path(directory)
            def save(day,price):
                data={'1':{'r30':[{'time':'2026-10-01','avg':price,'min':price,'max':price,'last':price},
                                  {'time':'2026-08-01','avg':1,'min':1,'max':1,'last':1}]}}
                (folder/('history_'+day+'.json')).write_text(json.dumps(data),encoding='utf-8')
            save('2026-10-01',100); save('2026-10-14',120)
            result=archived_daily(folder,NOW.date())
            self.assertEqual(result['1']['2026-10-01']['avg'],120)
            self.assertNotIn('2026-08-01',result['1'])
    def test_hourly_fallback_aggregates_all_hours_and_prefers_recent_duplicate(self):
        hist = {'r30': [], 'r15':[{'time':'10-14 06:00','avg':80,'min':70,'max':90,'last':85},
                                 {'time':'10-14 07:00','avg':120,'min':100,'max':130,'last':125}],
                'r7':[{'time':'10-14 06:00','avg':100,'min':90,'max':110,'last':105}]}
        result = collect_daily(hist, NOW.date())
        self.assertEqual(result['2026-10-14']['avg'],110)
        self.assertEqual(result['2026-10-14']['last'],125)
        self.assertEqual(result['2026-10-14']['hours'],2)

    def test_year_rollover_invalid_dates_and_epoch_timezone(self):
        self.assertEqual(parse_history_time('12-31 23:00', datetime(2026,1,2).date()).year,2025)
        self.assertIsNone(parse_history_time('02-30 09:00', NOW))
        stamp = datetime(2026,10,14,23,tzinfo=timezone.utc).timestamp()
        self.assertEqual(parse_history_time(stamp,NOW).hour,7)
        self.assertEqual(parse_history_time(stamp,NOW).day,15)


class StrategyTests(unittest.TestCase):
    def test_daily_trains_then_validates_without_bar_extrema_as_fills(self):
        config = trade.settings()
        hist = history_fixture()
        model, reason = trade.daily_model(hist,NOW,config)
        self.assertIsNone(reason)
        self.assertEqual(model['backtest']['fills'],5)
        self.assertEqual(model['backtest']['target_hits'],5)
        self.assertAlmostEqual(model['net_per_round'],10.84,2)
        bad = copy.deepcopy(hist)
        for row in bad['r15']:
            row['min'], row['max'] = 1,100000
        other,_=trade.daily_model(bad,NOW,config)
        self.assertEqual(model,other)

    def test_future_points_do_not_change_model(self):
        hist = history_fixture()
        before,_ = trade.daily_model(hist,NOW,trade.settings())
        hist['r7']=[{'time':'2026-10-16 07:00','last':1,'avg':1,'min':1,'max':100000}]
        after,_=trade.daily_model(hist,NOW,trade.settings())
        self.assertEqual(before,after)

    def test_same_bar_cannot_buy_and_sell(self):
        bars=[{'time':NOW,'price':100}]
        self.assertIsNone(trade._paper_trade(bars,candidate(),trade.settings(),daily=True))

    def test_holdout_reversal_blocks_buy_recommendation(self):
        hist=history_fixture()
        for row in hist['r15']:
            if row['time'][:10] >= '2026-10-10' and int(row['time'][11:13]) >= 13:
                row['last']=80
        result=trade.build_plan({'1':{'name':'test','grade':3,'latest':100}},{'1':hist},META,now=NOW)
        self.assertFalse(result['candidates'][0]['qualified'])
        self.assertLess(result['candidates'][0]['backtest']['net_total_per_unit'],0)

    def test_weekly_validation_uses_nonoverlapping_later_windows(self):
        rows=[]
        for ago in range(29,0,-1):
            price=100 if ago%7 < 4 else 140
            rows.append({'time':(NOW-timedelta(days=ago)).date().isoformat(),
                         'avg':price,'min':price,'max':price,'last':price})
        model,reason=trade.weekly_model({'r30':rows},NOW,trade.settings())
        self.assertIsNone(reason)
        self.assertEqual(model['backtest']['opportunities'],2)

    def test_daily_after_hours_plan_is_for_tomorrow_and_insufficient_history_is_empty(self):
        plan=trade.build_plan({'1':{'name':'test','grade':3}},{},META,now=NOW.replace(hour=22))
        self.assertTrue(plan['valid_from'].startswith('2026-10-16'))
        self.assertFalse(plan['candidates'])

    def test_fee_buffer_and_invalid_configuration(self):
        self.assertEqual(trade._levels([100],[130],trade.settings(),'daily')['break_even'],115)
        with self.assertRaises(ValueError):
            trade.settings({'region':'GLOBAL'})
        with self.assertRaises(ValueError):
            trade.settings({'fee_rate':1})


class ActionsTests(unittest.TestCase):
    def test_fresh_buy_stale_pause_sell_and_no_chase(self):
        item,plan=candidate(),plan_fixture()
        self.assertEqual(trade.action_for(item,plan,100,NOW,META)[0],'BUY_ZONE')
        self.assertEqual(trade.action_for(item,plan,100,NOW,{})[0],'STALE')
        self.assertEqual(trade.action_for(item,plan,130,NOW,META)[0],'TAKE_PROFIT')
        self.assertEqual(trade.action_for(item,plan,110,NOW,META)[0],'WAIT_PRICE')
        self.assertEqual(trade.action_for(item,plan,94,NOW,META)[0],'INVALIDATE')

    def test_afternoon_no_new_buy_and_deadline_does_not_need_fresh_price(self):
        item,plan=candidate(),plan_fixture()
        now=NOW.replace(hour=14)
        item['latest_bar_at']=now.replace(hour=13).isoformat()
        self.assertEqual(trade.action_for(item,plan,100,now,{'completed_at_utc':now.isoformat()})[0],'WAIT_SELL')
        self.assertEqual(trade.action_for(item,plan,100,NOW.replace(hour=18),{})[0],'TIME_EXIT')
        self.assertEqual(trade.action_for(item,plan,100,NOW.replace(hour=20),{})[0],'EXPIRED')

    def test_alert_dedup_is_per_plan_item_action(self):
        from cloud_trade import collect_alerts
        alerts,_=collect_alerts([(plan_fixture(),META)],{},NOW)
        self.assertEqual(len(alerts),1)
        state={alerts[0][0]:alerts[0][1]}
        self.assertEqual(collect_alerts([(plan_fixture(),META)],state,NOW)[0],[])
        item=plan_fixture(); item['id']='daily-next-day'
        self.assertEqual(len(collect_alerts([(item,META)],state,NOW)[0]),1)

    def test_freeze_prices_but_refresh_current_quote(self):
        from cloud_trade import get_plan,write_json
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            base=Path(directory); (base/'data').mkdir()
            write_json(base/'data/catalog.json',{'1':{'name':'test','grade':3,'latest':100}})
            write_json(base/'data/history_latest.json',{'1':history_fixture()})
            write_json(base/'data/market_meta.json',META)
            first,_=get_plan(base,'daily',NOW)
            write_json(base/'data/catalog.json',{'1':{'name':'test','grade':3,'latest':108}})
            second,_=get_plan(base,'daily',NOW)
            self.assertEqual(first['candidates'][0]['buy_high'],second['candidates'][0]['buy_high'])
            self.assertEqual(second['candidates'][0]['latest'],108)


class NewsTests(unittest.TestCase):
    def test_international_and_unlabelled_news_are_rejected_even_if_fresh(self):
        from cloud_report_all import render_news_section
        news={'source':{'name':'Steam'},'headlines':[{'title':'GLOBAL FALSE SIGNAL',
              'region':'GLOBAL','expires_at':(NOW+timedelta(days=1)).isoformat()}]}
        self.assertNotIn('GLOBAL FALSE SIGNAL',render_news_section(news,{},NOW))

    def test_cn_import_requires_publisher_host_region_and_date(self):
        from cn_news import parse_news_payload
        item={'title':'CN patch','region':'CN','published_at':(NOW-timedelta(days=1)).isoformat(),
              'url':'https://df.qq.com/news/fixture.html'}
        bad=dict(item,url='https://df.qq.com.evil.example/news')
        result=parse_news_payload({'region':'CN','headlines':[item,bad]},NOW)
        self.assertEqual(len(result['headlines']),1)
        with self.assertRaises(ValueError):
            parse_news_payload({'appnews':{'newsitems':[]}},NOW)

    def test_wechat_plan_preserves_price_windows_expiry_and_does_not_invent_holdings(self):
        from cloud_report_all import render_trade_plan
        from cloud_push import extract_trade_plans
        item=candidate()
        item.update(samples=15,backtest={'opportunities':5,'fills':4,'target_hits':3,'hit_rate':0.75,
                                         'net_total_per_unit':12},backtest_basis='fixture')
        plan=plan_fixture(); plan['candidates']=[item]
        texts=extract_trade_plans(render_trade_plan(plan,META,NOW))
        self.assertIn('06:00',texts[0])
        self.assertIn('2026-10-15 18:59',texts[0])
        self.assertIn('卖出目标 130',texts[0])


if __name__=='__main__':
    unittest.main(verbosity=2)
