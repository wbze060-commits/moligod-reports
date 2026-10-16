# -*- coding: utf-8 -*-
"""Short, shared report brief for the HTML page and ServerChan message."""
from datetime import datetime
from html import escape
import json

from report_data import CHINA_TZ
from trade_strategy import action_for

MAX_CARDS = 2
STATE_TEXT = {
    'BUY_ZONE': '进入买入区，先核实挂单',
    'TAKE_PROFIT': '到达目标，仅持仓者复核卖出',
    'INVALIDATE': '跌破失效线，取消买单',
    'WAIT_PRICE': '等回落，不追价',
    'WAIT_SELL': '买入时段已过，不再新买',
    'WAIT_TIME': '计划未开始，到时重新核价',
    'STALE': '行情过期，暂停操作',
    'EXPIRED': '计划已到期，未成交单取消',
    'TIME_EXIT': '到退出时段，有仓复核',
}


def china_datetime(value):
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        return None
    return stamp.astimezone(CHINA_TZ)


def brief_for_plan(plan, market_meta, now):
    kind = plan.get('kind')
    if kind not in ('daily', 'weekly') or plan.get('region') != 'CN':
        raise ValueError('A CN daily or weekly plan is required')
    now = now.astimezone(CHINA_TZ)
    start, end = china_datetime(plan.get('valid_from')), china_datetime(plan.get('valid_until'))
    if start is None or end is None:
        raise ValueError('Plan validity timestamps are required')
    quote_time = china_datetime((market_meta or {}).get('completed_at_utc'))
    mode = '日抛' if kind == 'daily' else '周抛'
    ahead = start.date() > now.date()
    empty_title = ('明日先观望' if kind == 'daily' else '本周先观望') if ahead or kind == 'weekly' else '今天先观望'
    records = []
    for item in plan.get('candidates', []):
        # Unqualified candidates stay out of the recommendation surface.
        if not item.get('qualified'):
            continue
        action, detail = action_for(item, plan, item.get('latest'), now, market_meta)
        records.append({
            'name': str(item.get('name') or '未知子弹'),
            'state': action,
            'state_text': STATE_TEXT.get(action, '等待下一次行情'),
            'detail': str(detail),
            'latest': item.get('latest'),
            'buy_low': int(item.get('buy_low') or 0),
            'buy_high': int(item.get('buy_high') or 0),
            'sell_target': int(item.get('sell_target') or 0),
            'invalidate_below': int(item.get('invalidate_below') or 0),
            'qualified': True,
        })
    records.sort(key=lambda item: (
        {'BUY_ZONE': 0, 'TAKE_PROFIT': 1, 'WAIT_PRICE': 2, 'WAIT_SELL': 3,
         'WAIT_TIME': 4, 'STALE': 5, 'INVALIDATE': 6, 'TIME_EXIT': 7, 'EXPIRED': 8}.get(item['state'], 9),
        -item['buy_high'], item['name']))
    cards = records[:MAX_CARDS]
    open_signals = [item for item in cards if item['state'] in ('BUY_ZONE', 'TAKE_PROFIT')]
    if any(item['state'] == 'STALE' for item in cards) and not open_signals:
        title = '行情待更新'
        sentence = '报价过期，先不买卖；等新行情再看。'
    elif not cards:
        title = empty_title
        sentence = '没有通过筛选的买入标的，暂不建议开仓。'
    elif open_signals:
        title = '%d 项到操作价' % len(open_signals)
        sentence = '只按下列价位核对；超过买入上限不追。'
    elif ahead:
        title = '明日关注%d款' % len(cards)
        sentence = '这些候选已通过筛选，但现在还不是买入时段；到时重新核价。'
    else:
        title = ('明日先观察' if ahead else '今天先观察') if kind == 'daily' else '本周先观察'
        if cards and all(item['state'] == 'WAIT_TIME' for item in cards):
            title = ('明日关注%d款' % len(cards)) if ahead else '等待计划开始'
            sentence = '当前还未到操作时段，开市后重新核价。'
        elif cards and all(item['state'] == 'WAIT_PRICE' for item in cards):
            title = '等待回落再买' if kind == 'daily' else '等待周内入场价'
            sentence = '目前都高于买入上限，先不追价。'
        elif cards and all(item['state'] == 'WAIT_SELL' for item in cards):
            title = '今日不再新买'
            sentence = '早盘买入窗口已结束；有仓才看午后目标。'
        else:
            title = '今天先观察' if kind == 'daily' else '本周先观察'
            sentence = '目前未到操作价，等价格触发再看。'
    return {
        'schema': 1,
        'region': 'CN',
        'kind': kind,
        'mode': mode,
        'plan_id': str(plan.get('id') or ''),
        'plan_date': start.strftime('%m-%d'),
        'title': title,
        'sentence': sentence,
        'window': '06–11买，13–19卖' if kind == 'daily' else '本周观察，周日18点复核退出',
        'valid_until': end.strftime('%m-%d %H:%M'),
        'quote_at': quote_time.strftime('%m-%d %H:%M') if quote_time else '时间未记录',
        'quote_at_iso': quote_time.isoformat() if quote_time else '',
        'cards': cards,
        'more_count': max(0, len(records) - len(cards)),
        'warnings': ['先核对国服挂单；未录入实际持仓成本，卖出按你的成本复核。'],
    }


