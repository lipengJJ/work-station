# 热点聚合模块修改任务书 · 第二批（交付给 DeepSeek 执行）

> 项目：`/Users/lipeng01/vscode/workbench`
> 后端 `backend/app/hotlist`，前端 `frontend/apps/web-antd/src/views/hotlist`
> 技术栈：FastAPI + SQLAlchemy 2.0 + SQLite（**无 Alembic**）/ Vue3 + Ant Design Vue（Vben Admin）
>
> 本批三项：**① 修复导入源不被调度的 BUG（最高优先级）② 手动抓取入口 ③ 全局过滤词换位置**

---

## 一、【BUG · 最高优先级】OPML 导入的源永远不会被抓取

### 1.1 现象

主题「AI 工具」下 81 个源全部显示「待抓取」、「近 7 天贡献 0 条」，
`hot_items` 里没有任何来自这些源的数据。

### 1.2 根因（已定位，勿再排查）

APScheduler 的 job 是**按源注册**的（`services/scheduler_jobs.py::register_job(source)`）。
注册时机目前只覆盖了单源操作：

```
controllers/sources.py:53   create_source  → scheduler_jobs.register_job(source)   ✅
controllers/sources.py:67   update_source  → scheduler_jobs.register_job(source)   ✅
controllers/sources.py:77   delete_source  → scheduler_jobs.unregister_job(id)     ✅
services/opml_service.py    批量导入        → ❌ 没有任何 register 调用
services/topic_service.py   attach_source / batch_set_sources / detach_source → ❌ 没有
```

`register_all_enabled_jobs()` 只在 `main.py` 的 lifespan 里跑一次。
所以 OPML 导入的源在**重启后端之前不会有任何 job**。

同理，`topic_service` 里改变「源是否被某个启用主题引用」的操作会改变
`pending_sources()` 的判定结果（源被调度的条件是「源自身 enabled 且被至少一个启用中的主题启用」），
但没有触发 job 的注册/注销，导致：
- 新勾选的源要等重启才开始抓
- 取消勾选的最后一个主题后，源的 job 还在继续跑

### 1.3 修复方案

**A. 新增全量对账函数** `services/scheduler_jobs.py`：

```python
def sync_jobs(db: Session) -> dict:
    """按当前数据库状态全量对账 source 级 job：该有的注册、不该有的注销。

    幂等，可随时调用。返回 {"registered": n, "unregistered": m, "total": k}。

    判定依据与 crawl_service 取待抓源的口径必须完全一致：
    源自身 enabled 且被至少一个启用中的主题启用（走 topic_service.pending_sources(db)）。
    """
    scheduler = get_scheduler()
    should_run = {s.id: s for s in topic_service.pending_sources(db)}
    existing = {
        job.id for job in scheduler.get_jobs()
        if job.id.startswith("hotlist_source_")     # 用实际的前缀常量，勿硬编码字符串
    }
    # 该有没有的 → register_job；不该有还在的 → unregister_job
```

> 用「全量对账」而不是在每个写入点手工 add/remove，是因为触发点太多
> （导入、关联、批量开关、主题启停、源启停），逐个补必然漏一个。
> 对账函数只有一处逻辑，且能自愈历史遗留的错误状态。

**B. 在这些写入点之后调用 `sync_jobs(db)`**（都在 commit 之后）：

| 文件 | 位置 |
|---|---|
| `services/opml_service.py` | `import_opml()` 返回前 |
| `services/topic_service.py` | `attach_source` / `detach_source` / `batch_set_sources` |
| `services/topic_service.py` | `disable_stale_sources` |
| `controllers/topics.py` | 主题启用/停用（`update_topic` 中 `enabled` 变化时） |
| `controllers/topics.py` | 主题删除 |
| `controllers/sources.py` | 批量启停 / 批量移动分组（若已实现） |

单源的 `create_source` / `update_source` / `delete_source` 保留现有的
`register_job` / `unregister_job` 调用即可，不必改成 `sync_jobs`（单源操作用不着全量扫）。

