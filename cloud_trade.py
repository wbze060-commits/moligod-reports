# -*- coding: utf-8 -*-
"""Freeze plans until expiry and send deduplicated conditional CN price alerts."""
from datetime import datetime
import json
import os
from pathlib import Path

from report_data import CHINA_TZ, collect_hourly
from trade_strategy import action_for, build_plan

BASE = Path(__file__).resolve().parent


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def write_json(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    os.replace(temp, path)


def get_plan(base, kind, now=None):
    base, now = Path(base), now or datetime.now(CHINA_TZ)
    config = read_json(base / 'data/trade_config.json', {'region': 'CN'})
    catalog = read_json(base / 'data/catalog.json', {})
    history = read_json(base / 'data/history_latest.json', {})
    meta = read_json(base / 'data/market_meta.json', {})
    path = base / ('data/trade_plan_%s.json' % kind)
    plan = read_json(path, {})
    try:
        active = plan.get('region') == 'CN' and plan.get('kind') == kind and datetime.fromisoformat(plan['valid_until']) >= now
        active = active and plan.get('source_config') == config
    except (KeyError, ValueError, TypeError):
        active = False
    if not active:
        if plan.get('region') == 'CN' and plan.get('kind') == kind:
            write_json(base / ('data/trade_expired_%s.json' % kind), plan)
        plan = build_plan(catalog, history, meta, kind=kind, now=now, config=config)
        plan['source_config'] = config
        write_json(path, plan)
    # Refresh quotes, never silently move a frozen plan's entry or exit price.
    for item in plan.get('candidates', []):
        current = catalog.get(item['item_id']) or {}
        item['latest'] = current.get('latest')
        bars = collect_hourly(history.get(item['item_id']) or {}, now)
        item['latest_bar_at'] = bars[-1]['time'].isoformat() if bars else None
    return plan, meta


def alert_text(item, plan, action, message, now):
    label = '日抛' if plan['kind'] == 'daily' else '周抛'
    quote_label = '计划报价（可能已过期）' if action in ('TIME_EXIT', 'EXPIRED') else '现价（须实盘核对）'
    return ('%s｜%s\n北京时间：%s\n%s\n%s：%s；计划买入：%d–%d；目标卖价：%d\n'
            '保本卖价（13%%费率口径）：%d；含滑点缓冲：%d\n'
            '跌破%d取消计划；有效至%s\n税后含2%%滑点估算空间：%.2f/发（%.2f%%）\n'
            '未记录你的实际持仓和成本；只有持有且扣费后达到个人目标时才卖。\n%s') % (
                label, item['name'], now.strftime('%Y-%m-%d %H:%M'), message,
                quote_label, item['latest'], item['buy_low'], item['buy_high'], item['sell_target'],
                item['break_even'], item['break_even_with_slippage'], item['invalidate_below'],
                plan['valid_until'], item['net_per_round'], item['net_margin_pct'], plan['risk'])


def collect_alerts(plans, state, now):
    alerts, updated = [], dict(state)
    for plan, meta in plans:
        for item in plan['candidates']:
            if not item['qualified']:
                continue
            action, message = action_for(item, plan, item['latest'], now, meta)
            key = plan['id'] + ':' + item['item_id']
            event_key = key + ':' + action
            if action in ('BUY_ZONE', 'TAKE_PROFIT', 'INVALIDATE', 'EXPIRED', 'TIME_EXIT') and not updated.get(event_key):
                alerts.append((event_key, action, item, plan, message))
    return alerts, updated


def main():
    now = datetime.now(CHINA_TZ)
    plans = [get_plan(BASE, kind, now) for kind in ('daily', 'weekly')]
    for kind in ('daily', 'weekly'):
        expired = read_json(BASE / ('data/trade_expired_%s.json' % kind), {})
        if expired.get('region') == 'CN':
            plans.insert(0, (expired, {}))
    state_path = BASE / 'data/trade_alert_state.json'
    state = read_json(state_path, {})
    alerts, state = collect_alerts(plans, state, now)
    key = os.environ.get('SCT_KEY', '').strip()
    if alerts and not key:
        print('TRADE_NO_SCT_KEY pending=%d' % len(alerts))
        return 1
    from cloud_push import push
    sent = 0
    for identity, action, item, plan, message in alerts[:3]:
        try:
            response = push(key, '国服子弹%s：%s' % ('日抛' if plan['kind'] == 'daily' else '周抛', item['name']),
                            alert_text(item, plan, action, message, now))
            if response.get('code') != 0:
                print('TRADE_PUSH_FAILED code=%s' % response.get('code'))
                continue
            state[identity] = action
            # Only acknowledge successful delivery; a failed push can retry next run.
            write_json(state_path, state)
            sent += 1
        except Exception as exc:
            print('TRADE_PUSH_FAILED', type(exc).__name__)
    print('TRADE_ALERTS pending=%d sent=%d' % (len(alerts), sent))
    return 0 if not alerts or sent == min(3, len(alerts)) else 1


if __name__ == '__main__':
    raise SystemExit(main())
