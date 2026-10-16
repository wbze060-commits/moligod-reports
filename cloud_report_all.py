# -*- coding: utf-8 -*-
"""cloud_report_all.py — 全子弹版报告（68 款：26 三级 + 26 四级 + 16 五级）
在 cloud_report.py 基础上扩展：5 级弹仅实时行情（无 30 天 K 线，只进行情表/榜单/独立板块）。
口径：国服；滚动统计与附带验证样本的日抛/周抛条件计划；出售到手估算=挂价*0.87。
用法: python cloud_report_all.py [daily|weekly|monthly] [output.html]
"""
import json, os, sys, datetime
import html as html_lib
from report_data import (CHINA_TZ, BASELINE_DAYS, RECENT_DAYS, collect_daily, filter_fresh_news, format_market_meta, parse_history_date, rolling_stats)
from cloud_trade import get_plan
from trade_strategy import action_for
from report_brief import brief_for_plan, render_brief_section

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
    up = sum(1 for row in with_change if row["chg"] > 0)
    down = sum(1 for row in with_change if row["chg"] < 0)
    flat = len(with_change) - up - down
    quote_time = _beijing_time((market_meta or {}).get('completed_at_utc'))
    quote_time = ('更新时间未知' if quote_time in ('未记录', '时间格式无效')
                  else '更新 ' + quote_time)
    return (
        '<section class="market-pulse" aria-label="市场简况">'
        '<span>上涨 <b>%d款</b></span><span>下跌 <b>%d款</b></span><span>持平 <b>%d款</b></span>'
        '<span class="pulse-coverage">覆盖%d款 · %s · 涨跌近似</span></section>'
        % (up, down, flat, len(rows), _e(quote_time))
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
        '<details class="secondary-section"><summary>近7天趋势与历史对照（%d款）</summary>' % len(valid)
        + '<p class="sub">近7天与前23天均价比较；税后估算扣13%卖出费，只作参考。</p>'
        + '<div class="table-scroll" role="region" aria-label="滚动行情比较">'
        + '<table><caption>近7天与前23天价格比较</caption><thead><tr>'
        + '<th scope="col">子弹</th><th scope="col">等级</th><th scope="col">近7天均价</th>'
        + '<th scope="col">前23天均价</th><th scope="col">税后基准</th><th scope="col">当前空间/发</th>'
        + '<th scope="col">历史比较空间/发</th></tr></thead><tbody>'
        + ''.join(body) + '</tbody></table></div></details>')


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
    filtered = filter_fresh_news(news, now=now, region='CN')
    source = filtered.get("source") or {}
    if filtered.get('region') != 'CN':
        source = {'name': '三角洲行动国服官网', 'scope': '国服；已过滤国际服及未标注区服的内容'}
        status = {'status':'manual_only'}
    scope = _e(source.get("scope") or "公告源范围未标注")
    status = status or {}
    last_success = _beijing_time(status.get("last_success_at") or filtered.get("updated")) if filtered.get('region') == 'CN' else '未记录'
    status_line = "公告源：%s；上次成功刷新（北京时间）：%s" % (_e(source.get("name") or "未配置"), last_success)
    warning = ""
    if status.get('status') == 'manual_only':
        warning = '<div class="warn">国服自动公告源暂不可用；只展示人工核验的国服官网链接。</div>'
    elif status.get("status") == "error":
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
    label = ('国服公告更新未接通' if status.get('status') == 'manual_only' else
             '公告刷新失败' if status.get('status') == 'error' else
             '国服公告与观点（%d条）' % len(filtered.get('headlines', [])))
    return (
        '<details class="secondary-section"><summary>%s</summary><div class="sub">%s｜范围：%s</div>%s'
        '<div class="card">%s</div>'
        '<h3>有效期内的人工研判</h3><ul>%s</ul>'
        '<div class="note">%s</div></details>'
        % (_e(label), status_line, scope, warning, "".join(items), outlook_html, risk)
    )


def render_trade_plan(plan, meta, now):
    brief = brief_for_plan(plan, meta, now)
    details = render_trade_plan_details(plan, meta, now)
    return render_brief_section(brief) + details