**C. 新增手动对账接口**（排障用）：

```
POST /api/hotlist/scheduler/sync     → 调 sync_jobs，返回统计
GET  /api/hotlist/scheduler/jobs     → 返回当前已注册的 job 列表
                                        [{source_id, source_name, cron, next_run_at}]
```

前端在「热点聚合 · 设置」页（见 §三）加一个「调度状态」区块：
显示已注册 job 数 / 应有源数，两者不一致时标红并给「立即对账」按钮。

### 1.4 验收

- [ ] 导入一个 OPML（不重启后端）→ `GET /api/hotlist/scheduler/jobs` 里立刻能看到新源的 job
- [ ] 主题详情里勾掉某个源 → 若它不再被任何启用主题引用，其 job 消失
- [ ] 停用整个主题 → 该主题独占的源 job 全部消失；被其他主题共享的源 job 保留
- [ ] 重启后端 → job 数量与重启前一致（对账口径与 lifespan 一致）

---

## 二、手动抓取入口

### 2.1 三个层级，两种执行方式

| 层级 | 位置 | 执行方式 | 限频 |
|---|---|---|---|
| **单个源** | 源管理页每行、主题详情「数据源」Tab 每行 | **同步**，直接返回结果 | 30 秒 / 源 |
| **本主题全部启用源** | 主题详情「数据源」Tab 工具栏 | **异步** + Task 进度 | 3 分钟 / 主题 |
| **全部源** | 榜单页（已存在） | 异步 + Task 进度 | 10 分钟（现状保留） |

**单源必须同步**。这是验证「这个 RSS 源到底能不能用」的核心场景，
一个源几秒就回来了，同步返回「成功 / 失败 + 抓到几条 + 具体错误」比
异步再去轮询体验好得多。你那 81 个源里必然有一批已失效，用户需要能逐个点开试。

**多源必须异步 + 有进度**。81 个源串行抓取（源间还有随机间隔）要好几分钟，
没有进度反馈用户会以为卡死。

### 2.2 后端改动

`services/crawl_service.py::run_crawl(db, source_ids, trigger)` 已支持按 `source_ids` 限定范围，
**不用改**。新增的是任务包装与进度上报。

**新增 `services/crawl_task_service.py`**：

```python
"""手动抓取的任务包装：落 Task 表 + 进度上报，复用工作台已有的任务中心。

不要另建一张任务表——common/models/task.py 的 Task 有 module/task_type/status/
params(JSON)/result_summary/started_at/finished_at，字段够用，且落进去之后
「任务中心」页面自动就能看到 hotlist 的抓取任务，不用改任务中心。
"""

def create_crawl_task(db, scope: str, topic_id: int | None,
                      source_ids: list[str], user_id: int | None) -> int:
    """建一条 Task(module="hotlist", task_type="hotlist_crawl", status="pending")，
    params 存 {"scope": "all|topic|source", "topic_id": ..., "source_ids": [...],
                "total": len(source_ids)}，返回 task_id。"""

def run_crawl_task(task_id: int) -> None:
    """daemon 线程执行体：自开自关 SessionLocal，逐源调 crawl_service，
    每完成一个源就更新 Task.result_summary 的进度 JSON：
        {"done": 12, "total": 81, "current": "Jina AI",
         "ok": 10, "failed": 2, "items": 137}
    异常整体兜底 → status="failed" + result_summary 记 error。"""
```

**Controller 新增**（`controllers/hotlist.py` 与 `controllers/topics.py`）：

```
POST /api/hotlist/sources/{source_id}/crawl
  同步执行单源抓取，30 秒限频（进程内 dict 记 source_id → 时间戳）
  返回 {ok, item_count, new_count, updated_count, error, elapsed_ms,
        last_status, consecutive_failures}
  ★ 失败时把 crawl_service 抓到的原始异常信息原样返回，别吞成"抓取失败"

POST /api/hotlist/topics/{topic_id}/crawl
  异步，范围 = 该主题 enabled 的源；3 分钟限频
  返回 {task_id, total}

GET  /api/hotlist/crawl-tasks/{task_id}
  返回 {status, done, total, current, ok, failed, items, error}
  供前端轮询（建议 2 秒一次）
```

