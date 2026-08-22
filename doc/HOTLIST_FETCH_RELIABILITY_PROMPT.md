# 热点聚合 · 抓取可靠性修复任务书（交付给 DeepSeek 执行）

> 项目：`/Users/lipeng01/vscode/workbench`，模块 `backend/app/hotlist`
> 起因：源管理页 81 个源大面积「失败（连续 N 次）」，报错
> `NameResolutionError: Failed to resolve 'aiweirdness.com' ([Errno 8] ...)`

---

## 一、诊断结论（已验证，**不要重复排查**）

### 1.1 报错的这个源本身是好的

`https://aiweirdness.com/rss` 从外网访问**完全正常**：合法 RSS 2.0，16 条目，
`lastBuildDate` 是最近。该源在库里已有 15 条历史数据，说明以前抓成功过。

`[Errno 8] nodename nor servname provided` 是 **macOS 的 `EAI_NONAME`**，
即本机 DNS 解析失败。域名有效 + 本机解析不到 = **本机网络/DNS 的瞬时问题**
（网络断开、休眠唤醒、DNS 缓存、或需要代理），不是源失效。

### 1.2 真正的大问题：75% 的源依赖同一个第三方上游

按 `adapter_params.url` 的 host 统计库里的 RSS 源：

```
  62  api.xgo.ing        ← 占 83 个 RSS 源的 75%
   1  www.infoq.cn
   1  www.36kr.com
   1  api.bestblogs.dev
   1  simonwillison.net
   1  venturebeat.com
   …（其余各 1）
总 RSS 源: 83
```

`https://api.xgo.ing/` 当前返回 **`System error, please try again later`（错误码 xgo-9999）**。
一个上游挂掉 → 62 个源同时失败。

### 1.3 现有逻辑会把这 62 个源全部误杀

`crawl_service.update_source_status()` 对**任何**失败都执行
`consecutive_failures += 1`，而 `topic_service.list_stale_source_ids()` 用
`consecutive_failures >= STALE_FAILURE_THRESHOLD` 判定失效源、`disable_stale_sources()` 自动关闭。

按 4 小时抓一次算，**上游挂 12 小时就会把 62 个完全健康的源自动关掉**，
且关掉之后不再抓取、永远不会自愈。这是本次必须优先修的设计缺陷。

---

## 二、修复项

### 2.1 【核心】错误分类：新增 `last_error_kind`

现在所有失败都收敛成一句「失败（连续 N 次）」，83 个源根本没法治理——
DNS 失败、404、403、返回 HTML 不是 RSS，处置方式完全不同。

**`models/hot_source.py` 新增字段**：

```python
last_error_kind: Mapped[str] = mapped_column(String(24), default="")
"""失败类型，决定这次失败算不算「源坏了」：

  瞬时类（transient）—— 大概率是本机网络或上游抖动，不该判定源失效：
    dns_error         DNS 解析失败（socket.gaierror / NameResolutionError）
    connect_timeout   TCP 连接超时
    read_timeout      读取超时
    connection_error  连接被拒 / 重置
    upstream_5xx      上游返回 5xx
    upstream_down     同 host 批量失败被熔断跳过（见 2.3）

  永久类（permanent）—— 源本身有问题，应提示用户删除：
    http_404 / http_410   feed 地址已失效
    parse_error           返回内容不是合法 RSS/Atom（通常是 HTML 错误页）
    empty_feed            能解析但 0 条目（连续多次才算）

  需干预类（blocked）—— 源活着但拒绝我们：
    http_403          被拒（多半要真实 UA 或代理）
    http_429          限流（该降频）
"""

transient_failures: Mapped[int] = mapped_column(Integer, default=0)
permanent_failures: Mapped[int] = mapped_column(Integer, default=0)
```

`consecutive_failures` 字段**保留**（UI 还在用，表示"连续失败次数"，不分类型）。

**分类实现**放在 `services/adapters/base.py`，`HotSourceAdapter._request()` 里：

