# -*- coding: utf-8 -*-
"""cloud_report_all.py — 全子弹版报告（68 款：26 三级 + 26 四级 + 16 五级）
在 cloud_report.py 基础上扩展：5 级弹仅实时行情（无 30 天 K 线，只进行情表/榜单/独立板块）。
口径：低价期=8/25-9/2；日常期=8/2-8/24；出售到手=挂价*0.87；SPIKE 不特殊处理。
用法: python cloud_report_all.py [daily|weekly|monthly] [output.html]
"""
import json, os, sys, datetime
import html as html_lib
from report_data import (CHINA_TZ, BASELINE_DAYS, RECENT_DAYS, collect_daily, filter_fresh_news, format_market_meta, parse_history_date, rolling_stats)

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')

TAX = 0.87

WEEKDAYS = ['周一','周二','周三','周四','周五','周六','周日']

def load_json(name):
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return None
    with open(p, encoding='utf-8') as f:
        return json.load(f)



def pct_str(v):
    return ('+%.1f%%' % v) if v and v >= 0 else ('%.1f%%' % (v or 0))

def cls(v):
    if v is None: return 'gray'
    return 'pos' if v > 0 else ('neg' if v < 0 else 'gray')


def build_rows_all(history, catalog, as_of=None):
    """All bullet rows with a rolling recent-vs-baseline comparison."""
    as_of = as_of or datetime.datetime.now(CHINA_TZ).date()
    rows = []
    for iid, cat in catalog.items():
        hist = history.get(iid) or {}
        grade = str(cat.get("grade"))
        latest = cat.get("latest")
        today_high, today_low = cat.get("today_high"), cat.get("today_low")
        yesterday_high, yesterday_low = cat.get("yesterday_high"), cat.get("yesterday_low")
        previous = ((yesterday_high or 0) + (yesterday_low or 0)) / 2.0 if (yesterday_high and yesterday_low) else None
        change = ((latest - previous) / previous * 100) if (latest is not None and previous) else None
        amplitude = ((today_high - today_low) / today_low * 100) if (today_high and today_low) else None
        row = {
            "name": cat.get("name") or str(iid), "grade": grade, "latest": latest,
            "th": today_high, "tl": today_low, "prev": previous,
            "chg": change, "amp": amplitude,
            "seven_high": cat.get("seven_high"), "seven_low": cat.get("seven_low"),
            "recent_avg": None, "baseline_avg": None, "recent_low": None, "recent_high": None,
            "baseline_low": None, "baseline_high": None, "recent_samples": 0, "baseline_samples": 0,
            "tax_net": None, "profit": None, "margin": None, "cur_space": None, "cur_margin": None,
        }
        if hist:
            days = collect_daily(hist, as_of=as_of)
            windows = rolling_stats(days, as_of=as_of)
            recent, baseline = windows["recent"], windows["baseline"]
            row.update({
                "recent_avg": recent["avg"], "baseline_avg": baseline["avg"],
                "recent_low": recent["low"], "recent_high": recent["high"],
                "baseline_low": baseline["low"], "baseline_high": baseline["high"],
                "recent_samples": recent["samples"], "baseline_samples": baseline["samples"],
            })
            enough_data = recent["samples"] >= 4 and baseline["samples"] >= 10
            if enough_data and baseline["avg"] is not None:
                tax_net = baseline["avg"] * TAX
                row["tax_net"] = round(tax_net)
                if recent["avg"] is not None and recent["avg"] > 0:
                    profit = tax_net - recent["avg"]
                    row["profit"] = round(profit)
                    row["margin"] = round(profit / recent["avg"] * 100, 1)
                if latest is not None:
                    space = tax_net - latest
                    row["cur_space"] = round(space)
                    row["cur_margin"] = round(space / latest * 100, 1) if latest > 0 else None
        rows.append(row)
    return rows


def _e(value):
    return html_lib.escape(str(value if value is not None else "-"))


def _pct(value):
    return pct_str(value) if value is not None else "--"


def _beijing_time(value):
    if not value:
        return "未记录"
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return parsed.astimezone(CHINA_TZ).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return "时间格式无效"


