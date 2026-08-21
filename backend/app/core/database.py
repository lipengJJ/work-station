from __future__ import annotations

from collections.abc import Generator

from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args)
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


def _ensure_hotlist_topic_rule_schema() -> None:
    """hotlist 规则归属主题 + 源分组 + 推送配置拆分（幂等，老库兼容）。

    与 _ensure_tracking_ai_schema 同一套写法：inspect 列集合 → 缺列才 ALTER，
    每一步独立 try/except，任何异常只记日志，绝不让老库在启动时炸掉。
    分四个阶段：
      1. 加列（hot_keyword_rules.topic_id / hot_sources.group_id / hot_topics 推送两组 12 列）
      2. 搬数据：hot_topics 老 notify_* → report_notify_*（仅当 report_notify_channel_ids 为空）
      3. 收编无主规则：rule_type='group' AND topic_id IS NULL → 主题「默认主题」(slug='default')
      4. 存量源归入内置分组（中文热榜 / 技术社区）
    """
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())

        # ---- 阶段 1：加列（已存在跳过）----
        try:
            with engine.begin() as conn:
                if "hot_keyword_rules" in table_names:
                    cols = {c["name"] for c in inspector.get_columns("hot_keyword_rules")}
                    if "topic_id" not in cols:
                        conn.execute(text("ALTER TABLE hot_keyword_rules ADD COLUMN topic_id INTEGER"))
                if "hot_sources" in table_names:
                    cols = {c["name"] for c in inspector.get_columns("hot_sources")}
                    if "group_id" not in cols:
                        conn.execute(text("ALTER TABLE hot_sources ADD COLUMN group_id INTEGER"))
                if "hot_topics" in table_names:
                    cols = {c["name"] for c in inspector.get_columns("hot_topics")}
                    topic_adds = {
                        "report_notify_enabled": "BOOLEAN DEFAULT 0",
                        "report_notify_channel_ids": "TEXT DEFAULT '[]'",
                        "report_notify_time_start": "VARCHAR(8)",
                        "report_notify_time_end": "VARCHAR(8)",
                        "hit_notify_enabled": "BOOLEAN DEFAULT 0",
                        "hit_notify_channel_ids": "TEXT DEFAULT '[]'",
                        "hit_notify_time_start": "VARCHAR(8)",
                        "hit_notify_time_end": "VARCHAR(8)",
                        "hit_notify_frequency": "VARCHAR(16) DEFAULT 'realtime'",
                        "hit_notify_only_on_hit": "BOOLEAN DEFAULT 1",
                        "hit_notify_pending_hits": "INTEGER DEFAULT 0",
                        "hit_notify_pending_since": "DATETIME",
                    }
                    for name, ddl in topic_adds.items():
                        if name not in cols:
                            conn.execute(text(f"ALTER TABLE hot_topics ADD COLUMN {name} {ddl}"))
            logger.warning("hotlist 主题规则/源分组/推送配置列已补充")
        except Exception:
            logger.exception("补充 hotlist 主题规则/源分组/推送配置列失败")

        # ---- 阶段 2：搬数据（老 notify_* → report_notify_*）----
        try:
            if "hot_topics" in table_names:
                topic_cols = {c["name"] for c in inspector.get_columns("hot_topics")}
                # 老 notify_* 列只存在于老库；新库没有这几列，UPDATE 引用会报错，必须先判存在
                if "notify_enabled" in topic_cols and "report_notify_channel_ids" in topic_cols:
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "UPDATE hot_topics SET "
                                "report_notify_enabled=notify_enabled, "
                                "report_notify_channel_ids=notify_channel_ids, "
                                "report_notify_time_start=notify_time_start, "
                                "report_notify_time_end=notify_time_end "
                                "WHERE report_notify_channel_ids IS NULL "
                                "OR report_notify_channel_ids='' "
                                "OR report_notify_channel_ids='[]'"
                            )
                        )
                    logger.warning("hotlist 迁移：hot_topics 老 notify_* 已搬到 report_notify_*")
        except Exception:
            logger.exception("hotlist 迁移：hot_topics 报告推送数据搬运失败")

        # ---- 阶段 2.5：重建 hot_topics，去掉改名前的老 notify_enabled / notify_channel_ids ----
        # 这两列建表时是 NOT NULL 且没有 DB 端 DEFAULT（当年 ORM 的 default= 只在走 ORM
        # insert 时生效，不是 DB schema 里的 DEFAULT）。阶段 2 把数据搬到 report_notify_*
        # 之后这两列就是死列，但 NOT NULL 约束还在——现在的 ORM 模型已经不再声明这两个
        # 字段，所以任何走 ORM 的 INSERT INTO hot_topics（比如新建主题）都不会带这两列的
        # 值，会被 SQLite 的 NOT NULL 约束直接拒绝。SQLite 不支持 ALTER COLUMN，只能重建表；
        # 这里没有别的路可走，且本表没有任何外键引用（hot_topic_sources / hot_keyword_rules /
        # hot_topic_reports 的 topic_id 都是普通 Integer 列，不是 ForeignKey），重建安全。
        # 写法与 _ensure_notification_config_schema 里的表重建一致。
        try:
            if "hot_topics" in table_names:
                cols_now = {c["name"] for c in inspector.get_columns("hot_topics")}
                if "notify_enabled" in cols_now:
                    keep = [
                        "id", "name", "slug", "description", "enabled", "sort_order",
                        "skill_key", "template_key", "extra_question", "digest_strategy",
                        "digest_period", "digest_cron", "max_items", "shortlist_size",
                        "fulltext_size", "compare_with_previous", "publish_enabled",
                        "publish_formats", "created_at", "updated_at",
                        "report_notify_enabled", "report_notify_channel_ids",
                        "report_notify_time_start", "report_notify_time_end",
                        "hit_notify_enabled", "hit_notify_channel_ids",
                        "hit_notify_time_start", "hit_notify_time_end",
                        "hit_notify_frequency", "hit_notify_only_on_hit",
                        "hit_notify_pending_hits", "hit_notify_pending_since",
                    ]
                    keep = [c for c in keep if c in cols_now]  # 兼容比这更老、还没补齐推送列的库
                    col_list = ", ".join(keep)
                    with engine.begin() as conn:
                        conn.execute(
                            text(
                                "CREATE TABLE hot_topics_new ("
                                "id INTEGER NOT NULL, name VARCHAR(64) NOT NULL, "
                                "slug VARCHAR(64) NOT NULL, description TEXT NOT NULL, "
                                "enabled BOOLEAN NOT NULL, sort_order INTEGER NOT NULL, "
                                "skill_key VARCHAR(64) NOT NULL, template_key VARCHAR(64), "
                                "extra_question TEXT NOT NULL, digest_strategy VARCHAR(16) NOT NULL, "
                                "digest_period VARCHAR(16) NOT NULL, digest_cron VARCHAR(64) NOT NULL, "
                                "max_items INTEGER NOT NULL, shortlist_size INTEGER NOT NULL, "
                                "fulltext_size INTEGER NOT NULL, compare_with_previous BOOLEAN NOT NULL, "
                                "publish_enabled BOOLEAN NOT NULL, publish_formats VARCHAR(64) NOT NULL, "
                                "created_at DATETIME, updated_at DATETIME, "
                                "report_notify_enabled BOOLEAN DEFAULT 0, "
                                "report_notify_channel_ids TEXT DEFAULT '[]', "
                                "report_notify_time_start VARCHAR(8), report_notify_time_end VARCHAR(8), "
                                "hit_notify_enabled BOOLEAN DEFAULT 0, "
                                "hit_notify_channel_ids TEXT DEFAULT '[]', "
                                "hit_notify_time_start VARCHAR(8), hit_notify_time_end VARCHAR(8), "
                                "hit_notify_frequency VARCHAR(16) DEFAULT 'realtime', "
                                "hit_notify_only_on_hit BOOLEAN DEFAULT 1, "
                                "hit_notify_pending_hits INTEGER DEFAULT 0, "
                                "hit_notify_pending_since DATETIME, "
                                "PRIMARY KEY (id), UNIQUE (slug))"
                            )
                        )
                        conn.execute(
                            text(
                                f"INSERT INTO hot_topics_new ({col_list}) "
                                f"SELECT {col_list} FROM hot_topics"
                            )
                        )
                        conn.execute(text("DROP TABLE hot_topics"))
                        conn.execute(text("ALTER TABLE hot_topics_new RENAME TO hot_topics"))
                    logger.warning("hotlist 迁移：hot_topics 已重建，去掉改名前的老 notify_enabled/notify_channel_ids 死列")
                    # 表重建后 inspector 缓存的列信息已经过期，后面阶段要用的地方重新查
                    table_names = set(inspector.get_table_names())
        except Exception:
            logger.exception("hotlist 迁移：hot_topics 重建失败")

        # ---- 阶段 3：收编无主 group 规则 → 主题「默认主题」----
        try:
            if "hot_topics" in table_names and "hot_keyword_rules" in table_names:
                rule_cols = {c["name"] for c in inspector.get_columns("hot_keyword_rules")}
                with engine.begin() as conn:
                    # 先查无主规则；没有就不动（全新库不预建默认主题）
                    orphans = conn.execute(
                        text(
                            "SELECT id FROM hot_keyword_rules "
                            "WHERE rule_type='group' AND topic_id IS NULL ORDER BY id"
                        )
                    ).fetchall()
                    if orphans:
                        # 确保「默认主题」存在（slug 唯一约束，已存在则复用）
                        row = conn.execute(
                            text("SELECT id FROM hot_topics WHERE slug='default'")
                        ).fetchone()
                        if row is not None:
                            default_topic_id = row[0]
                        else:
                            # 列集合按当前实际表结构动态拼 INSERT：老库上 hot_topics 还留着
                            # 改名前的 notify_enabled 等列（NOT NULL、无 DB 端 DEFAULT，ORM
                            # 的 default= 只在走 ORM insert 时生效），这里必须显式补值，
                            # 否则这条裸 SQL INSERT 会被 SQLite 的 NOT NULL 约束拒绝。
                            insert_values = {
                                "name": "'默认主题'",
                                "slug": "'default'",
                                "description": "'由迁移自动创建：收编历史遗留的无主关键词规则。'",
                                "enabled": "1",
                                "sort_order": "0",
                                "skill_key": "''",
                                "template_key": "NULL",
                                "extra_question": "''",
                                "digest_strategy": "'funnel'",
                                "digest_period": "'weekly'",
                                "digest_cron": "'0 8 * * 1'",
                                "max_items": "500",
                                "shortlist_size": "80",
                                "fulltext_size": "15",
                                "compare_with_previous": "1",
                                "publish_enabled": "0",
                                "publish_formats": "'[\"json\",\"html\"]'",
                                "report_notify_enabled": "0",
                                "report_notify_channel_ids": "'[]'",
                                "report_notify_time_start": "NULL",
                                "report_notify_time_end": "NULL",
                                "hit_notify_enabled": "0",
                                "hit_notify_channel_ids": "'[]'",
                                "hit_notify_time_start": "NULL",
                                "hit_notify_time_end": "NULL",
                                "hit_notify_frequency": "'realtime'",
                                "hit_notify_only_on_hit": "1",
                                "hit_notify_pending_hits": "0",
                                "hit_notify_pending_since": "NULL",
                                "created_at": "datetime('now')",
                                "updated_at": "datetime('now')",
                                # 改名前的老列（若还在表里，见类 docstring）
                                "notify_enabled": "0",
                                "notify_channel_ids": "'[]'",
                                "notify_time_start": "NULL",
                                "notify_time_end": "NULL",
                            }
                            existing_cols = {c["name"] for c in inspector.get_columns("hot_topics")}
                            cols = [c for c in insert_values if c in existing_cols]
                            col_sql = ", ".join(cols)
                            val_sql = ", ".join(insert_values[c] for c in cols)
                            res = conn.execute(
                                text(f"INSERT INTO hot_topics ({col_sql}) VALUES ({val_sql})")
                            )
                            default_topic_id = res.lastrowid

                        # 源 = 当前全部 enabled 源经 hot_topic_sources 关联 enabled=False（幂等）
                        enabled_sources = conn.execute(
                            text("SELECT id FROM hot_sources WHERE enabled=1")
                        ).fetchall()
                        for (source_id,) in enabled_sources:
                            exists = conn.execute(
                                text(
                                    "SELECT 1 FROM hot_topic_sources WHERE topic_id=:tid AND source_id=:sid"
                                ),
                                {"tid": default_topic_id, "sid": source_id},
                            ).fetchone()
                            if exists is None:
                                conn.execute(
                                    text(
                                        "INSERT INTO hot_topic_sources (topic_id, source_id, enabled, "
                                        "imported_from, added_at) VALUES (:tid, :sid, 0, 'builtin', "
                                        "datetime('now'))"
                                    ),
                                    {"tid": default_topic_id, "sid": source_id},
                                )

                        # 收编无主规则
                        for (rule_id,) in orphans:
                            conn.execute(
                                text("UPDATE hot_keyword_rules SET topic_id=:tid WHERE id=:rid"),
                                {"tid": default_topic_id, "rid": rule_id},
                            )
                        # 第一条规则若带 notify_enabled=1，把 notify_* 搬到该主题的 hit_notify_*
                        if "notify_enabled" in rule_cols:
                            first = conn.execute(
                                text(
                                    "SELECT notify_enabled, notify_channel_ids, notify_time_start, "
                                    "notify_time_end, notify_frequency, notify_only_on_hit, "
                                    "notify_pending_hits, notify_pending_since "
                                    "FROM hot_keyword_rules WHERE id=:rid"
                                ),
                                {"rid": orphans[0][0]},
                            ).fetchone()
                            if first is not None and first[0]:
                                conn.execute(
                                    text(
                                        "UPDATE hot_topics SET "
                                        "hit_notify_enabled=:enabled, "
                                        "hit_notify_channel_ids=:channel_ids, "
                                        "hit_notify_time_start=:time_start, "
                                        "hit_notify_time_end=:time_end, "
                                        "hit_notify_frequency=:frequency, "
                                        "hit_notify_only_on_hit=:only_on_hit, "
                                        "hit_notify_pending_hits=:pending_hits, "
                                        "hit_notify_pending_since=:pending_since "
                                        "WHERE id=:tid"
                                    ),
                                    {
                                        "tid": default_topic_id,
                                        "enabled": first[0],
                                        "channel_ids": first[1] or "[]",
                                        "time_start": first[2],
                                        "time_end": first[3],
                                        "frequency": first[4] or "realtime",
                                        "only_on_hit": first[5],
                                        "pending_hits": first[6] if first[6] is not None else 0,
                                        "pending_since": first[7],
                                    },
                                )
                        logger.warning(
                            "hotlist 迁移：已把 {} 条无主 group 规则收编进主题「默认主题」(slug=default)，请去检查调整",
                            len(orphans),
                        )
        except Exception:
            logger.exception("hotlist 迁移：无主规则收编失败")

        # ---- 阶段 4：内置分组 seed + 存量源归组 ----
        try:
            if "hot_source_groups" in table_names and "hot_sources" in table_names:
                with engine.begin() as conn:
                    existing_groups = {
                        g[0] for g in conn.execute(text("SELECT name FROM hot_source_groups")).fetchall()
                    }
                    if "中文热榜" not in existing_groups:
                        conn.execute(
                            text(
                                "INSERT INTO hot_source_groups (name, description, color, sort_order, "
                                "is_builtin, created_at, updated_at) "
                                "VALUES ('中文热榜', 'NewsNow 平台中文热榜源', '#ff4d4f', 0, 1, "
                                "datetime('now'), datetime('now'))"
                            )
                        )
                    if "技术社区" not in existing_groups:
                        conn.execute(
                            text(
                                "INSERT INTO hot_source_groups (name, description, color, sort_order, "
                                "is_builtin, created_at, updated_at) "
                                "VALUES ('技术社区', 'HN / GitHub / arXiv / HF 等技术源', '#1677ff', 1, 1, "
                                "datetime('now'), datetime('now'))"
                            )
                        )
                    conn.execute(
                        text(
                            "UPDATE hot_sources SET group_id="
                            "(SELECT id FROM hot_source_groups WHERE name='中文热榜') "
                            "WHERE group_id IS NULL AND source_kind='hotlist'"
                        )
                    )
                    conn.execute(
                        text(
                            "UPDATE hot_sources SET group_id="
                            "(SELECT id FROM hot_source_groups WHERE name='技术社区') "
                            "WHERE group_id IS NULL AND source_kind='tech'"
                        )
                    )
                    logger.warning("hotlist 迁移：内置源分组已就绪，存量源已归组")
        except Exception:
            logger.exception("hotlist 迁移：内置分组 seed / 存量源归组失败")

    except Exception:
        logger.exception("检查/补充 hotlist 主题规则与源分组 schema 失败")


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
    # hotlist 规则归属主题 + 源分组 + 推送配置拆分（老库幂等迁移）
    _ensure_hotlist_topic_rule_schema()