def render_brief_cards(brief):
    parts = []
    for item in brief['cards']:
        latest = '未知' if item['latest'] is None else str(item['latest'])
        parts.append(
            '<article class="brief-card"><div class="brief-card-head"><h3>%s</h3><span class="signal-state">%s</span></div>'
            '<p class="brief-prices">现价 %s <span>买 %d–%d</span> <span>卖 ≥%d</span></p>'
            '<p class="brief-invalidation">失效线：跌破 %d；%s</p></article>' % (
                escape(item['name']), escape(item['state_text']), escape(latest),
                item['buy_low'], item['buy_high'], item['sell_target'],
                item['invalidate_below'], escape(item['detail']))
        )
    if not parts:
        parts.append('<p class="brief-empty">%s</p>' % escape(brief['sentence']))
    if brief['more_count']:
        parts.append('<p class="brief-more">另有 %d 项；在完整行情明细里查看。</p>' % brief['more_count'])
    return ''.join(parts)


def render_brief_section(brief):
    cards = render_brief_cards(brief)
    warning = ' '.join(brief['warnings'])
    payload = json.dumps(brief, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return (
        '<section class="daily-brief" aria-labelledby="brief-title">'
        '<div class="brief-heading"><div><p class="eyebrow">国服 · %s计划 · 北京时间</p>'
        '<h2 id="brief-title">%s</h2><p class="brief-sentence">%s</p></div>'
        '<span class="quote-time">数据更新 <time>%s</time></span></div>'
        '<div class="brief-cards">%s</div>'
        '<p class="brief-window">%s · 有效至 %s</p>'
        '<p class="brief-risk">%s</p></section>'
        '<script type="application/json" id="report-brief-data">%s</script>' % (
            escape(brief['mode']), escape(brief['title']), escape(brief['sentence']),
            escape(brief['quote_at']), cards,
            escape(brief['window']), escape(brief['valid_until']), escape(warning), payload)
    )


def push_summary(brief, report_date, pages, report_type='daily'):
    prefix = {'daily': '日报', 'weekly': '周报'}.get(report_type)
    if prefix is None:
        raise ValueError('Only daily and weekly briefs are supported')
    report_name = prefix + '_' + report_date
    lines = ['**国服%s · %s**' % (brief['mode'], report_date), '',
             '**%s**' % brief['title'], brief['sentence'], '']
    for item in brief['cards']:
        latest = '未知' if item['latest'] is None else str(item['latest'])
        lines.extend(['- **%s**｜%s' % (item['name'], item['state_text']),
                      '  现价%s · 买%d–%d · 卖≥%d · 失效<%d' % (
                          latest, item['buy_low'], item['buy_high'],
                          item['sell_target'], item['invalidate_below'])])
    lines.extend(['', '%s · 有效至%s' % (brief['window'], brief['valid_until']),
                  '先核对国服挂单；卖出按实际成本复核。',
                  '[打开精简报告 HTML](%s%s.html)' % (pages, report_name),
                  '[PDF 版](%s%s.pdf)' % (pages, report_name)])
    if len(brief['cards']) > MAX_CARDS:
        raise ValueError('Brief exceeds its visible card budget')
    return '\n'.join(lines)
