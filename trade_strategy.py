# -*- coding: utf-8 -*-
"""Conditional CN ammo plans. Quotes and paper fills are not actual executions."""
from datetime import datetime, timedelta
import math
from statistics import median

from report_data import CHINA_TZ, collect_daily, collect_hourly, positive_price

DEFAULTS = {
    'region': 'CN', 'fee_rate': 0.13, 'sale_slippage': 0.02,
    'daily_min_net_margin': 0.03, 'weekly_min_net_margin': 0.06,
    'quote_drop_limit': 0.05, 'max_quote_age_minutes': 180,
    'morning_hours': [6, 11], 'afternoon_hours': [13, 18],
    'daily_min_train_days': 5, 'daily_test_days': 5,
    'daily_min_test_fills': 3, 'weekly_min_train_days': 14,
    'weekly_min_test_fills': 2, 'min_test_hit_rate': 0.6,
    'max_weekly_decline': 0.07, 'max_candidates': 3,
}


def quantile(values, fraction):
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def settings(config=None):
    result = dict(DEFAULTS)
    result.update(config or {})
    if result['region'] != 'CN':
        raise ValueError('This strategy is configured for CN only')
    for key in ('fee_rate', 'sale_slippage', 'quote_drop_limit'):
        if not 0 <= result[key] < 1:
            raise ValueError('Invalid ' + key)
    for key in ('morning_hours', 'afternoon_hours'):
        if len(result[key]) != 2 or not 0 <= result[key][0] <= result[key][1] <= 23:
            raise ValueError('Invalid ' + key)
    if result['morning_hours'][1] >= result['afternoon_hours'][0]:
        raise ValueError('Buy window must precede the sale window')
    return result


def _china(now):
    now = now or datetime.now(CHINA_TZ)
    if now.tzinfo is None:
        raise ValueError('now must have a timezone')
    return now.astimezone(CHINA_TZ)


def _levels(entry_samples, exit_samples, config, kind):
    net_factor = (1 - config['fee_rate']) * (1 - config['sale_slippage'])
    target = math.floor(quantile(exit_samples, 0.6))
    margin = config[kind + '_min_net_margin']
    ceiling = math.floor(min(quantile(entry_samples, 0.25), target * net_factor / (1 + margin)))
    if ceiling <= 0 or target <= ceiling:
        return None
    floor = math.ceil(ceiling * (1 - config['quote_drop_limit']))
    return {'buy_low': floor, 'buy_high': ceiling, 'sell_target': target,
            'break_even': math.ceil(ceiling / (1 - config['fee_rate'])),
            'break_even_with_slippage': math.ceil(ceiling / net_factor),
            'invalidate_below': floor, 'net_per_round': round(target * net_factor - ceiling, 2),
            'net_margin_pct': round((target * net_factor / ceiling - 1) * 100, 2),
            'exit_at_floor_net_loss_pct': round((1 - floor * net_factor / ceiling) * 100, 2)}


def _paper_trade(bars, levels, config, daily=False):
    """First observed entry; only later closes may sell. Never use bar extrema as fills."""
    entry = None
    for index, bar in enumerate(bars):
        stamp, price = bar['time'], bar['price']
        if entry is None:
            if daily and not config['morning_hours'][0] <= stamp.hour <= config['morning_hours'][1]:
                continue
            if levels['buy_low'] <= price <= levels['buy_high'] and index < len(bars) - 1:
                entry = price
            continue
        stop = price < levels['invalidate_below']
        can_sell = not daily or stamp.hour >= config['afternoon_hours'][0]
        target = can_sell and price >= levels['sell_target']
        deadline = index == len(bars) - 1
        if stop or target or deadline:
            sale = levels['sell_target'] if target else price
            net_factor = (1 - config['fee_rate']) * (1 - config['sale_slippage'])
            return {'net': sale * net_factor - entry, 'hit': target, 'entry': entry,
                    'exit': sale, 'reason': 'stop' if stop else ('target' if target else 'deadline')}
    return None


def _test_summary(trades):
    fills = [trade for trade in trades if trade is not None]
    return {'opportunities': len(trades), 'fills': len(fills),
            'target_hits': sum(trade['hit'] for trade in fills),
            'hit_rate': sum(trade['hit'] for trade in fills) / len(fills) if fills else 0,
            'net_total_per_unit': round(sum(trade['net'] for trade in fills), 2),
            'worst_net_pct': round(min((trade['net'] / trade['entry'] * 100 for trade in fills), default=0), 2)}