def render_overview(rows, today, market_meta=None):
    with_change = [row for row in rows if row["chg"] is not None]
    indices = {}
    for grade in ("3", "4", "5"):
        group = [row for row in with_change if str(row["grade"]) == grade]
        indices[grade] = sum(row["chg"] for row in group) / len(group) if group else None
    tags = []
    for grade, label in (("3", "3级"), ("4", "4级"), ("5", "5级")):
        tags.append('<span class="tag">%s指数 %s</span>' % (label, _pct(indices[grade])))
    tags.append('<span class="tag">覆盖 %d 种子弹（%d 三级 / %d 四级 / %d 五级）</span>' % (
        len(rows),
        sum(1 for row in rows if row["grade"] == "3"),
        sum(1 for row in rows if row["grade"] == "4"),
        sum(1 for row in rows if row["grade"] == "5"),
    ))
    return (
        '<div class="card"><b>📊 市场概览</b><br>%s</div>'
        '<div class="sub">%s</div>'
        % (" ".join(tags), _e(format_market_meta(market_meta)))
    )


def render_rolling_comparison(rows):
    valid = [row for row in rows if row["recent_avg"] is not None and row["baseline_avg"] is not None]
    valid.sort(key=lambda row: -(row["margin"] if row["margin"] is not None else -999))
    body = []
    for row in valid:
        body.append(
            '<tr><td>%s</td><td>%s</td><td>%s (%d天)</td><td>%s (%d天)</td>'
            '<td>%s</td><td class="%s">%s</td><td class="%s">%s</td></tr>'
            % (
                _e(row["name"]), _e(row["grade"]),
                _e(row["recent_avg"]), row["recent_samples"],
                _e(row["baseline_avg"]), row["baseline_samples"],
                _e(row["tax_net"]),
                cls(row["cur_space"]), _e(row["cur_space"]),
                cls(row["margin"]), _e(row["profit"]),
            )
        )
    if not body:
        body.append('<tr><td colspan="7">有效历史样本不足，暂不计算滚动比较。</td></tr>')
    return (
        '<h2>滚动行情比较：近7天 vs 前23天</h2>'
        '<div class="sub">前23天均价×0.87估算税后基准；正空间表示当前价低于该历史基准，'
        '是历史比较值，不是收益保证。5级弹仅展示实时行情。</div>'
        '<table><tr><th>子弹</th><th>等级</th><th>近7天均价</th><th>前23天均价</th>'
        '<th>税后基准价</th><th>当前空间/发</th><th>近7天均价买入的估算空间/发</th></tr>%s</table>'
        % "".join(body)
    )


def render_current_buys(rows):
    candidates = [
        row for row in rows
        if row["grade"] == "3" and row["cur_space"] is not None and row["cur_space"] > 0
    ]
    candidates.sort(key=lambda row: -(row["cur_margin"] or 0))
    if not candidates:
        return '<h2>当前可入手清单（3级弹）</h2><div class="card">当前没有低于滚动税后基准的三级弹。</div>'
    rows_html = "".join(
        '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td class="pos">%.1f%%</td></tr>'
        % (_e(row["name"]), _e(row["latest"]), _e(row["tax_net"]), _e(row["cur_space"]), row["cur_margin"])
        for row in candidates
    )
    return (
        '<h2>当前可入手清单（3级弹）</h2>'
        '<div class="sub">筛选条件：当前价低于前23天均价的税后值（×0.87）。</div>'
        '<table><tr><th>子弹</th><th>当前价</th><th>税后基准价</th><th>空间/发</th><th>空间率</th></tr>%s</table>'
        % rows_html
    )