```python
except requests.exceptions.ConnectionError as exc:
    # urllib3 的 NameResolutionError 包在 ConnectionError 里，靠字符串或类型判断
    kind = "dns_error" if _is_dns_error(exc) else "connection_error"
    raise HotSourceAdapterError(str(exc), kind=kind) from exc
except requests.exceptions.ConnectTimeout as exc:
    raise HotSourceAdapterError(str(exc), kind="connect_timeout") from exc
except requests.exceptions.ReadTimeout as exc:
    raise HotSourceAdapterError(str(exc), kind="read_timeout") from exc
except requests.exceptions.HTTPError as exc:
    code = exc.response.status_code if exc.response is not None else 0
    kind = {404: "http_404", 410: "http_410", 403: "http_403", 429: "http_429"}.get(code)
    if not kind:
        kind = "upstream_5xx" if 500 <= code < 600 else "connection_error"
    raise HotSourceAdapterError(f"HTTP {code}", kind=kind) from exc
```

给 `HotSourceAdapterError` 加 `kind` 属性（默认 `""`），`rss.py` 里的
`bozo` 解析失败抛 `kind="parse_error"`，0 条目抛 `kind="empty_feed"`。

### 2.2 【核心】失效判定按错误类型分流

`crawl_service.update_source_status()`：

```python
TRANSIENT_KINDS = {"dns_error", "connect_timeout", "read_timeout",
                   "connection_error", "upstream_5xx", "upstream_down"}

if ok:
    重置全部计数
else:
    source.last_error_kind = kind
    source.consecutive_failures += 1
    if kind in TRANSIENT_KINDS:
        source.transient_failures += 1        # 只记录，不参与失效判定
    else:
        source.permanent_failures += 1
```

`topic_service.list_stale_source_ids()` 的判定条件从
`consecutive_failures >= 3` 改为 **`permanent_failures >= 3`**。

> 这一条直接解决 §1.3 的误杀：上游挂掉产生的是 `upstream_5xx` / `upstream_down`，
> 属于瞬时类，不会让 62 个健康源被自动关闭。

同时 `disable_stale_sources()` 的行为改成**只标记不自动关闭**——
在 UI 上把这些源标红并给「批量关闭」按钮，由用户确认。自动关闭一旦误判就无法自愈。

### 2.3 【核心】上游主机熔断

62 个源指向同一个 host，上游挂掉时会逐个等 20 秒超时 = **20 分钟白等**，
而且每个源都记一次失败。

在 `crawl_service.run_crawl()` 里加 host 级熔断：

```python
HOST_FAILURE_THRESHOLD = 3   # 同一 host 本批次连续失败 3 次即熔断

host_failures: dict[str, int] = {}
host_tripped: set[str] = set()

for source in sources:
    host = _source_host(source)          # 从 adapter_params.url 解析 hostname
    if host in host_tripped:
        # 跳过，记 upstream_down（瞬时类，不影响失效判定），不发请求
        update_source_status(db, source, ok=False,
                             error=f"上游 {host} 本轮已熔断，跳过", kind="upstream_down")
        continue
    try:
        ...抓取...
        host_failures[host] = 0
    except HotSourceAdapterError as exc:
        if exc.kind in {"dns_error", "connect_timeout", "connection_error", "upstream_5xx"}:
            host_failures[host] = host_failures.get(host, 0) + 1
            if host_failures[host] >= HOST_FAILURE_THRESHOLD:
                host_tripped.add(host)
                logger.warning(f"上游 {host} 连续失败 {HOST_FAILURE_THRESHOLD} 次，本轮熔断，"
                               f"跳过其余 {剩余同 host 源数} 个源")
```

熔断只作用于**本批次**，下一轮重新尝试（上游恢复即自愈）。
`http_403` / `http_404` / `parse_error` **不计入 host 熔断**——那是单个源的问题，不是上游的。

### 2.4 批次前网络预检

笔记本合盖一夜后第一次定时抓取，会因为网络还没恢复导致 83 个源全失败。
在 `run_crawl()` 开头加预检：

```python
def _network_available(timeout: float = 3.0) -> bool:
    """解析 + 连接一个稳定域名，判断本机网络是否可用。
    用 DNS 解析（socket.getaddrinfo）而不是 HTTP 请求，快且不依赖具体站点可达。
    """

if not _network_available():
    logger.warning("本机网络不可用，跳过本轮抓取（不累加任何失败计数）")
    return CrawlResult(skipped=True, reason="network_unavailable")
```