def render_trade_plan_details(plan, meta, now):
    """Keep model evidence available without making the first screen a wall of text."""
    label = '日抛' if plan['kind'] == 'daily' else '周抛'
    detailed = []
    for item in plan['candidates']:
        stats = item.get('backtest') or {'fills': 0, 'hit_rate': 0}
        detailed.append(
            '<tr><th scope="row">%s</th><td>%s</td><td>%s–%s</td><td>≥%s</td>'
            '<td>%s</td><td>%s</td><td>&lt;%s</td><td>%s</td><td>%d次 · %.0f%%</td></tr>' % (
                _e(item['name']), _e(item['qualification']), _e(item['buy_low']), _e(item['buy_high']),
                _e(item['sell_target']), _e(item['break_even']), _e(item['break_even_with_slippage']),
                _e(item['invalidate_below']), _e(item['net_per_round']), stats['fills'], stats['hit_rate']*100))
    if not detailed:
        detailed.append('<tr><td colspan="9">没有达到推荐条件的候选；当前保持观望。</td></tr>')
    return ('<details class="secondary-section"><summary>%s计划细节与历史验证</summary>'
            '<p class="sub">目标价只适用于确实持有的仓位；回测不代表未来胜率，也不包含真实挂单排队。</p>'
            '<div class="table-scroll" role="region" aria-label="%s计划价位与历史验证">'
            '<table><caption>%s计划价位与验证数据</caption><thead><tr><th scope="col">子弹</th>'
            '<th scope="col">筛选状态</th><th scope="col">买入区间</th><th scope="col">目标卖价</th>'
            '<th scope="col">费后保本</th><th scope="col">含滑点保本</th><th scope="col">失效线</th>'
            '<th scope="col">估算净空间/发</th><th scope="col">验证成交 · 到目标率</th></tr></thead><tbody>%s</tbody></table>'
            '</div></details>') % (_e(label), _e(label), _e(label), ''.join(detailed))


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
        '<tr data-grade="%s" data-name="%s"><th scope="row">%s</th><td>%s</td>'
        '<td>%s</td><td class="%s">%s</td></tr>'
        % (
            _e(row["grade"]), _e(row["name"]).lower(), _e(row["name"]),
            _e(row["grade"]), _e(row["latest"]),
            cls(row["chg"]), _pct(row["chg"]),
        )
        for row in ordered
    )
    up = [row for row in ordered if row['chg'] > 0][:3]
    down = list(reversed([row for row in ordered if row['chg'] < 0][-3:]))
    ranked = ''.join(board(up)) + ''.join(board(down))
    unavailable = len(rows) - len(with_change)
    unavailable_text = ('（另%d款暂无当日涨跌数据）' % unavailable) if unavailable else ''
    return (
        '<details class="secondary-section" id="market-details">'
        '<summary>全部行情 · %d/%d款</summary><p class="sub">当日比较价暂缺的子弹不显示，最新价来自行情源。</p>'
        '<div class="market-controls"><label for="ammo-search">搜索子弹</label>'
        '<input type="search" id="ammo-search" autocomplete="off" placeholder="输入子弹名称" aria-label="按名称搜索子弹">'
        '<div class="grade-filters" role="group" aria-label="按等级筛选">'
        '<button type="button" data-grade-filter="all" aria-pressed="true">全部</button>'
        '<button type="button" data-grade-filter="3" aria-pressed="false">3级</button>'
        '<button type="button" data-grade-filter="4" aria-pressed="false">4级</button>'
        '<button type="button" data-grade-filter="5" aria-pressed="false">5级</button></div></div>'
        '<p id="market-status" class="sub" aria-live="polite">共%d款%s</p>'
        '<p id="market-empty" class="brief-empty" hidden>没有匹配的子弹，试试其他名称。</p>'
        '<div class="table-scroll" role="region" tabindex="0" aria-label="今日子弹行情，可横向滚动">'
        '<table id="market-rows"><caption>今日子弹价与近似涨跌</caption>'
        '<thead><tr><th scope="col">子弹</th><th scope="col">等级</th><th scope="col">最新价</th>'
        '<th scope="col">涨跌幅</th></tr></thead><tbody>%s</tbody></table></div></details>'
        '<details class="secondary-section"><summary>今日涨跌榜（各3款）</summary>'
        '<div class="table-scroll" role="region" aria-label="今日涨跌榜">'
        '<table><caption>涨幅、跌幅各前三名</caption><thead><tr><th scope="col">子弹</th>'
        '<th scope="col">等级</th><th scope="col">涨跌幅</th><th scope="col">最新价</th></tr></thead>'
        '<tbody>%s</tbody></table></div></details>'
        % (len(with_change), len(rows), len(with_change), unavailable_text, market_rows, ranked)
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

    body = ''
    if rtype in ('daily', 'weekly'):
        plan, plan_meta = get_plan(BASE, rtype, now)
        body += render_trade_plan(plan, plan_meta, now)
    body += render_overview(rows, today, market_meta)
    if rtype == 'daily':
        body += render_daily(rows, today)
    else:
        body += render_weekly_monthly(rows, rtype, today)
    body += render_rolling_comparison(rows)
    body += render_news_section(news, news_status, now=now)

    html = """<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>三角洲国服 · {t} · {today}</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:'Microsoft YaHei',system-ui,sans-serif;background:#0e1420;color:#e6edf3;margin:0;padding:clamp(12px,3vw,24px);line-height:1.55}}
.wrap{{max-width:1000px;margin:0 auto;min-width:0}}
.skip-link{{position:absolute;left:-10000px;top:auto}}.skip-link:focus{{left:12px;top:12px;z-index:5;background:#fff;color:#111;padding:10px}}
h1{{font-size:clamp(20px,5vw,26px);margin:0 0 4px}}
h2{{font-size:17px;border-left:4px solid #4a9eff;padding-left:10px;margin:0 0 8px;color:#cfe3ff}}
.report-header{{margin-bottom:14px}}
.market-pulse{{display:flex;flex-wrap:wrap;align-items:center;gap:8px 16px;background:#101a2e;border:1px solid #22314e;border-radius:10px;padding:10px 14px;margin:14px 0}}
.market-pulse>span:not(.pulse-coverage){{white-space:nowrap}}
.pulse-coverage{{color:#aab8ca;font-size:12px;flex-basis:100%}}
.daily-brief{{background:#111d31;border:1px solid #31517e;border-top:3px solid #4a9eff;border-radius:12px;padding:14px;margin:14px 0 18px}}
.brief-heading{{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}}
.brief-heading h2{{font-size:22px;border:0;padding:0;margin:0 0 4px}}
.brief-heading time{{font-size:12px;color:#aab8ca;text-align:right;white-space:nowrap}}
.eyebrow{{color:#9ecbff;font-size:12px;margin:0 0 4px}}
.brief-sentence{{margin:0 0 10px}}
.brief-card{{border-top:1px solid #2a3d5b;padding:9px 0}}
.brief-card-head{{display:flex;justify-content:space-between;gap:8px;align-items:baseline}}
.brief-card h3{{font-size:15px;margin:0}}
.signal-state{{font-size:12px;color:#91d7ae}}
.brief-prices{{display:flex;flex-wrap:wrap;gap:4px 12px;margin:5px 0;font-variant-numeric:tabular-nums}}
.brief-invalidation,.brief-window,.brief-risk,.brief-empty,.brief-more{{font-size:12px;color:#b4c0d0;margin:4px 0}}
.brief-window{{padding-top:6px;border-top:1px solid #2a3d5b}}
.secondary-section{{border-top:1px solid #243550;margin:12px 0;padding-top:10px}}
.secondary-section>summary{{cursor:pointer;font-weight:600;padding:5px 2px;min-height:40px;display:flex;align-items:center}}
.secondary-section>summary:focus-visible,button:focus-visible,input:focus-visible{{outline:2px solid #87bfff;outline-offset:2px}}
.market-controls{{display:none;gap:8px;flex-wrap:wrap;align-items:center;margin:10px 0}}
.js-enabled .market-controls{{display:flex}}
#ammo-search{{min-width:150px;max-width:100%;padding:8px;background:#0e1420;color:#e6edf3;border:1px solid #51637f;border-radius:6px}}
.grade-filters{{display:flex;gap:6px;flex-wrap:wrap}}
button{{padding:8px 11px;background:#18263d;color:#e6edf3;border:1px solid #435878;border-radius:7px;cursor:pointer}}
button[aria-pressed=true]{{background:#294877;border-color:#78aef6}}
.table-scroll{{max-width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch}}
.sub{{color:#8b98a9;font-size:12px;margin-bottom:10px}}
.tag{{display:inline-block;background:#1c2a44;color:#9ecbff;border:1px solid #2c4a7a;border-radius:4px;padding:2px 10px;font-size:12px;margin-right:8px}}
.badge{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px;margin:0 4px}}
.b-up{{background:#1e3a2f;color:#5ddb8e}}.b-down{{background:#3a1e24;color:#ff7d85}}
table{{width:100%;border-collapse:collapse;font-size:12.5px;margin:8px 0}}
caption{{text-align:left;color:#aab8ca;padding:5px 0}}
th{{background:#16233a;color:#9ecbff;text-align:left;padding:7px 8px;border:1px solid #22314e}}
td{{padding:6px 8px;border:1px solid #1d2b44;text-align:left}}
tr:nth-child(even) td{{background:#101a2e}}
.pos{{color:#5ddb8e}}.neg{{color:#ff7d85}}.gray{{color:#8b98a9}}
.card{{background:#101a2e;border:1px solid #22314e;border-radius:8px;padding:14px 16px;margin:12px 0}}
.note{{background:#1a2438;border-left:4px solid #e0a63c;padding:10px 14px;border-radius:0 6px 6px 0;font-size:12.5px;margin:12px 0}}
.warn{{background:#2a1a20;border-left:4px solid #e0564a;padding:10px 14px;border-radius:0 6px 6px 0;font-size:12.5px;margin:12px 0}}
ul{{margin:6px 0;padding-left:20px}}
.src{{color:#6b7a8f;font-size:11px}}
@media(max-width:560px){{
  .brief-heading{{display:block}}.brief-heading time{{display:block;text-align:left;margin:3px 0 8px}}
  .daily-brief{{padding:12px}}.pulse-coverage{{flex-basis:100%}}
  table{{min-width:450px}}.brief-prices{{gap:3px 8px}}
}}
@media print{{
  body{{background:#fff;color:#111;padding:8mm;font-size:10pt}}
  .wrap{{max-width:none}}.market-pulse,.brief-card,.daily-brief{{background:#fff;color:#111;border-color:#aaa}}
  .secondary-section{{display:none}}.sub,.brief-risk,.brief-invalidation,.brief-heading time{{color:#444}}
  a{{color:#111;text-decoration:none}}
}}
</style></head><body><a class="skip-link" href="#main-content">跳到日报摘要</a><main class="wrap" id="main-content">
<header class="report-header"><h1>三角洲国服 · {t}</h1>
<div class="sub">{today}（{wd}）｜{tot}款子弹</div></header>
{body}
<footer class="note">买卖前核对国服挂单。13%手续费及2%卖出滑点为估算，实际以游戏内为准。HTML可展开明细；PDF只含摘要。</footer>
</main><script>
document.documentElement.classList.add('js-enabled');
(()=>{{const table=document.getElementById('market-rows');if(!table)return;
const rows=[...table.querySelectorAll('tbody tr')],search=document.getElementById('ammo-search');
const status=document.getElementById('market-status'),empty=document.getElementById('market-empty');
let grade='all';
function update(){{const term=(search.value||'').trim().toLowerCase();let visible=0;
for(const row of rows){{const show=(grade==='all'||row.dataset.grade===grade)&&(!term||row.dataset.name.includes(term));row.hidden=!show;if(show)visible++;}}
status.textContent='显示 '+visible+' / '+rows.length+' 款';empty.hidden=visible!==0;}}
for(const button of document.querySelectorAll('[data-grade-filter]'))button.addEventListener('click',()=>{{grade=button.dataset.gradeFilter;for(const option of document.querySelectorAll('[data-grade-filter]'))option.setAttribute('aria-pressed',String(option===button));update();}});
search?.addEventListener('input',update);update();}})();
</script></body></html>""".format(
        t=t, today=today, wd=wd, tot=len(rows),
        market_meta=html_lib.escape(format_market_meta(market_meta)), body=body)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html)
    print('REPORT_ALL', rtype, 'rows=', len(rows), '->', out)

if __name__ == '__main__':
    main()