限频命中时返回 **429** + `{"detail": "抓取过于频繁，请 N 秒后重试"}`，
与现有 `/api/hotlist/crawl` 的行为保持一致。

### 2.3 前端改动

**主题详情「数据源」Tab 工具栏**，在现有按钮（从分组关联 / 导入 OPML / 全开 / 全关 /
一键关闭失效源）后面加：

```
[⚡ 立即抓取本主题]    ← 主按钮样式，点击后变成进度条
```

点击后：调 `POST /topics/{id}/crawl` 拿 task_id → 每 2 秒轮询 →
按钮位置显示 `抓取中 12/81 · Jina AI` 的进度条 → 完成后弹出结果汇总
`成功 74 / 失败 7 / 新增条目 312`，并刷新源列表（健康状态和「近 7 天贡献」会变）。

**每行操作列**加一个「立即抓取」图标按钮（`lucide:refresh-cw`）：

点击 → loading → 同步返回后：
- 成功：行内 toast `抓到 23 条`，并就地刷新该行的健康状态与贡献数
- 失败：行内展开一条红色错误信息（**显示完整错误**，不要只写"失败"），
  并提供「关闭此源」快捷操作

> 源管理页（`views/hotlist/sources/index.vue`）每行也加同样的按钮，复用同一个接口。

**任务中心**（`views/task-center/index.vue`）：`module="hotlist"` 的任务会自动出现，
确认它能正确渲染 `result_summary` 里的进度 JSON；如果任务中心目前只按纯文本展示，
让它对 `task_type="hotlist_crawl"` 特殊渲染成进度描述即可，**不要改任务中心的表结构**。

### 2.4 验收

- [ ] 单个源点「立即抓取」→ 3~10 秒内返回结果，失败时显示完整错误信息
- [ ] 已失效的 RSS 源点抓取 → 明确告知失败原因（超时 / 404 / 解析失败），
      而不是笼统的"抓取失败"
- [ ] 主题「立即抓取本主题」→ 进度条逐步推进，能看到当前正在抓哪个源
- [ ] 抓取完成后源列表的「健康状态」和「近 7 天贡献」立即刷新
- [ ] 同一个源 30 秒内二次点击 → 429 且提示剩余秒数
- [ ] 抓取任务在「任务中心」可见，状态与进度正确

---

## 三、全局过滤词换位置 → 新建「热点聚合 · 设置」页

### 3.1 为什么不放系统设置

`views/settings/system/index.vue` 现在是 **AI 模型配置 + 消息通知 + 数据处理模型**，
定位是**跨模块的基础设施配置**。全局过滤词是 hotlist 的业务配置，放进去会稀释系统设置的定位，
而且用户在配 hotlist 的时候要跳到另一个模块去找，链路是断的。

放在「主题订阅」页顶部同样不合适：它是**低频配置**（配一次半年不动），
却占据了**高频页面**的头部黄金位置，还打断了「主题卡片列表」这个页面主体。

### 3.2 方案：新建模块级设置页

新增路由与页面：

```
router/routes/modules/hotlist.ts  →  children 末尾追加
{
  name: 'HotlistSettings',
  path: 'settings',
  component: () => import('#/views/hotlist/settings/index.vue'),
  meta: { title: '设置' },
}
```

侧边栏顺序：榜单 / 摘要 / 源管理 / 主题订阅 / **设置**（放最后）。

页面分区块（`a-card` 或现有的分区组件，风格对齐 `views/settings/system/index.vue`）：

