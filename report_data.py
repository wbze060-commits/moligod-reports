# -*- coding: utf-8 -*-
"""Freshness and rolling-window helpers for the market report."""
from datetime import date, datetime, timedelta, timezone
import math

CHINA_TZ = timezone(timedelta(hours=8))
RECENT_DAYS = 7
BASELINE_DAYS = 23


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def parse_history_date(value, as_of):
    """Parse ISO dates or MM-DD points, including year rollover."""
    reference = _as_date(as_of) or date.today()
    if value is None:
        return None
    if isinstance(value, (int, float)):
        timestamp = value / 1000 if value > 10_000_000_000 else value
        try:
            return datetime.fromtimestamp(timestamp, CHINA_TZ).date()
        except (ValueError, OSError, OverflowError):
            return None
    text = str(value).strip()
    if len(text) >= 10:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            pass
    if len(text) >= 5 and text[2] == "-":
        try:
            month, day = int(text[:2]), int(text[3:5])
            candidate = date(reference.year, month, day)
            if candidate > reference + timedelta(days=1):
                candidate = date(reference.year - 1, month, day)
            return candidate
        except ValueError:
            return None
    return None


def positive_price(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def parse_history_time(value, as_of=None):
    """moligod MM-DD HH:MM labels use the China clock; epochs retain their zone."""
    reference = _as_date(as_of) or datetime.now(CHINA_TZ).date()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value, CHINA_TZ)
        except (ValueError, OSError, OverflowError):
            return None
    text = str(value or '').strip()
    try:
        if len(text) >= 16 and text[4] == '-':
            parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
            return (parsed.replace(tzinfo=CHINA_TZ) if parsed.tzinfo is None else parsed).astimezone(CHINA_TZ)
        if len(text) == 11 and text[2] == '-' and text[5] == ' ':
            day = parse_history_date(text[:5], reference)
            if day:
                clock = datetime.strptime(text[6:], '%H:%M').time()
                return datetime.combine(day, clock, CHINA_TZ)
    except ValueError:
        pass
    return None


def collect_hourly(history, as_of=None):
    reference = as_of or datetime.now(CHINA_TZ)
    if isinstance(reference, date) and not isinstance(reference, datetime):
        reference = datetime.combine(reference, datetime.max.time(), CHINA_TZ)
    reference = reference.replace(tzinfo=CHINA_TZ) if reference.tzinfo is None else reference.astimezone(CHINA_TZ)
    points = {}
    # r7 is more recent. Do not count the same hour again from r15.
    for key in ('r7', 'r15'):
        for row in history.get(key, []) or []:
            stamp = parse_history_time(row.get('time'), reference)
            price = positive_price(row.get('last'))
            if stamp is None or price is None or stamp > reference or stamp < reference - timedelta(days=30):
                continue
            points.setdefault(stamp, {'time': stamp, 'price': price, 'low': positive_price(row.get('min')),
                                      'high': positive_price(row.get('max')), 'avg': positive_price(row.get('avg'))})
    return [points[key] for key in sorted(points)]


def collect_daily(history, as_of=None):
    """Prefer daily r30, aggregate hourly fallback without losing overlapping bars."""
    reference = _as_date(as_of) or date.today()
    days = {}
    grouped = {}
    for point in collect_hourly(history, as_of=reference):
        grouped.setdefault(point['time'].date().isoformat(), []).append(point)
    for key, points in grouped.items():
        averages = [point['avg'] or point['price'] for point in points]
        days[key] = {'low': min(point['low'] or point['price'] for point in points),
                     'high': max(point['high'] or point['price'] for point in points),
                     'avg': sum(averages) / len(averages), 'avg_n': len(points),
                     'last': points[-1]['price'], 'hours': len(points)}
    for row in history.get('r30', []) or []:
        day = parse_history_date(row.get("time"), reference)
        if day is None or day > reference or day < reference - timedelta(days=29):
            continue
        key = day.isoformat()
        avg = positive_price(row.get("avg"))
        days[key] = {
            "low": row.get("min"),
            "high": row.get("max"),
            "avg": avg,
            "avg_n": 1 if avg is not None else 0,
            "last": row.get("last"),
        }
        if 'hours' in row:
            days[key]['hours'] = row['hours']
    return days


def _period_stats(days, start, end):
    rows = [row for key, row in days.items() if start <= key <= end]
    lows = [row["low"] for row in rows if row.get("low") is not None]
    highs = [row["high"] for row in rows if row.get("high") is not None]
    averages = [row["avg"] for row in rows if row.get("avg") is not None]
    return {
        "start": start,
        "end": end,
        "low": min(lows) if lows else None,
        "high": max(highs) if highs else None,
        "avg": round(sum(averages) / len(averages)) if averages else None,
        "samples": len(averages),
    }


def rolling_stats(days, as_of=None, recent_days=RECENT_DAYS, baseline_days=BASELINE_DAYS):
    reference = _as_date(as_of) or date.today()
    recent_start = reference - timedelta(days=recent_days - 1)
    baseline_end = recent_start - timedelta(days=1)
    baseline_start = baseline_end - timedelta(days=baseline_days - 1)
    return {
        "recent": _period_stats(days, recent_start.isoformat(), reference.isoformat()),
        "baseline": _period_stats(days, baseline_start.isoformat(), baseline_end.isoformat()),
        "recent_days": recent_days,
        "baseline_days": baseline_days,
    }


def _parse_iso(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def filter_fresh_news(news, now=None, region=None):
    """Drop legacy, malformed, or expired headlines and editorial outlook."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    result = dict(news or {})
    for key in ("headlines", "outlook"):
        active = []
        for item in result.get(key, []) or []:
            if region and item.get('region') != region:
                continue
            expires = _parse_iso(item.get("expires_at"))
            if expires is not None and expires > current:
                active.append(item)
        result[key] = active
    return result


def format_market_meta(meta):
    meta = meta or {}
    completed = _parse_iso(meta.get("completed_at_utc"))
    if completed is None:
        timestamp = "未记录"
    else:
        timestamp = completed.astimezone(CHINA_TZ).strftime("%Y-%m-%d %H:%M")
    source = str(meta.get("source") or "未知")
    counts = []
    if isinstance(meta.get("catalog_count"), int):
        counts.append("实时价%d款" % meta["catalog_count"])
    if isinstance(meta.get("history_count"), int):
        counts.append("K线%d款" % meta["history_count"])
    coverage = "；覆盖" + "、".join(counts) if counts else ""
    return (
        "行情采集时间（北京时间）：%s；来源：%s%s；窗口：近%d天 vs 前%d天"
        % (timestamp, source, coverage, RECENT_DAYS, BASELINE_DAYS)
    )
