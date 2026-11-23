from __future__ import annotations

from collections.abc import Generator

from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args)

if settings.database_url.startswith("sqlite"):
    # SQLite 默认关闭外键约束；语义检索的向量表/命中表/召回快照表依赖 ON DELETE CASCADE，
    # 必须统一开启（SQLAlchemy 不会自动开启）。
    # 另外几个业务场景会有多个线程各自开独立连接并发写同一个 SQLite 文件（如主题报告
    # L2 全文抓取的 ThreadPoolExecutor），默认 rollback journal 模式下同一时刻只允许
    # 一个写者，容易在竞争下报 "database is locked"；开 WAL 让一个写者和多个读者可以
    # 并发进行，busy_timeout 兜底真正撞上写写竞争时等待重试而不是立刻报错。
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 进程内只做一次老库检查（避免每次请求都 inspect 一遍表结构）
_schema_checked = False


def _ensure_notification_config_schema() -> None:
    """
    轻量老库兼容（无 Alembic，create_all 只建新表不 ALTER 已有表）：
    1. notification_config 补 sendkey / token 列（已有列跳过）；
    2. channel 列补唯一索引（多通道化：每通道一行）。
    任何异常只记日志，绝不让老库在启动/seed 时炸掉；进程内只检查一次，幂等。
    """
    global _schema_checked
    if _schema_checked:
        return
    _schema_checked = True
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if "notification_config" not in inspector.get_table_names():
            return
        columns = {c["name"] for c in inspector.get_columns("notification_config")}
        with engine.begin() as conn:
            # SQLite 允许带 DEFAULT 的 ADD COLUMN；不声明 NOT NULL，兼容已有行的 NULL 值
            if "sendkey" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE notification_config "
                        "ADD COLUMN sendkey VARCHAR(256) DEFAULT ''"
                    )
                )
                logger.warning("notification_config 表已补充 sendkey 列（Server酱 通道）")
            if "token" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE notification_config "
                        "ADD COLUMN token VARCHAR(256) DEFAULT ''"
                    )
                )
                logger.warning("notification_config 表已补充 token 列（PushPlus 预留通道）")
            if "smtp_host" not in columns:
                conn.execute(text("ALTER TABLE notification_config ADD COLUMN smtp_host VARCHAR(255) DEFAULT ''"))
                conn.execute(text("ALTER TABLE notification_config ADD COLUMN smtp_port INTEGER DEFAULT 465"))
                conn.execute(text("ALTER TABLE notification_config ADD COLUMN smtp_user VARCHAR(255) DEFAULT ''"))
                conn.execute(text("ALTER TABLE notification_config ADD COLUMN smtp_password VARCHAR(255) DEFAULT ''"))
                conn.execute(text("ALTER TABLE notification_config ADD COLUMN smtp_use_ssl BOOLEAN DEFAULT 1"))
                conn.execute(text("ALTER TABLE notification_config ADD COLUMN email_to VARCHAR(512) DEFAULT ''"))
                logger.warning("notification_config 表已补充 email 通道相关列（SMTP）")
        # 多实例化：移除 channel 唯一索引（同类型可配多个实例）；老库补 remark 列；
        # SQLite 老表内嵌 UNIQUE 约束生成的 autoindex 无法 DROP，只能重建表移除。
        with engine.begin() as conn:
            index_names = {ix["name"] for ix in inspector.get_indexes("notification_config")}
            if "ix_notification_config_channel" in index_names:
                conn.execute(text("DROP INDEX ix_notification_config_channel"))
                logger.warning("notification_config 表已移除 channel 唯一索引（多实例化）")
            if "remark" not in columns:
                conn.execute(
                    text("ALTER TABLE notification_config ADD COLUMN remark VARCHAR(64) DEFAULT ''")
                )
                logger.warning("notification_config 表已补充 remark 列（多实例备注名）")
            auto_rows = conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='index' "
                    "AND tbl_name='notification_config' AND name LIKE 'sqlite_autoindex%'"
                )
            ).fetchall()
            if auto_rows:
                # 这个重建分支只在「从没跑过多实例化迁移」的老库上触发；此时上面几步已经把
                # email 相关列加上了，这里的列表必须跟着补，否则重建完这些列就白加了。
                conn.execute(
                    text(
                        "CREATE TABLE notification_config_new ("
                        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                        "channel VARCHAR(32) NOT NULL DEFAULT 'wecom_webhook', "
                        "remark VARCHAR(64) DEFAULT '', "
                        "webhook_url VARCHAR(512) DEFAULT '', "
                        "sendkey VARCHAR(256) DEFAULT '', "
                        "token VARCHAR(256) DEFAULT '', "
                        "enabled BOOLEAN DEFAULT 0, "
                        "mention_all BOOLEAN DEFAULT 0, "
                        "smtp_host VARCHAR(255) DEFAULT '', "
                        "smtp_port INTEGER DEFAULT 465, "
                        "smtp_user VARCHAR(255) DEFAULT '', "
                        "smtp_password VARCHAR(255) DEFAULT '', "
                        "smtp_use_ssl BOOLEAN DEFAULT 1, "
                        "email_to VARCHAR(512) DEFAULT '', "
                        "created_at DATETIME, "
                        "updated_at DATETIME)"
                    )
                )
                conn.execute(
                    text(
                        "INSERT INTO notification_config_new (id, channel, remark, webhook_url, "
                        "sendkey, token, enabled, mention_all, smtp_host, smtp_port, smtp_user, "
                        "smtp_password, smtp_use_ssl, email_to, created_at, updated_at) "
                        "SELECT id, channel, COALESCE(remark, ''), webhook_url, sendkey, token, "
                        "enabled, mention_all, COALESCE(smtp_host, ''), COALESCE(smtp_port, 465), "
                        "COALESCE(smtp_user, ''), COALESCE(smtp_password, ''), COALESCE(smtp_use_ssl, 1), "
                        "COALESCE(email_to, ''), created_at, updated_at FROM notification_config"
                    )
                )
                conn.execute(text("DROP TABLE notification_config"))
                conn.execute(text("ALTER TABLE notification_config_new RENAME TO notification_config"))
                logger.warning("notification_config 表已重建（移除 channel 唯一约束，支持多实例）")

    except Exception:
        logger.exception("检查/补充 notification_config 表结构失败，部分通知通道可能不可用")


