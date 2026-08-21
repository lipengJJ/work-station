"""
Skill 文件系统访问的唯一入口：所有读文件/列目录都要经过这里的路径校验，不允许
控制器或别的 service 自己拼 Path。第一阶段只有 builtin 一种来源（workbench/skills/
下的目录），第二阶段加 ZIP 导入后 upload 来源会指向 storage/skills/<name>/<version>/，
到时候在 BUILTIN_ROOT 旁边加一个 UPLOAD_ROOT，resolve_skill_root 按 source_type 分流即可。
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

# backend/app/skills/services/storage_service.py -> parents[4] 是 workbench/backend 的
# 上一级，即 workbench/；仓库自带的「内置 Skill」放这里（随代码走，如 gemini-travel-planner）。
REPO_SKILLS_ROOT: Path = Path(__file__).resolve().parents[4] / "skills"

# 用户自行导入/安装的 Skill 放仓库之外的独立目录，避免把上传内容写进 Git 工作区。
# 位置可用环境变量 WORKBENCH_SKILLS_DIR 覆盖，默认 ~/.workbench/skills。
EXTERNAL_SKILLS_ROOT: Path = Path(
    os.environ.get("WORKBENCH_SKILLS_DIR", "") or (Path.home() / ".workbench" / "skills")
).expanduser()

# 兼容旧代码里引用 BUILTIN_ROOT 的地方（仅仓库根）。
BUILTIN_ROOT: Path = REPO_SKILLS_ROOT

MAX_FILE_BYTES = 512 * 1024  # 单个文件预览上限 512KB，超过的截断读取而不是拒绝整个请求
MAX_HASH_FILE_BYTES = 4 * 1024 * 1024  # 参与内容哈希计算的单文件上限，超大文件跳过内容只算路径
MAX_TREE_ENTRIES = 2000  # 文件树条目上限，防止异常大的目录拖垮列表接口

# 不进入文件树/预览的路径片段：, .git 目录不该出现在 Skill 目录里，出现了也不展示
_IGNORED_NAMES = {".git", "__pycache__", ".ds_store"}


class SkillPathError(ValueError):
    """请求的相对路径试图逃逸 Skill 根目录，或指向不允许访问的内容。"""


def _all_skill_roots() -> list[Path]:
    """扫描顺序：先仓库根、后外部根。同名 Skill 仓库根优先。"""
    roots = [REPO_SKILLS_ROOT]
    if EXTERNAL_SKILLS_ROOT != REPO_SKILLS_ROOT:
        roots.append(EXTERNAL_SKILLS_ROOT)
    return roots


def resolve_skill_root(source_type: str, storage_path: str) -> Path:
    """
    根据 SkillVersion.source_type + storage_path 算出该版本内容在磁盘上的根目录。
    storage_path 存的是相对路径（相对哪个根由 source_type 决定），这里做真正的拼接
    和越权校验，controller/service 层拿到的都是这个函数返回的、已确认安全的绝对路径。
    """
    if source_type != "builtin":
        # 第一阶段只登记内置 Skill，upload/local/github 来源留给后续阶段接入
        raise SkillPathError(f"暂不支持的 Skill 来源类型：{source_type}")
    # 先做路径合法性校验（禁止绝对路径 / .. 逃逸），再在仓库根与外部根里定位
    if not storage_path or storage_path in {".", "/"}:
        return REPO_SKILLS_ROOT
    if os.path.isabs(storage_path) or ".." in Path(storage_path).parts:
        raise SkillPathError(f"非法路径：{storage_path}")
    for root in _all_skill_roots():
        candidate = root / storage_path
        if candidate.is_dir():
            return candidate.resolve()
    # 未命中任何根：回退到仓库根的安全拼接（保持旧行为，让后续 is_file 检查报“不存在”）
    return _safe_join(REPO_SKILLS_ROOT, storage_path)


def _safe_join(root: Path, relative: str) -> Path:
    if not relative or relative in {".", "/"}:
        candidate = root
    else:
        if os.path.isabs(relative) or ".." in Path(relative).parts:
            raise SkillPathError(f"非法路径：{relative}")
        candidate = root / relative

    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise SkillPathError(f"路径越界：{relative}")
    return resolved


def list_builtin_skill_dirs() -> list[Path]:
    """内置 Skill 的判定标准：仓库根（workbench/skills/）或外部根（~/.workbench/skills/）
    下、直接子目录里有 SKILL.md 的都算；同名时仓库根优先，外部根去重。"""
    result: list[Path] = []
    seen: set[str] = set()
    for root in _all_skill_roots():
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if entry.is_dir() and not entry.is_symlink() and (entry / "SKILL.md").is_file():
                if entry.name in seen:
                    continue
                seen.add(entry.name)
                result.append(entry)
    return sorted(result, key=lambda p: p.name)


@dataclass
class FileNode:
    name: str
    path: str  # 相对 Skill 根目录的路径，用 / 分隔
    type: str  # "file" | "dir"
    size: int | None = None
    children: list["FileNode"] = field(default_factory=list)


def build_file_tree(skill_root: Path) -> list[FileNode]:
    """按目录结构列出 Skill 内容，跳过符号链接和隐藏的系统目录（.git/__pycache__ 等）。"""
    count = 0

    def _walk(dir_path: Path, rel_prefix: str) -> list[FileNode]:
        nonlocal count
        nodes: list[FileNode] = []
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: (p.is_file(), p.name))
        except OSError:
            return nodes
        for entry in entries:
            if count >= MAX_TREE_ENTRIES:
                break
            if entry.name.lower() in _IGNORED_NAMES or entry.is_symlink():
                continue
            rel_path = f"{rel_prefix}{entry.name}"
            count += 1
            if entry.is_dir():
                nodes.append(
                    FileNode(
                        name=entry.name,
                        path=rel_path,
                        type="dir",
                        children=_walk(entry, f"{rel_path}/"),
                    )
                )
            elif entry.is_file():
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = None
                nodes.append(FileNode(name=entry.name, path=rel_path, type="file", size=size))
        return nodes

    return _walk(skill_root, "")


def read_file_text(skill_root: Path, relative_path: str) -> tuple[str, bool]:
    """
    返回 (内容, 是否被截断)。relative_path 必须先过 _safe_join 校验，不能直接拼路径。
    读取失败（二进制、无法解码）时抛 SkillPathError，由 controller 转成 4xx。
    """
    target = _safe_join(skill_root, relative_path)
    if not target.is_file():
        raise SkillPathError(f"文件不存在：{relative_path}")
    try:
        raw = target.read_bytes()
    except OSError as e:
        raise SkillPathError(f"读取文件失败：{e}") from e

    truncated = len(raw) > MAX_FILE_BYTES
    raw = raw[:MAX_FILE_BYTES]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise SkillPathError("该文件不是文本内容，无法预览") from e
    return text, truncated


def write_file_text(skill_root: Path, relative_path: str, content: str) -> None:
    """
    把文本内容写回 Skill 目录内的文件（页面编辑保存）。路径必须先过 _safe_join 校验，
    不允许逃逸 Skill 根目录；只允许覆盖已存在的文本文件，内容超过单文件上限（与预览
    截断阈值一致）直接拒绝，避免拿不完整的预览内容覆盖完整文件。写入采用临时文件 +
    os.replace 的原子替换，避免写一半崩溃留下半截文件。
    """
    target = _safe_join(skill_root, relative_path)
    if not target.is_file():
        raise SkillPathError(f"文件不存在：{relative_path}")
    try:
        raw = content.encode("utf-8")
    except UnicodeEncodeError as e:
        raise SkillPathError("内容不是合法 UTF-8 文本，无法保存") from e
    if len(raw) > MAX_FILE_BYTES:
        raise SkillPathError(f"保存内容超过 {MAX_FILE_BYTES} 字节上限")

    tmp = target.with_name(f".{target.name}.wb-tmp")
    try:
        tmp.write_bytes(raw)
        os.replace(tmp, target)
    except OSError as e:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise SkillPathError(f"写入文件失败：{e}") from e


def compute_content_hash(skill_root: Path) -> str:
    """
    对目录下所有文件的相对路径 + 内容做 sha256，得到内容指纹。用于判断 Skill 目录
    自上次扫描以来是否变化过，避免每次启动都无脑新建一条 SkillVersion。
    超过 MAX_HASH_FILE_BYTES 的文件只把路径和大小计入摘要，不读取全部内容，防止
    个别大文件拖慢启动扫描。
    """
    digest = hashlib.sha256()
    tree = build_file_tree(skill_root)

    def _flatten(nodes: list[FileNode]) -> list[FileNode]:
        flat = []
        for node in nodes:
            if node.type == "file":
                flat.append(node)
            else:
                flat.extend(_flatten(node.children))
        return flat

    for node in sorted(_flatten(tree), key=lambda n: n.path):
        digest.update(node.path.encode("utf-8"))
        file_path = skill_root / node.path
        try:
            size = file_path.stat().st_size
        except OSError:
            continue
        digest.update(str(size).encode("utf-8"))
        if size <= MAX_HASH_FILE_BYTES:
            try:
                digest.update(file_path.read_bytes())
            except OSError:
                pass
    return f"sha256:{digest.hexdigest()}"
