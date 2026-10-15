# -*- coding: utf-8 -*-
"""cloud_push.py — 微信推送报告厚内容（Server酱）
用法: SCT_KEY=xxx python cloud_push.py [daily|weekly|monthly] [date]
把市场概览/持仓/涨跌榜/可入手/消息面全部塞进推送，链接仅作补充。
"""
import json, os, sys, re, datetime, urllib.request, urllib.parse

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

    lines = ['**国服 moligod %s · %s**' % (label, date), '']
    plans = extract_trade_plans(html)
    if plans:
        lines.append('🎯 国服买卖计划（北京时间）：')
        lines.extend('- ' + text for text in plans)
        lines.append('到价后核对国服挂单；未记录你的真实持仓成本，模拟空间不保证成交或盈利。')
        lines.append('')

    tags = extract_overview(html)
    if tags:
        lines.append('📊 市场概览：')
        for t in tags:
            lines.append('- ' + t)
        lines.append('')

    hld = extract_holdings(html)
    if hld:
        lines.append('📈 关注子弹今日：')
        for n, cur, chg in hld:
            lines.append('- %s：最新 %s（%s）' % (n, cur, chg))
        lines.append('')

    ups = extract_rank(html, '涨幅榜', 3)
    if ups:
        lines.append('🔺 涨幅 TOP3：')
        for n, g, chg, cur in ups:
            lines.append('- %s：%s（现价 %s）' % (n, chg, cur))
        lines.append('')

    downs = extract_rank(html, '跌幅榜', 3)
    if downs:
        lines.append('🔻 跌幅 TOP3：')
        for n, g, chg, cur in downs:
            lines.append('- %s：%s（现价 %s）' % (n, chg, cur))
        lines.append('')

    top = extract_top_buy(html)
    if top:
        lines.append('🎯 当前可入手（3级弹）：')
        for n, cur, sp in top:
            lines.append('- %s：现价 %s，空间 %s' % (n, cur, sp))
        lines.append('')

    news = extract_news(html)
    if news:
        lines.append('📰 官方公告 / 有效观点：')
        for it in news:
            lines.append('- ' + it[:80])
        lines.append('')

    enc = lambda s: urllib.parse.quote(s, safe='/:')
    lines.append('📄 [完整报告 HTML](%s%s)' % (PAGES, enc(fname + '.html')))
    lines.append('📄 [PDF 版](%s%s)' % (PAGES, enc(fname + '.pdf')))

    desp = '\n'.join(lines)
    title = 'moligod %s %s' % (label, date)
    resp = push(key, title, desp)
    code = resp.get('code')
    if code == 0:
        print('PUSH_OK pushid=', resp.get('data', {}).get('pushid'))
    else:
        print('PUSH_FAIL', resp)
        sys.exit(1)


if __name__ == '__main__':
    main()