def _daily_sessions(hist, now, config):
    groups = {}
    for bar in collect_hourly(hist, now):
        if bar['time'].date() < now.date():
            groups.setdefault(bar['time'].date(), []).append(bar)
    sessions = []
    for day, bars in sorted(groups.items()):
        morning = [bar for bar in bars if config['morning_hours'][0] <= bar['time'].hour <= config['morning_hours'][1]]
        afternoon = [bar for bar in bars if config['afternoon_hours'][0] <= bar['time'].hour <= config['afternoon_hours'][1]]
        if len(morning) >= 3 and len(afternoon) >= 4 and afternoon[-1]['time'].hour == config['afternoon_hours'][1]:
            sessions.append({'day': day, 'entry': quantile([bar['price'] for bar in morning], 0.25),
                             'exit': median(bar['price'] for bar in afternoon),
                             'bars': [bar for bar in bars if config['morning_hours'][0] <= bar['time'].hour <= config['afternoon_hours'][1]]})
    return sessions


def daily_model(hist, now, config):
    sessions = _daily_sessions(hist, now, config)
    required = config['daily_min_train_days'] + config['daily_test_days']
    if len(sessions) < required:
        return None, '完整早盘/午后样本%d天，至少需要%d天' % (len(sessions), required)
    if sessions[-1]['day'] < now.date() - timedelta(days=2):
        return None, '小时历史已过期'
    training, validation = sessions[:-config['daily_test_days']], sessions[-config['daily_test_days']:]
    # Hold the trained prices fixed during the later validation period.
    levels = _levels([day['entry'] for day in training], [day['exit'] for day in training], config, 'daily')
    if levels is None:
        return None, '历史价差不足以覆盖费用'
    stats = _test_summary([_paper_trade(day['bars'], levels, config, daily=True) for day in validation])
    final = _levels([day['entry'] for day in sessions], [day['exit'] for day in sessions], config, 'daily')
    final.update({'samples': len(sessions), 'backtest': stats,
                  'backtest_basis': '先训练后验证；最近%d天为留出期，按小时收盘顺序模拟' % len(validation)})
    return final, None


def weekly_model(hist, now, config):
    daily = collect_daily(hist, now.date())
    bars = []
    for day, row in sorted(daily.items()):
        if row.get('hours', 24) < 18:
            continue
        if day < now.date().isoformat() and positive_price(row.get('last')):
            bars.append({'time': datetime.fromisoformat(day).replace(hour=23, tzinfo=CHINA_TZ), 'price': float(row['last'])})
    required = config['weekly_min_train_days']
    if len(bars) < required:
        return None, '完整日线%d天，至少需要%d天' % (len(bars), required)
    if bars[-1]['time'].date() < now.date() - timedelta(days=2):
        return None, '日线历史已过期'
    if any((right['time'] - left['time']).days > 1 for left, right in zip(bars[-required:], bars[-required+1:])):
        return None, '近期日线存在缺口'
    def fit(data):
        prices = [bar['price'] for bar in data]
        return _levels(prices, prices, config, 'weekly')
    trades = []
    for cut in range(required, len(bars) - 6, 7):
        trained = fit(bars[cut - required:cut])
        trades.append(_paper_trade(bars[cut:cut + 7], trained, config) if trained else None)
    final = fit(bars[-required:])
    if final is None:
        return None, '周内价差不足以覆盖费用'
    previous = median(bar['price'] for bar in bars[-14:-7])
    recent = median(bar['price'] for bar in bars[-7:])
    decline = recent / previous - 1
    final.update({'samples': len(bars), 'backtest': _test_summary(trades),
                  'trend_pct': round(decline * 100, 2),
                  'trend_blocked': decline < -config['max_weekly_decline'],
                  'backtest_basis': '每次仅用此前14天训练，随后7天验证；验证窗口不重叠，日线收盘近似成交'})
    return final, None


