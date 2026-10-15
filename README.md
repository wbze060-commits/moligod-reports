# moligod 子弹行情自动化

三角洲行动子弹行情报告与交易提醒，运行在 GitHub Actions。

## 报告

- 日报：每天北京时间 22:30。
- 周报：每周日北京时间 22:30。
- 月报：每月 1 日北京时间 22:30。
- 覆盖 68 种子弹：3/4 级提供滚动行情统计，5 级提供实时行情。
- 报告保存为 HTML 和 PDF，数据快照保存在 data/。
- 统计比较近 7 天与此前 23 天，显示价格数据采集时间、有效样本数和 13% 税后基准。
- 公告来自 Steam Community Announcements（Steam 国际服 feed），保留来源链接；30 天后自动过期隐藏。公告不会自动生成价格预测。

## 盯价提醒

- .357 Magnum FMJ：每 5 分钟检查；最新价或今日最高价达到 800 时提醒，冷却 6 小时。
- 重点子弹：每小时检查指定列表，较上一快照涨跌达到 5% 时提醒。
- 三级弹策略：每小时检查指定买卖线，状态进入买入/卖出区间时提醒。

## 微信与历史报告

Server 酱通过仓库 Secret SCT_KEY 推送报告摘要和 HTML/PDF 直链。
历史文件位于 reports 目录：https://github.com/wbze060-commits/moligod-reports/tree/main/reports