def _ensure_tracking_ai_schema() -> None:
    """追踪任务 AI 筛选相关列（任务表 3 列 + 命中表 6 列，幂等）。"""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        task_adds = {
            "ai_filter_enabled": "BOOLEAN DEFAULT 0",
            "ai_filter_prompt": "TEXT",
            "ai_filter_min_confidence": "FLOAT DEFAULT 0.6",
        }
        hit_adds = {
            "ai_process_status": "VARCHAR(16) DEFAULT 'pending'",
            "ai_structured_data": "TEXT",
            "ai_is_match": "BOOLEAN",
            "ai_match_reason": "TEXT",
            "ai_confidence": "FLOAT",
            "ai_raw_response": "TEXT",
        }
        with engine.begin() as conn:
            if "xhs_tracking_tasks" in inspector.get_table_names():
                cols = {c["name"] for c in inspector.get_columns("xhs_tracking_tasks")}
                for name, ddl in task_adds.items():
                    if name not in cols:
                        conn.execute(text(f"ALTER TABLE xhs_tracking_tasks ADD COLUMN {name} {ddl}"))
            if "xhs_tracking_hits" in inspector.get_table_names():
                cols2 = {c["name"] for c in inspector.get_columns("xhs_tracking_hits")}
                for name, ddl in hit_adds.items():
                    if name not in cols2:
                        conn.execute(text(f"ALTER TABLE xhs_tracking_hits ADD COLUMN {name} {ddl}"))
        logger.warning("追踪任务 AI 筛选相关列已补充")
    except Exception:
        logger.exception("补充追踪任务 AI 筛选列失败")


def _ensure_tracking_task_notify_schema() -> None:
    """追踪任务表补机器人通知相关列（幂等，老库兼容）。"""
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if "xhs_tracking_tasks" not in inspector.get_table_names():
            return
        columns = {c["name"] for c in inspector.get_columns("xhs_tracking_tasks")}
        adds = {
            "notify_enabled": "BOOLEAN DEFAULT 0",
            "notify_channel_ids": "TEXT DEFAULT '[]'",
            "notify_time_start": "VARCHAR(8)",
            "notify_time_end": "VARCHAR(8)",
            "notify_frequency": "VARCHAR(16) DEFAULT 'realtime'",
            "notify_only_on_hit": "BOOLEAN DEFAULT 1",
            "notify_pending_hits": "INTEGER DEFAULT 0",
            "notify_pending_since": "DATETIME",
        }
        with engine.begin() as conn:
            for name, ddl in adds.items():
                if name not in columns:
                    conn.execute(text(f"ALTER TABLE xhs_tracking_tasks ADD COLUMN {name} {ddl}"))
        logger.warning("xhs_tracking_tasks 表已补充机器人通知相关列")
    except Exception:
        logger.exception("补充 xhs_tracking_tasks 通知列失败")


