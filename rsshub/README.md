# RSSHub（workbench 的通用 RSS 转换层）

把没有 RSS 的站点转成 RSS，供 workbench 的 `rss` adapter 消费。

## 起服务

```bash
cp .env.example .env      # 按注释填 token / cookie
docker compose up -d
docker compose logs -f rsshub
```

## 验证

```bash
# 应该输出 XML（<rss ...> 开头）
curl -s "http://localhost:1200/github/topics/mcp" | head -30

# 带路由参数（注意：qs 是路径段，不是 ?查询串）
curl -s "http://localhost:1200/github/topics/mcp/l=python&o=desc&s=updated" | head -30

# Telegram 公开频道（无需任何凭证）
curl -s "http://localhost:1200/telegram/channel/awesomeRSSHub" | head -30
```

出 `<rss>` 且有 `<item>` 就成了。出 JSON 错误对象说明该路由需要凭证或被上游拦了。

## 接进 workbench

源管理里新建 RSS 源，URL 填 `http://localhost:1200/<路由>`。

⚠️ workbench 后端是宿主机 venv 起的（见 `../start.sh`），所以 `localhost:1200`
直接可达。若将来后端也搬进 docker-compose，URL 必须改成容器可达的地址
（把两个 compose 接到同一个 external network，然后用 `http://rsshub:1200/`），
否则会在状态列看到「域名解析失败」。

## 已验证可用的路由（2026-08-23 实测）

| 路由 | 状态 | 备注 |
|---|---|---|
| `/github/topics/:name/:qs?` | ✅ | 每次约 20 条，**无分页**，这是上限 |
| `/github/search/:query/:sort?/:order?` | ❌ | 抓 github.com/search 页面，公共实例全挂；自建 + token 可试 |
| `/telegram/channel/:username` | ✅ | 默认走 t.me/s/ 公开预览，零凭证 |
| `/zhihu/topic/:topicId/:isTop?` | 需 cookie | isTop 传任意值 = 只要精华 |
| `/zhihu/zhuanlan/:id` | 需 cookie | |
| `/zhihu/hot/:category?` | cookie 可选 | 你已有 newsnow 的知乎热榜源，这条可以不用 |

## 不要用 RSSHub 的场景

- **GitHub releases / commits / tags**：GitHub 原生提供 `.atom`，直连更稳
  （`https://github.com/{owner}/{repo}/releases.atom`）
- **GitHub 关键词搜热门仓库**：用 workbench 自己的 `github_search` adapter，
  走官方 Search API，有 `min_stars` / `window_days` 过滤，比 RSSHub 的
  HTML 抓取稳得多
- **已有官方 RSS 的站点**（OpenAI / DeepMind / HF / vLLM / MCP 博客 / 量子位）：
  直接订官方 feed

## 维护提醒

- 知乎 `z_c0` cookie 会过期（几周到几个月）。过期后是**静默失败**——返回空
  feed 而不是报错。workbench 的错误分类会标成 `empty_feed`，看到就去换 cookie。
- 上游站点改版会导致路由失效，需定期 `docker compose pull && docker compose up -d`。
- 预算：机器资源可忽略（官方文档给的参考规格是 cpu 1 / 内存 0.5G），
  真正的成本是每月 15~30 分钟的维护。