def render_news_section(news, status, now=None):
    filtered = filter_fresh_news(news, now=now)
    source = filtered.get("source") or {}
    scope = _e(source.get("scope") or "公告源范围未标注")
    status = status or {}
    last_success = _beijing_time(status.get("last_success_at") or filtered.get("updated"))
    status_line = "公告源：%s；上次成功刷新（北京时间）：%s" % (_e(source.get("name") or "未配置"), last_success)
    warning = ""
    if status.get("status") == "error":
        warning = '<div class="warn">本次公告刷新失败；只显示仍在有效期内的上次成功公告。%s</div>' % _e(status.get("error"))
    elif not filtered.get("headlines"):
        warning = '<div class="warn">近30天没有仍在有效期内的行情相关官方公告。</div>'

    items = []
    for item in filtered.get("headlines", []):
        title = _e(item.get("title"))
        summary = _e(item.get("summary"))
        published = _beijing_time(item.get("published_at"))
        item_source = _e(item.get("source") or source.get("name"))
        url = str(item.get("url") or "")
        safe_url = html_lib.escape(url, quote=True) if url.startswith("https://") else ""
        link = '<a href="%s" target="_blank" rel="noopener">查看来源</a>' % safe_url if safe_url else ""
        items.append(
            '<article class="news-item"><b>%s</b><div class="sub">%s｜发布：%s｜标签：%s</div>'
            '<p>%s</p>%s</article>'
            % (title, item_source, published, _e("、".join(item.get("tags", []))), summary, link)
        )
    if not items:
        items.append('<p>暂无当前有效的官方公告。</p>')

    outlook_items = filtered.get("outlook", [])
    outlook_html = "".join(
        '<li>%s：%s — %s</li>' % (
            _e(item.get("line")), _e(item.get("text")), _e(item.get("basis") or "人工研判")
        )
        for item in outlook_items
    )
    if not outlook_html:
        outlook_html = "<li>暂无仍在有效期内的人工价格研判；官方公告不自动推断价格方向。</li>"
    risk = _e(filtered.get("risk") or "请结合当前行情和个人风险判断。")
    return (
        '<h2>官方公告与有效观点</h2><div class="sub">%s｜范围：%s</div>%s'
        '<div class="card">%s</div>'
        '<h3>有效期内的人工研判</h3><ul>%s</ul>'
        '<div class="warn"><b>风险提示：</b>%s</div>'
        % (status_line, scope, warning, "".join(items), outlook_html, risk)
    )


def render_daily(rows, today):
    with_change = [row for row in rows if row["chg"] is not None]

    def board(values):
        return "".join(
            '<tr><td>%s</td><td>%s</td><td class="%s">%s</td><td>%s</td></tr>'
            % (_e(row["name"]), _e(row["grade"]), cls(row["chg"]), _pct(row["chg"]), _e(row["latest"]))
            for row in values
        )

    ordered = sorted(with_change, key=lambda row: row["chg"] or 0, reverse=True)
    market_rows = "".join(
        '<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
        '<td class="%s">%s</td></tr>'
        % (
            _e(row["name"]), _e(row["grade"]), _e(row["latest"]),
            _e(row["th"]), _e(row["tl"]), _e(round(row["prev"]) if row["prev"] else None),
            cls(row["chg"]), _pct(row["chg"]),
        )
        for row in ordered
    )
    amplitudes = sorted((row for row in rows if row["amp"] is not None), key=lambda row: row["amp"], reverse=True)[:5]
    amplitude_rows = "".join(
        '<tr><td>%s</td><td>%s</td><td>%s</td><td>%.1f%%</td></tr>'
        % (_e(row["name"]), _e(row["grade"]), _pct(row["chg"]), row["amp"])
        for row in amplitudes
    )
    return (
        '<h2>今日行情表（按涨跌幅）</h2>'
        '<table><tr><th>子弹</th><th>等级</th><th>最新价</th><th>今高</th><th>今低</th>'
        '<th>昨收(近似)</th><th>涨跌幅</th></tr>%s</table>'
        '<h2>涨幅榜 TOP5</h2><table><tr><th>子弹</th><th>等级</th><th>涨跌幅</th><th>最新价</th></tr>%s</table>'
        '<h2>跌幅榜 TOP5</h2><table><tr><th>子弹</th><th>等级</th><th>跌幅</th><th>最新价</th></tr>%s</table>'
        '<h2>振幅 TOP5</h2><table><tr><th>子弹</th><th>等级</th><th>涨跌幅</th><th>振幅</th></tr>%s</table>'
        % (market_rows, board(ordered[:5]), board(list(reversed(ordered[-5:]))), amplitude_rows)
    )


def render_weekly_monthly(rows, rtype, today):
    title = {"weekly": "行情周报", "monthly": "行情月报"}.get(rtype, "行情报告")
    return '<h2>%s：市场概览</h2>' % _e(title)