**跳过时不写任何 `update_source_status`**，否则一次断网会让所有源的
`consecutive_failures` 平白加 1。

### 2.5 requests 层加固（`services/adapters/base.py`）

现有 `_request()` 是裸 `requests.get()`，四个问题：

| 问题 | 现状 | 改法 |
|---|---|---|
| 无重试 | DNS 抖动一次就判失败 | `urllib3.Retry(total=2, connect=2, read=1, backoff_factor=0.8, status_forcelist=[502,503,504])` 挂到 `HTTPAdapter` |
| 无连接池 | 83 个源各自新建连接 | 模块级共享 `requests.Session()`，`pool_connections=10, pool_maxsize=20` |
| 超时不分离 | `timeout=20` 连接和读取共用 | 改成 `timeout=(5, 15)`，连接 5 秒读取 15 秒 |
| UA 像爬虫 | `WorkBench-Hotlist/1.0` | 改成真实浏览器 UA。Cloudflare 前置的站点会直接 403 掉自报家门的 bot UA |

**新增代理支持**（你在国内，部分源必须走代理）：

```python
# ApiConfig 读 hotlist_http_proxy（形如 http://127.0.0.1:7890），空则不用
# HotSource 新增字段 use_proxy: bool = False，源级别开关
```

源编辑弹窗加「走代理」勾选框，配合 §2.6 的诊断按钮可以逐个试出哪些源需要代理。

### 2.6 单源诊断按钮

83 个源要治理，必须能一键看出「卡在哪一步」。
`POST /api/hotlist/sources/{source_id}/diagnose`，**同步执行**，分步返回：

```json
{
  "steps": [
    {"name": "DNS 解析",     "ok": true,  "detail": "aiweirdness.com → 104.21.x.x", "ms": 42},
    {"name": "TCP 连接",     "ok": true,  "detail": "443 端口连通", "ms": 128},
    {"name": "HTTP 请求",    "ok": true,  "detail": "200 OK", "ms": 340},
    {"name": "Content-Type", "ok": true,  "detail": "application/rss+xml"},
    {"name": "XML 解析",     "ok": true,  "detail": "RSS 2.0"},
    {"name": "条目提取",     "ok": true,  "detail": "16 条，最新 2026-06-23"}
  ],
  "verdict": "healthy",
  "suggestion": ""
}
```

失败时在**第一个失败的步骤**停下并给建议：

| 卡在 | suggestion |
|---|---|
| DNS 解析 | 「域名解析失败。该域名从外部可解析时通常是本机网络/DNS 问题；请检查网络或为该源开启代理」 |
| TCP 连接 | 「端口不通，可能被墙或站点下线，尝试开启代理」 |
| HTTP 403 | 「站点拒绝访问，尝试开启代理」 |
| HTTP 404 | 「feed 地址已失效，建议删除该源或更新 URL」 |
| Content-Type 是 text/html | 「返回的是网页不是 feed，URL 可能填错」 |

诊断接口**不受 30 秒抓取限频约束**（它是排障工具，要允许连续点）。

### 2.7 UI 改动（`views/hotlist/sources/index.vue`）

1. **状态列显示错误类型徽章**，不要只写「失败（连续 N 次）」：

   ```
   ● DNS 解析失败 (2)     ← 灰色/橙色，瞬时类
   ● 上游故障 (5)         ← 橙色
   ● 地址失效 404 (3)     ← 红色，永久类，右侧直接给「删除」
   ● 被拒 403 (1)         ← 紫色，右侧给「开启代理」
   ```
   hover 显示 `last_error` 完整原文。

2. **顶部筛选**：全部 / 正常 / 瞬时失败 / 永久失效 / 需干预。
   永久失效那一栏给「批量删除」。

3. **按上游 host 聚合的提示条**：当某个 host 下 ≥5 个源同时失败时，
   列表顶部出现一条橙色提示：

   ```
   ⚠ 上游 api.xgo.ing 当前不可用，影响 62 个源。这些源已跳过本轮抓取，
     不会被判定为失效。  [诊断该上游]  [暂停该上游全部源]
   ```

   这是本次事故最直接的可视化——一眼看出是一个上游挂了，不是 62 个源坏了。