def _ensure_hotlist_source_health_schema() -> None:
    """hot_sources 补失败分类三列（幂等，老库兼容）。

    背景：原来所有失败都只累加 consecutive_failures，而失效判定又只看它——
    一次本机 DNS 抖动或一个上游挂掉，就能把几十个完全健康的源判成失效并自动关闭，
    关掉之后不再抓取、无法自愈。分成 transient / permanent 两个计数后，
    失效判定只看 permanent_failures。
    """
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if "hot_sources" not in inspector.get_table_names():
            return
        columns = {c["name"] for c in inspector.get_columns("hot_sources")}
        adds = {
            "last_error_kind": "VARCHAR(24) DEFAULT ''",
            "transient_failures": "INTEGER DEFAULT 0",
            "permanent_failures": "INTEGER DEFAULT 0",
        }
        missing = {k: v for k, v in adds.items() if k not in columns}
        if not missing:
            return
        with engine.begin() as conn:
            for name, ddl in missing.items():
                conn.execute(
                    text(f"ALTER TABLE hot_sources ADD COLUMN {name} {ddl}")
                )
        logger.warning(f"hot_sources 表已补充失败分类列：{', '.join(missing)}")
    except Exception:
        logger.exception("补充 hot_sources 失败分类列失败")


def _fix_opml_expected_domain() -> None:
    """清掉 OPML 导入的 RSS 源上「等于 feed 自身域名」的 expected_domain（幂等）。

    域名安全校验的本意是防公共聚合接口（NewsNow 实例）被篡改后返回钓鱼链接；
    但 OPML 导入曾把 expected_domain 设成 feed 自己的域名，而转发型 feed
    （如 api.xgo.ing 的条目指向 x.com）跨域是完全正常的，结果整源被误杀。
    只清「expected_domain == feed URL 的 host」这一种情况，用户手工填的不动；
    清完就不再匹配，所以每次启动跑一遍也没有副作用。
    """
    try:
        import json
        from urllib.parse import urlsplit

        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if "hot_sources" not in inspector.get_table_names():
            return
        with engine.begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, adapter_params, expected_domain FROM hot_sources "
                    "WHERE adapter = 'rss' AND id LIKE 'rss-%' "
                    "AND expected_domain != ''"
                )
            ).fetchall()
            fixed = 0
            for source_id, params_json, expected in rows:
                try:
                    url = json.loads(params_json or "{}").get("url", "")
                    host = (urlsplit(url).hostname or "").lower()
                except (ValueError, AttributeError):
                    continue
                if not host or host != (expected or "").strip().lower():
                    continue  # 用户手工填的别的域名，不动
                conn.execute(
                    text(
                        "UPDATE hot_sources SET expected_domain = '' WHERE id = :i"
                    ),
                    {"i": source_id},
                )
                fixed += 1
        if fixed:
            logger.warning(
                f"已清理 {fixed} 个 OPML 导入源的 expected_domain"
                "（按 feed 域名校验会误杀转发型 feed 的跨域条目）"
            )
    except Exception:
        logger.exception("清理 OPML 源 expected_domain 失败")


def _ensure_hotlist_semantic_schema() -> None:
    """hotlist 语义检索：hot_topics 补兴趣查询四列（幂等，老库兼容）。

    create_all 只建缺失的表，不会给已有表加列；HotTopic ORM 新增的
    interest_query / retrieval_mode / similarity_threshold / retrieval_size
    必须靠这里 ALTER TABLE 补上，否则老库上任何走 ORM 的读写都会报
    「no such column」。与 _ensure_tracking_ai_schema 同一套 inspect → 缺列才 ALTER 写法。
    """
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if "hot_topics" not in inspector.get_table_names():
            return
        cols = {c["name"] for c in inspector.get_columns("hot_topics")}
        adds = {
            "interest_query": "TEXT",
            "retrieval_mode": "VARCHAR(16) DEFAULT 'semantic'",
            "similarity_threshold": "FLOAT DEFAULT 0.35",
            "retrieval_size": "INTEGER DEFAULT 100",
        }
        missing = {name: ddl for name, ddl in adds.items() if name not in cols}
        if not missing:
            return
        with engine.begin() as conn:
            for name, ddl in missing.items():
                conn.execute(text(f"ALTER TABLE hot_topics ADD COLUMN {name} {ddl}"))
        logger.warning(
            f"hotlist 语义检索列已补充: {', '.join(sorted(missing))}"
        )
    except Exception:
        logger.exception("补充 hotlist 语义检索列失败")