def main():
    rtype = sys.argv[1] if len(sys.argv) > 1 else 'daily'
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(BASE, 'reports', 'report_all_%s.html' % rtype)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    catalog = load_json('catalog.json') or {}
    history = load_json('history_latest.json') or {}
    market_meta = load_json('market_meta.json') or {}
    news = load_json('news.json') or {}
    news_status = load_json('news_refresh_status.json') or {}
    now = datetime.datetime.now(datetime.timezone.utc)
    if not catalog:
        print('ERROR: no data/catalog.json'); sys.exit(1)

    today_date = now.astimezone(CHINA_TZ).date()
    rows = build_rows_all(history, catalog, as_of=today_date)
    today = today_date.isoformat()
    wd = WEEKDAYS[today_date.weekday()]
    title_map = {'daily': '行情日报', 'weekly': '行情周报', 'monthly': '行情月报'}
    t = title_map.get(rtype, '行情报告')

    body = render_overview(rows, today, market_meta)
    if rtype == 'daily':
        body += render_daily(rows, today)
    else:
        body += render_weekly_monthly(rows, rtype, today)
    body += render_rolling_comparison(rows)
    body += render_current_buys(rows)
    body += render_news_section(news, news_status, now=now)

    html = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>moligod {t}（全子弹版） · {today}</title>
<style>
body{{font-family:'Microsoft YaHei',system-ui,sans-serif;background:#0e1420;color:#e6edf3;margin:0;padding:24px;line-height:1.6}}
.wrap{{max-width:1100px;margin:0 auto}}
h1{{font-size:22px;margin:0 0 4px}}
h2{{font-size:17px;border-left:4px solid #4a9eff;padding-left:10px;margin:30px 0 12px;color:#cfe3ff}}
.sub{{color:#8b98a9;font-size:12px;margin-bottom:10px}}
.tag{{display:inline-block;background:#1c2a44;color:#9ecbff;border:1px solid #2c4a7a;border-radius:4px;padding:2px 10px;font-size:12px;margin-right:8px}}
.badge{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px;margin:0 4px}}
.b-up{{background:#1e3a2f;color:#5ddb8e}}.b-down{{background:#3a1e24;color:#ff7d85}}
table{{width:100%;border-collapse:collapse;font-size:12.5px;margin:8px 0}}
th{{background:#16233a;color:#9ecbff;text-align:left;padding:7px 8px;border:1px solid #22314e}}
td{{padding:6px 8px;border:1px solid #1d2b44;text-align:left}}
tr:nth-child(even) td{{background:#101a2e}}
.pos{{color:#5ddb8e}}.neg{{color:#ff7d85}}.gray{{color:#8b98a9}}
.card{{background:#101a2e;border:1px solid #22314e;border-radius:8px;padding:14px 16px;margin:12px 0}}
.note{{background:#1a2438;border-left:4px solid #e0a63c;padding:10px 14px;border-radius:0 6px 6px 0;font-size:12.5px;margin:12px 0}}
.warn{{background:#2a1a20;border-left:4px solid #e0564a;padding:10px 14px;border-radius:0 6px 6px 0;font-size:12.5px;margin:12px 0}}
ul{{margin:6px 0;padding-left:20px}}
.src{{color:#6b7a8f;font-size:11px}}
</style></head><body><div class="wrap">
<h1>moligod {t}（全子弹版） · {today}</h1>
<div class="sub">报告日期：{today}（{wd}）｜覆盖 {tot} 种子弹｜{market_meta}</div>
{body}
<div class="note">行情单位为哈夫币；税后基准按挂价×0.87估算。滚动比较使用近7天和前23天历史均价；5级弹只提供实时行情。公告来自标注的官方 Steam feed，公告不等于价格预测，统计值也不保证收益。</div>
</div></body></html>""".format(
        t=t, today=today, wd=wd, tot=len(rows),
        market_meta=html_lib.escape(format_market_meta(market_meta)), body=body)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html)
    print('REPORT_ALL', rtype, 'rows=', len(rows), '->', out)

if __name__ == '__main__':
    main()
