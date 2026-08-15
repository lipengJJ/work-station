"""AI 开发热点聚合模块。

四层结构（controllers / models / schemas / services），与 resource / xhs 模块一致：
- models: 热点条目（ai_trending_items）+ 来源健康状态（ai_trending_source_status）
- schemas: API 出入参
- services: 抓取器抽象基类 + 6 源实现 + Collector 统一执行 + APScheduler 定时任务
- controllers: /api/ai-trending/* 只读查询与手动刷新
"""