def build_plan(catalog, history, market_meta, kind='daily', now=None, config=None):
    if kind not in ('daily', 'weekly'):
        raise ValueError('kind must be daily or weekly')
    now, config = _china(now), settings(config)
    day = now.date()
    if kind == 'daily':
        if now.hour > config['afternoon_hours'][1]:
            day += timedelta(days=1)
        start = datetime.combine(day, datetime.min.time(), CHINA_TZ).replace(hour=config['morning_hours'][0])
        end = start.replace(hour=config['afternoon_hours'][1], minute=59, second=59)
    else:
        day -= timedelta(days=day.weekday())
        if now.weekday() == 6 and now.hour > config['afternoon_hours'][1]:
            day += timedelta(days=7)
        start = datetime.combine(day, datetime.min.time(), CHINA_TZ).replace(hour=6)
        end = (start + timedelta(days=6)).replace(hour=18, minute=59, second=59)
    plan = {'schema_version': 1, 'region': 'CN', 'kind': kind,
            'id': kind + '-' + start.date().isoformat(), 'generated_at': now.isoformat(),
            'valid_from': start.isoformat(), 'valid_until': end.isoformat(),
            'fee_rate': config['fee_rate'], 'sale_slippage': config['sale_slippage'],
            'quote_collected_at': (market_meta or {}).get('completed_at_utc'),
            'candidates': [], 'excluded': [], 'config': config,
            'risk': 'moligod为第三方行情，国服挂单价格须在游戏内核对；回测不含成交量、排队、保证金及额外费用，不能保证成交或盈利。'}
    model_fn = daily_model if kind == 'daily' else weekly_model
    for iid, item in catalog.items():
        if str(item.get('grade')) not in ('3', '4'):
            continue
        model, reason = model_fn(history.get(str(iid)) or {}, now, config)
        if reason:
            plan['excluded'].append({'name': item.get('name', str(iid)), 'reason': reason})
            continue
        latest = positive_price(item.get('latest'))
        hourly = collect_hourly(history.get(str(iid)) or {}, now)
        latest_bar = hourly[-1]['time'] if hourly else None
        stats = model['backtest']
        enough = stats['fills'] >= config[kind + '_min_test_fills']
        validated = enough and stats['hit_rate'] >= config['min_test_hit_rate'] and stats['net_total_per_unit'] > 0
        model.update({'item_id': str(iid), 'name': item.get('name', str(iid)), 'grade': str(item.get('grade')),
                      'latest': latest, 'latest_bar_at': latest_bar.isoformat() if latest_bar else None,
                      'qualified': validated and not model.get('trend_blocked'),
                      'qualification': '通过历史筛选' if validated and not model.get('trend_blocked') else
                        ('近期持续下跌，暂停买入' if model.get('trend_blocked') else '回测样本或表现不足，仅观察')})
        plan['candidates'].append(model)
    plan['candidates'].sort(key=lambda row: (not row['qualified'], -row['backtest']['hit_rate'], -row['net_margin_pct']))
    plan['candidates'] = plan['candidates'][:config['max_candidates']]
    return plan


def action_for(candidate, plan, latest, now=None, market_meta=None):
    now = _china(now)
    config = settings(plan.get('config'))
    if plan.get('region') != 'CN':
        return 'REGION_BLOCKED', '区服不符，停止建议'
    start, end = datetime.fromisoformat(plan['valid_from']), datetime.fromisoformat(plan['valid_until'])
    if now > end:
        return 'EXPIRED', '计划已到期；有仓复核清仓，未成交取消'
    if plan['kind'] == 'daily' and now.date() == end.date() and now.hour == end.hour:
        return 'TIME_EXIT', '已到日抛清仓时段；核对实盘后退出，不延长持有'
    if plan['kind'] == 'weekly' and now.date() == end.date() and now.hour == end.hour:
        return 'TIME_EXIT', '已到周抛清仓时段；核对实盘后退出，不延长持有'
    try:
        collected = datetime.fromisoformat((market_meta or {}).get('completed_at_utc', '').replace('Z', '+00:00'))
        bar_time = datetime.fromisoformat(candidate.get('latest_bar_at') or '')
        fresh = all(timedelta(minutes=-5) <= now - stamp <= timedelta(minutes=config['max_quote_age_minutes']) for stamp in (collected, bar_time))
    except (ValueError, TypeError):
        fresh = False
    if not fresh or positive_price(latest) is None:
        return 'STALE', '行情过期或时间缺失，等待刷新'
    if now < start:
        return 'WAIT_TIME', '计划尚未开始，届时重新核价'
    if latest >= candidate['sell_target']:
        return 'TAKE_PROFIT', '已到目标；如有仓核对成本后卖出，空仓不追'
    if latest < candidate['invalidate_below']:
        return 'INVALIDATE', '跌破失效线；取消买单，有仓复核退出'
    if not candidate['qualified']:
        return 'WATCH', candidate['qualification']
    if plan['kind'] == 'daily' and not config['morning_hours'][0] <= now.hour <= config['morning_hours'][1]:
        return 'WAIT_SELL', '已过早盘买入时段；有仓等待目标或到期退出'
    if latest <= candidate['buy_high']:
        return 'BUY_ZONE', '进入买入区；先核对国服挂单和成交费用，再考虑限价买入'
    return 'WAIT_PRICE', '等待回落至买入区，超过上限不追'
