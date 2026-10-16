# -*- coding: utf-8 -*-
"""cloud_push.py — 微信推送报告厚内容（Server酱）
用法: SCT_KEY=xxx python cloud_push.py [daily|weekly|monthly] [date]
把市场概览/持仓/涨跌榜/可入手/消息面全部塞进推送，链接仅作补充。
"""
import json, os, sys, re, datetime, urllib.request, urllib.parse
from report_brief import push_summary

BASE = os.path.dirname(os.path.abspath(__file__))
PAGES = 'https://wbze060-commits.github.io/moligod-reports/reports/'
TYPE_MAP = {'daily': '日报', 'weekly': '周报', 'monthly': '月报'}
# 用户持仓子弹（与今日行情表名称一致），推送里单列
HOLDINGS = ['12.7x55mm PS12A', '.45 ACP FMJ', '5.8x42mm DVP88', '.357 Magnum FMJ']


def push(key, title, desp):
    url = 'https://sctapi.ftqq.com/%s.send' % key
    data = urllib.parse.urlencode({'title': title, 'desp': desp}).encode('utf-8')
    req = urllib.request.Request(url, data=data)
    resp = json.loads(urllib.request.urlopen(req, timeout=30).read().decode('utf-8'))
    return resp


def extract_overview(html):
    m = re.search(r'<b>📊 市场概览</b><br>(.*?)</div>', html, re.S)
    tags = []
    if m:
        tags = re.findall(r'<span class="tag">(.*?)</span>', m.group(1))
    return tags


def extract_holdings(html):
    """从今日行情表提取用户持仓子弹的今日价格与涨跌幅"""
    m = re.search(r'<h2>今日行情表.*?</table>', html, re.S)
    if not m:
        return []
    out = []
    for row in re.findall(r'<tr>(.*?)</tr>', m.group(0), re.S):
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
        if len(cells) < 7:
            continue
        name = re.sub(r'<[^>]+>', '', cells[0]).strip()
        if name in HOLDINGS:
            out.append((name, cells[2].strip(), cells[6].strip()))
    return out


def extract_rank(html, h2_keyword, limit=3):
    """提取涨幅/跌幅榜表格：行 = [名字, 等级, 涨跌幅, 最新价]"""
    m = re.search(r'<h2>%s.*?</table>' % re.escape(h2_keyword), html, re.S)
    if not m:
        return []
    out = []
    for row in re.findall(r'<tr>(.*?)</tr>', m.group(0), re.S):
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
        if len(cells) < 4:
            continue
        vals = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
        if vals[0] and vals[0] != '子弹':
            out.append(tuple(vals))
        if len(out) >= limit:
            break
    return out


def extract_top_buy(html, limit=3):
    """提取当前可入手清单（3级弹）：名字/现价/税后空间"""
    m = re.search(r'<h2>当前可入手清单.*?</table>', html, re.S)
    if not m:
        return []
    seg = m.group(0)
    rows = re.findall(r'<tr><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td><td>(.*?)</td><td[^>]*>(.*?)</td></tr>', seg)
    out = []
    for name, cur, taxnet, space, rate in rows[:limit]:
        out.append((re.sub(r'<[^>]+>', '', name).strip(),
                    re.sub(r'<[^>]+>', '', cur).strip(),
                    re.sub(r'<[^>]+>', '', space).strip()))
    return out


def extract_trade_plans(html, limit=3):
    match = re.search(r'<section class="trade-plan">(.*?)</section>', html, re.S)
    if not match:
        return []
    cards = re.findall(r'<article class="trade-item">(.*?)</article>', match.group(1), re.S)
    if not cards:
        cards = [match.group(1)]
    result = []
    for card in cards[:limit]:
        text = re.sub(r'<[^>]+>', ' ', card)
        result.append(__import__('html').unescape(re.sub(r'\s+', ' ', text)).strip())
    return result


def extract_report_brief(html):
    """Read the exact same structured brief that the HTML page displays."""
    match = re.search(
        r'<script type="application/json" id="report-brief-data">(.*?)</script>', html, re.S
    )
    if not match:
        return None
    try:
        brief = json.loads(match.group(1))
    except (TypeError, ValueError):
        return None
    if not isinstance(brief, dict) or brief.get('schema') != 1 or brief.get('region') != 'CN':
        return None
    if brief.get('kind') not in ('daily', 'weekly') or not isinstance(brief.get('cards'), list):
        return None
    return brief


def extract_news(html, limit=3):
    """提取报告中的官方公告和仍有效的人工观点。"""
    match = re.search(
        r'<h2>官方公告与有效观点</h2>(.*?)(?:<h2>|$)', html, re.S
    )
    if not match:
        match = re.search(
            r'<h2>消息面与价格走势预测.*?</h2>(.*?)(?:<h2>|$)', html, re.S
        )
    if not match:
        return []
    body = match.group(1)
    cards = re.findall(r'<article class="news-item">(.*?)</article>', body, re.S)
    if not cards:
        cards = [body]
    out = []
    for card in cards:
        text = re.sub(r'<br\s*/?>', ' ', card, flags=re.I)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = __import__('html').unescape(re.sub(r'\s+', ' ', text)).strip()
        if text:
            out.append(text[:240])
        if len(out) >= limit:
            break
    return out

def main():
    rtype = sys.argv[1] if len(sys.argv) > 1 else 'daily'
    date = sys.argv[2] if len(sys.argv) > 2 else datetime.date.today().isoformat()
    key = os.environ.get('SCT_KEY', '').strip()
    if not key:
        print('NO_SCT_KEY'); sys.exit(1)
    label = TYPE_MAP.get(rtype, '日报')
    fname = '%s_%s' % (label, date)
    html_path = os.path.join(BASE, 'reports', fname + '.html')
    if not os.path.exists(html_path):
        print('NO_REPORT', html_path); sys.exit(1)
    html = open(html_path, encoding='utf-8').read()

    brief = extract_report_brief(html)
    if brief:
        desp = push_summary(brief, date, PAGES, rtype)
        title = '国服 moligod %s %s' % (label, date)
        response = push(key, title, desp)
        if response.get('code') == 0:
            print('PUSH_OK pushid=', response.get('data', {}).get('pushid'))
        else:
            print('PUSH_FAIL code=', response.get('code'))
            sys.exit(1)
        return

    # Old stored reports retain their link, but avoid resending the old wall of text.
    name = urllib.parse.quote(fname, safe='')
    desp = ('**国服 moligod %s · %s**\n\n'
            '这份旧报告没有精简摘要，请打开HTML查看。\n\n'
            '[打开报告 HTML](%s%s.html) · [PDF 版](%s%s.pdf)') % (
                label, date, PAGES, name, PAGES, name)
    title = 'moligod %s %s' % (label, date)
    resp = push(key, title, desp)
    code = resp.get('code')
    if code == 0:
        print('PUSH_OK pushid=', resp.get('data', {}).get('pushid'))
    else:
        print('PUSH_FAIL code=', code)
        sys.exit(1)


if __name__ == '__main__':
    main()