4. **每行加「诊断」按钮**（`lucide:stethoscope`），点开弹窗显示 §2.6 的分步结果。

---

## 三、架构建议（本次可不实施，但要让问题可见）

**75% 的源依赖一个免费第三方代理，是这套系统当前最大的脆弱点。**
`api.xgo.ing` 一挂，你的「AI 工具链」主题就基本没有数据了，周报也就无米下锅。

三条路，按投入排序：

1. **让依赖可见**（本次做）：源管理页增加「按上游分组」视图，
   一眼看到 62/83 集中在一个 host。有了这个视图，才谈得上分散风险。
2. **自建 RSSHub**（推荐）：`docker run -d -p 1200:1200 diygod/rsshub`，
   然后把这 62 个源的 URL 从 `api.xgo.ing/...` 批量替换成 `localhost:1200/...`。
   路由规则大多兼容。批量替换可以做成源管理页的「批量替换 URL 前缀」功能。
3. **fallback 机制**：`adapter_params` 加 `fallback_url`，主 URL 失败时自动降级。
   实现成本最高，收益也最直接。

---

## 四、验收标准

- [ ] 断开本机网络后触发抓取 → 日志出现「本机网络不可用，跳过本轮」，
      **所有源的 `consecutive_failures` 不变**
- [ ] 模拟 `api.xgo.ing` 不可达（hosts 指向 127.0.0.1）→ 第 3 个源失败后触发熔断，
      剩余 59 个源被跳过且**几秒内结束**，不是逐个等超时
- [ ] 上述场景下这 62 个源的 `permanent_failures` 保持 0，
      **不出现在「失效源」列表里、不被自动关闭**
- [ ] 恢复网络后下一轮抓取自动成功，计数清零（自愈，无需人工干预）
- [ ] 对 `aiweirdness.com` 点「诊断」→ 六个步骤全绿，条目数 16
- [ ] 把某个源 URL 改成 `https://example.com/not-exist` → 诊断在 HTTP 步骤停下，
      标记 `http_404`，UI 显示「地址失效」并提供删除入口
- [ ] 源管理页在 `api.xgo.ing` 故障时显示聚合提示条，写明「影响 62 个源」
- [ ] 老库启动时自动补 `last_error_kind` / `transient_failures` /
      `permanent_failures` / `use_proxy` 四列（幂等 DDL，沿用 `core/database.py` 已有写法）

---

## 五、禁止事项

1. **不要因为失败就自动关闭源**。改成标记 + 用户确认。自动关闭一旦误判无法自愈，
   这正是本次事故会造成的后果。
2. **不要把所有失败一视同仁**。DNS 失败和 404 是完全不同的两件事，
   混在一起就没法治理 83 个源。
3. **不要在网络不可用时累加失败计数**。一次断网不该让全部源背锅。
4. **不要用 HTTP 请求做网络预检**，用 DNS 解析（`socket.getaddrinfo`），
   快且不依赖某个具体站点可达。
5. **不要给诊断接口加限频**。它是排障工具，要允许连续点。
6. **不要改抓取的业务逻辑**（去重、榜位、权重、规则匹配），本次只动网络层与状态判定。

---

## 六、建议的提交拆分

```
feat(hotlist): 抓取错误分类（last_error_kind）与瞬时/永久失败分流
fix(hotlist): 失效源判定改用 permanent_failures，避免上游故障误杀健康源
feat(hotlist): 上游主机熔断 + 批次前网络预检，断网与上游故障不再累加失败
feat(hotlist): requests 层加固（重试/连接池/分离超时/真实 UA/代理支持）
feat(hotlist): 单源分步诊断接口与源管理页错误类型可视化
```

---

## 附：立刻可做的临时处置（改代码之前）

在 §二 落地之前，先手动止损，避免那 62 个源被自动关掉：

```sql
-- 备份后执行：把上游故障造成的失败计数清零
UPDATE hot_sources SET consecutive_failures = 0, last_error = '', last_status = ''
WHERE adapter_params LIKE '%api.xgo.ing%';
```

并暂时**不要点「一键关闭失效源」**——现在点会一次性关掉 62 个健康的源。
