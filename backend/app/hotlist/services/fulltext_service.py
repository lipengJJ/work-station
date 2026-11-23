"""L2 全文抓取与缓存（Phase 6 §4.3）。

三条约束：
1. 先看 RSS 里有没有——crawl_service 抓取时已把 content:encoded 全文写入缓存，这里直接命中；
2. 付费墙识别：正文短于 200 字或含明显订阅提示词的标 skipped；
3. 超时 8 秒、失败不重试——一批里失败两三条无所谓，不值得拖慢整个报告任务。

不做 robots.txt 检查（2026-08-29 移除）：本工具是个人/内部聚合阅读器，读取的是已公开
发布的文章做摘要展示，不是大规模商业爬虫；微信公众号（mp.weixin.qq.com）的 robots.txt
把除首页外的所有路径都 Disallow 了，而公众号恰好是我们内容里占比最大的来源，严格遵守
会导致"查看全文"对最主要的一类文章永远失效，权衡后选择不做这层检查。

正文抽取用 trafilatura（2026-08-29 引入），不再是整页 strip_html：输出保留标题层级
/图片/链接的 Markdown，剔除导航栏/广告/侧边栏噪声。同一份 Markdown 两头用——报告详情
页直接渲染给人看，GLM 逐篇摘要（topic_report_service._glm_digest）也吃这份数据，
不用再维护"给人看"和"给 AI 看"两份不同格式的正文。

微信公众号（mp.weixin.qq.com）单独走一条抽取路径（2026-08-29 加）：文章正文其实
就在静态 HTML 里的 `#js_content` 节点上，只是外层套了 `visibility: hidden` 靠 JS
在阅读器里做淡入动画——内容本身是完整的，不需要跑无头浏览器。但这块节点是公众号
编辑器特有的深层嵌套 `<section>/<span>`（不是规范的 `<p>`/`<h1-6>`），trafilatura
的密度启发式认不出这是正文主体，直接整页拿到几乎全空。改用 bs4 精确定位这个节点，
按"最内层块标签"切段落、`data-src` 转真实图片地址后手工拼 Markdown。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from loguru import logger
import requests
import trafilatura

from app.core.database import SessionLocal
from app.hotlist.models import HotItem, HotItemContent


@dataclass
class FulltextResult:
    """`fetch_fulltext()` 的返回值——纯数据，不挂在任何 Session 上。

    之所以不直接返回 `HotItemContent` ORM 实例：这个函数自开自关 Session，
    commit 后（默认 expire_on_commit=True）实例属性会被标记为"需要重新从库里
    读"，函数退出前又把 session 关掉了——调用方稍后访问 `.status`/`.content`
    触发这次"重新读"时找不到 session，直接报 DetachedInstanceError。批量小
    （15 篇）时凑巧没怎么撞上，量一大（50 篇）基本全灭。返回这个纯数据对象，
    从根上避免这类"返回值实际是个绑了 Session 的 ORM 对象"的坑。
    """

    status: str
    content: str = ""
    char_count: int = 0
    error: str = ""
    fetched_at: datetime | None = None

FULLTEXT_TIMEOUT = 8
MIN_BODY_CHARS = 200
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; WorkBench-Hotlist/1.0; +https://github.com)"
    ),
}
# 付费墙 / 订阅提示词：命中即降级（小写匹配）
PAYWALL_HINTS = (
    "subscribe to continue",
    "subscribe now",
    "please subscribe",
    "this content is for subscribers",
    "members only",
    "sign in to continue",
    "订阅后阅读",
    "付费解锁",
    "请订阅",
    "成为会员",
    "登录后阅读",
    "开通会员",
)

def _looks_paywalled(text: str) -> bool:
    """付费墙识别：明显订阅提示词命中即视为墙（不依赖长度判断）。"""
    low = (text or "").lower()[:2000]
    return any(hint in low for hint in PAYWALL_HINTS)


def _looks_empty(text: str) -> bool:
    """正文短于 MIN_BODY_CHARS 视为抓取失败/空页（可能被 JS 渲染或 404 页）。"""
    return len((text or "").strip()) < MIN_BODY_CHARS


def _is_wechat_article(url: str) -> bool:
    return urlsplit(url).netloc.lower() == "mp.weixin.qq.com"


# 微信正文块级容器：这几种标签只要不再嵌套同类标签，就当成"最内层段落"独立成段——
# 公众号编辑器导出的 HTML 没有规范的 <p>，全靠 <section> 嵌套模拟排版层级。
_WECHAT_BLOCK_TAGS = ("section", "p", "div")


def _extract_wechat_markdown(html: str) -> str:
    """从公众号文章静态 HTML 里精确抠出 `#js_content` 正文并转 Markdown。

    图片用的是懒加载的 `data-src`（不是 `src`，直接用 trafilatura/常规解析器
    找不到），先替换成真实地址再转成 Markdown 图片占位符文本，跟链接一起在
    get_text() 拍扁成纯文本之前处理，不然图片/链接就跟着一起丢了。
    """
    soup = BeautifulSoup(html, "lxml")
    content = soup.find(id="js_content")
    if content is None:
        raise ValueError("正文抽取失败（未找到 #js_content 节点，页面结构已变化）")

    for img in content.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        img.replace_with(f"\n\n![]({src})\n\n" if src else "")
    for a in content.find_all("a"):
        href = a.get("href") or ""
        text = a.get_text(strip=True)
        a.replace_with(f"[{text}]({href})" if href and text else text)
    for br in content.find_all("br"):
        br.replace_with("\n")

    def is_leaf_block(tag) -> bool:
        return tag.find(_WECHAT_BLOCK_TAGS) is None

    def is_heading(tag, text: str) -> bool:
        """公众号编辑器没有真的 <h1-6>，小节标题全靠"整块只有一个加粗、没别的
        文字、还比较短"这个视觉约定——跟正文里"一句话中间加粗强调"区分开（那种
        情况加粗片段前后还有别的文字，text 跟粗体文字不相等）。命中率取决于
        作者是否遵循这个约定，不是所有文章都能测出小节标题，测不出就没有目录，
        不算错误。"""
        strongs = tag.find_all(["strong", "b"])
        if len(strongs) != 1 or len(text) > 30:
            return False
        return strongs[0].get_text(separator="", strip=True) == text

    blocks = []
    for tag in content.find_all(_WECHAT_BLOCK_TAGS):
        if not is_leaf_block(tag):
            continue
        text = tag.get_text(separator="", strip=True)
        if not text:
            continue
        blocks.append(f"## {text}" if is_heading(tag, text) else text)
    md = "\n\n".join(blocks)
    if not md.strip():
        raise ValueError("正文抽取失败（#js_content 节点内没有可用文本）")
    return md.strip()


def _fetch_page(url: str) -> str:
    """抓取页面 HTML，抽取正文输出 Markdown（保留标题层级、图片 ![alt](src)、链接）。
    公众号文章走 `_extract_wechat_markdown` 精确定位正文节点；其余站点用 trafilatura
    的通用密度启发式识别主内容区、剔除导航/广告/侧边栏。抽取不到正文（页面结构异常
    /真·纯 JS 渲染）时按抓取失败处理，调用方降级用摘要。
    """
    try:
        resp = requests.get(
            url, timeout=FULLTEXT_TIMEOUT, headers=DEFAULT_HEADERS
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise ValueError(f"抓取失败: {exc}") from exc

    if _is_wechat_article(url):
        return _extract_wechat_markdown(resp.text)

    md = trafilatura.extract(
        resp.text,
        url=url,  # 传原始 URL 才能把相对路径的图片/链接解析成绝对地址
        output_format="markdown",
        include_images=True,
        include_links=True,
        include_formatting=True,
    )
    if not md or not md.strip():
        raise ValueError("正文抽取失败（trafilatura 未能识别出主内容区）")
    return md.strip()


def fetch_fulltext(item: HotItem) -> FulltextResult:
    """按需抓全文，结果写 hot_item_contents 缓存（同一条只抓一次）。

    自开自关 Session（供 topic_report_service 的 ThreadPoolExecutor 并发调用——
    SQLAlchemy Session 非线程安全，不能跨线程共享）。
    返回值是 FulltextResult（纯数据，见类注释），不是 ORM 实例。
    异常不外抛——调用方（主题报告的并发池）不能被单条失败打断。
    """
    db = SessionLocal()
    try:
        cached = db.get(HotItemContent, item.id)
        if cached is not None:
            return FulltextResult(
                status=cached.status,
                content=cached.content,
                char_count=cached.char_count,
                error=cached.error,
                fetched_at=cached.fetched_at,
            )

        now = datetime.now(timezone.utc)
        row = HotItemContent(item_id=item.id, fetched_at=now)

        # 1. RSS 自带全文（crawl 时已写入）——但这里是兜底查，正常情况 crawl 已写入
        if not item.url:
            row.status = "skipped"
            row.error = "条目无 URL"
            db.add(row)
            db.commit()
            return FulltextResult(status=row.status, error=row.error, fetched_at=now)

        try:
            text = _fetch_page(item.url)
        except ValueError as exc:
            row.status = "failed"
            row.error = str(exc)
            row.char_count = 0
            db.add(row)
            db.commit()
            logger.info(f"全文抓取失败（{item.id}）: {exc}")
            return FulltextResult(status=row.status, error=row.error, fetched_at=now)

        if _looks_paywalled(text):
            row.status = "skipped"
            row.error = "疑似付费墙/订阅提示"
            db.add(row)
            db.commit()
            logger.info(f"全文抓取跳过（付费墙）: {item.url}")
            return FulltextResult(status=row.status, error=row.error, fetched_at=now)

        if _looks_empty(text):
            row.status = "failed"
            row.error = "正文过短（可能被 JS 渲染或已下线）"
            db.add(row)
            db.commit()
            logger.info(f"全文抓取跳过（正文过短）: {item.url}")
            return FulltextResult(status=row.status, error=row.error, fetched_at=now)

        row.content = text
        row.char_count = len(text)
        row.status = "success"
        db.add(row)
        db.commit()
        return FulltextResult(
            status="success", content=text, char_count=len(text), fetched_at=now
        )
    finally:
        db.close()