| 区块 | 内容 | 存哪 |
|---|---|---|
| **全局过滤词** | 标签式增删，命中即从所有主题的结果中剔除 | `hot_keyword_rules`（`rule_type='global_filter'`，`topic_id=NULL`），沿用现有接口 |
| **调度状态** | 已注册 job 数 / 应有源数 + 「立即对账」按钮（见 §1.3C） | 实时查询 |
| **权重系数** | rank / frequency / hotness 三个滑块，和为 1 时给绿色提示 | `ApiConfig`：`hotlist_rank_weight` / `hotlist_frequency_weight` / `hotlist_hotness_weight` |
| **数据源接口** | NewsNow API 地址（留空用默认公共实例） | `ApiConfig`：`hotlist_newsnow_api_url` |
| **数据保留** | 条目保留天数、单源最大条目数、「立即清理」按钮 | `ApiConfig`：`hotlist_retention_days` |
| **报告发布** | S3 兼容对象存储：endpoint / region / bucket / AK / SK / 公开访问前缀 + 「测试连接」 | `ApiConfig`：`hotlist_s3_*` |

> 这几项现在要么埋在代码常量里、要么在 `ApiConfig` 里没有 UI。收在一处之后，
> hotlist 的所有模块级配置在模块内就能找全，全局过滤词只是其中一个区块，不再突兀。

**从主题订阅页移除**：删掉 `views/hotlist/topics/index.vue` 顶部的
「全局过滤词（对所有主题生效）」折叠区块。在页面副标题处加一行浅色提示 +
跳转链接：`全局过滤词已移至 [设置]`，保留一个版本方便你自己适应，之后可删。

**后端**：全局过滤词接口保持 `/api/hotlist/global-filters`（GET/POST/DELETE）不变。
新增设置读写接口：

```
GET  /api/hotlist/settings          → 返回上表所有配置项（S3 的 secret_key 脱敏成 ****）
PUT  /api/hotlist/settings          → 批量更新（只更新传了的字段）
POST /api/hotlist/settings/s3-test  → 测试对象存储连通性（尝试 put 一个探针对象再删除）
```

配置值统一走 `ApiConfig` 表（`app/common/models/api_config.py`，字段是 `name` / `value`），
与现有 API 配置的读写方式保持一致。

### 3.3 验收

- [ ] 侧边栏「热点聚合」下出现「设置」，六个区块齐全
- [ ] 全局过滤词在设置页可增删，改动后对所有主题的匹配立即生效
- [ ] 主题订阅页顶部不再有全局过滤词区块
- [ ] 权重系数改动后，重新抓取的条目 `weight` 按新系数计算
- [ ] S3「测试连接」能正确区分「配置错误」「网络不通」「权限不足」三类失败
- [ ] 调度状态区块在 job 数与源数不一致时标红，点「立即对账」后恢复一致

---

## 四、禁止事项

1. **不要另建任务表**。手动抓取任务用 `common/models/task.py` 的 `Task`，
   `module="hotlist"`，这样任务中心自动可见。
2. **不要把单源抓取也做成异步**。同步返回是这个功能的价值所在。
3. **不要吞掉抓取错误**。失败时把 adapter 抛出的原始信息返回给前端——
   用户要靠它判断是源挂了还是网络问题。
4. **不要在每个写入点手工 add/remove job**。用 §1.3 的 `sync_jobs` 全量对账，
   触发点太多，逐个补必然漏。
5. **不要把 hotlist 的业务配置塞进「系统设置」页**。系统设置的定位是跨模块基础设施。
6. **不要改任务中心的表结构或路由**，只在渲染层对 `hotlist_crawl` 做适配。

---

## 五、建议的提交拆分

```
fix(hotlist): OPML 导入与主题源关联后未注册调度 job，新增 sync_jobs 全量对账
feat(hotlist): 手动抓取——单源同步验证 + 主题级异步任务与进度
feat(hotlist): 新增模块设置页，全局过滤词/权重系数/发布配置/调度状态归位
```

---

## 附：执行顺序建议

先做 §一（BUG 修复），做完立刻在页面上点一次「立即对账」，
再手动抓一个源验证链路通不通——**这两步没过之前不要动 §二、§三**，
否则会在一个「源根本不会被抓」的系统上调试上层功能，浪费时间。