def _ensure_hotlist_topic_setup_schema() -> None:
    """hot_topics 补 setup_done 列（幂等，老库兼容，默认 1）。

    创建向导拆成三步后，用它区分「草稿（向导没走完）」和「配好了手动停用」——
    两者都是 enabled=False，不加这列就分不开。老库既有主题一律按默认值 1
    视为已配置完成，不会被误判成草稿。
    """
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if "hot_topics" not in inspector.get_table_names():
            return
        cols = {c["name"] for c in inspector.get_columns("hot_topics")}
        if "setup_done" in cols:
            return
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE hot_topics ADD COLUMN setup_done BOOLEAN DEFAULT 1"
                )
            )
        logger.warning("hot_topics 表已补充 setup_done 列（默认 1）")
    except Exception:
        logger.exception("补充 hot_topics setup_done 列失败")


def _ensure_hotlist_embedding_nullable() -> None:
    """两向量表 vector 列从 NOT NULL 改 nullable（SQLite 无 ALTER COLUMN：DROP 后由
    create_all 重建，init_db 里紧随其后会再跑一次 create_all）。

    原 NOT NULL 约束导致嵌入失败（status='failed'）时写 NULL 记录错误被拒
    （IntegrityError: NOT NULL constraint failed: hot_topic_embeddings.vector）。
    当前表内没有成功数据（此前维度不匹配从未写入成功），直接重建无损失；
    若将来表内有数据需要保留，应改为「建新表 + INSERT SELECT + 换名」流程。
    """
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        names = set(inspector.get_table_names())
        rebuilt = []
        for table, vec_col in (
            ("hot_topic_embeddings", "vector"),
            ("hot_item_embeddings", "vector"),
        ):
            if table not in names:
                continue
            cols = {c["name"]: c for c in inspector.get_columns(table)}
            if cols.get(vec_col) and not cols[vec_col]["nullable"]:
                with engine.begin() as conn:
                    conn.execute(text(f"DROP TABLE {table}"))
                rebuilt.append(table)
        if rebuilt:
            logger.warning(
                f"向量表已重建（vector 列改 nullable）: {', '.join(rebuilt)}"
            )
    except Exception:
        logger.exception("重建向量表 vector 可空失败")


def _ensure_hotlist_source_group_crawl_schema() -> None:
    """hot_source_groups 补 crawl_enabled 列（幂等，老库兼容）。

    存量分组（迁移这一刻已存在的）一律种成 True——它们当下就在自动抓取，
    不能因为加了这个开关就让正在跑的抓取静默停掉；新建分组走模型默认值 False。
    """
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if "hot_source_groups" not in inspector.get_table_names():
            return
        cols = {c["name"] for c in inspector.get_columns("hot_source_groups")}
        if "crawl_enabled" in cols:
            return
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE hot_source_groups ADD COLUMN crawl_enabled BOOLEAN DEFAULT 0"
                )
            )
            conn.execute(text("UPDATE hot_source_groups SET crawl_enabled = 1"))
        logger.warning(
            "hot_source_groups 表已补充 crawl_enabled 列，存量分组默认开启资讯爬取"
        )
    except Exception:
        logger.exception("补充 hot_source_groups crawl_enabled 列失败")


def _ensure_hotlist_source_kind_dropped() -> None:
    """hot_sources 表去掉 source_kind 列（幂等，老库兼容）。

    分组织归属已经统一走 group_id（hot_source_groups），source_kind 这套
    「中文热榜/技术源」独立分类标签和分组是同一个用途的两套并行机制，前端
    「类型：全部/中文热榜/技术源」筛选跟分组筛选完全重复，下掉其中一套。
    需要 SQLite 3.35+（DROP COLUMN），本机/生产都已满足。
    """
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if "hot_sources" not in inspector.get_table_names():
            return
        cols = {c["name"] for c in inspector.get_columns("hot_sources")}
        if "source_kind" not in cols:
            return
        with engine.begin() as conn:
            # 列原来带 index=True，DROP COLUMN 前必须先手动摘掉索引，否则 SQLite
            # 报 "error in index ... after drop column"（索引不会跟着列自动清）。
            conn.execute(text("DROP INDEX IF EXISTS ix_hot_sources_source_kind"))
            conn.execute(text("ALTER TABLE hot_sources DROP COLUMN source_kind"))
        logger.warning("hot_sources 表已去掉 source_kind 列（并入 group_id 分组）")
    except Exception:
        logger.exception("去掉 hot_sources source_kind 列失败")


def _ensure_hotlist_source_interval_schema() -> None:
    """hot_sources 的 cron_expr（cron 表达式）换成 interval_hours（抓取间隔小时数）（幂等，老库兼容）。

    cron 定点触发在休眠/重启频繁的机器上一碰到 misfire 容忍窗口就被跳过、且用户
    还得会填 cron 表达式；换成 IntervalTrigger 后不需要用户理解 cron 语法，调度器
    自己按「距上次触发过了多久」判断，不依赖命中某个精确时间点（见 scheduler_jobs）。
    老库里 cron_expr 的值尽量解析出等价的小时数迁过去，解析不出的退回默认 4 小时
    （对齐 opml_service.RSS_FETCH_INTERVAL_HOURS，多数源原本就是这个频率）。
    """
    import re

    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if "hot_sources" not in inspector.get_table_names():
            return
        cols = {c["name"] for c in inspector.get_columns("hot_sources")}
        if "cron_expr" not in cols:
            return  # 已经迁过了

        if "interval_hours" not in cols:
            with engine.begin() as conn:
                conn.execute(
                    text("ALTER TABLE hot_sources ADD COLUMN interval_hours REAL DEFAULT 0.5")
                )

        with engine.begin() as conn:
            rows = conn.execute(text("SELECT id, cron_expr FROM hot_sources")).fetchall()
            for row_id, cron_expr in rows:
                hours = 4.0
                expr = (cron_expr or "").strip()
                m = re.match(r"^\*/(\d+) \* \* \* \*$", expr)
                if m:
                    hours = int(m.group(1)) / 60
                else:
                    m = re.match(r"^0 \*/(\d+) \* \* \*$", expr)
                    if m:
                        hours = float(int(m.group(1)))
                conn.execute(
                    text("UPDATE hot_sources SET interval_hours = :hours WHERE id = :id"),
                    {"hours": hours, "id": row_id},
                )
            # 索引不会跟着列自动清，DROP COLUMN 前先摘掉（同 _ensure_hotlist_source_kind_dropped）
            conn.execute(text("DROP INDEX IF EXISTS ix_hot_sources_cron_expr"))
            conn.execute(text("ALTER TABLE hot_sources DROP COLUMN cron_expr"))
        logger.warning(f"hot_sources 表已将 cron_expr 迁移为 interval_hours（{len(rows)} 行）")
    except Exception:
        logger.exception("迁移 hot_sources cron_expr → interval_hours 失败")


def init_db() -> None:
    # noqa: F401  各域的 models 子包只是被 import 一下确保类注册到 Base.metadata 上，
    # 不在这里直接用——按域拆分后模型定义各自归属 common/stock/xhs，不再有一个统一的
    # app.models 聚合包
    from app.analysis import models as analysis_models  # noqa: F401
    from app.hotlist import models as hotlist_models  # noqa: F401
    from app.common import models as common_models  # noqa: F401
    from app.resource import models as resource_models  # noqa: F401
    from app.skills import models as skills_models  # noqa: F401
    from app.stock import models as stock_models  # noqa: F401
    from app.xhs import models as xhs_models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    # 老库兼容：通知配置补列（sendkey/token）+ channel 唯一索引（多通道化）
    _ensure_notification_config_schema()
    _ensure_tracking_task_notify_schema()
    _ensure_tracking_ai_schema()
    # hotlist 源健康状态：失败分类三列（老库幂等迁移）
    _ensure_hotlist_source_health_schema()
    # hotlist 语义检索：hot_topics 兴趣查询四列（老库幂等迁移）
    _ensure_hotlist_semantic_schema()
    # hotlist 创建向导：hot_topics 补 setup_done 列（老库幂等迁移）
    _ensure_hotlist_topic_setup_schema()
    # hotlist 语义检索：向量表 vector 列改 nullable（可能 DROP 表，之后需重建）
    _ensure_hotlist_embedding_nullable()
    # hotlist 分组资讯爬取开关：hot_source_groups 补 crawl_enabled 列（老库幂等迁移）
    _ensure_hotlist_source_group_crawl_schema()
    # hotlist 源类型标签下线：hot_sources 去掉 source_kind 列（并入 group_id 分组）
    _ensure_hotlist_source_kind_dropped()
    # hotlist 抓取调度简化：hot_sources cron_expr → interval_hours（老库幂等迁移）
    _ensure_hotlist_source_interval_schema()
    Base.metadata.create_all(bind=engine)
    _fix_opml_expected_domain()
