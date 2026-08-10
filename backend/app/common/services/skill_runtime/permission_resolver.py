"""
把 Skill 声明的工具需求（google_search / url_context）转成本次请求实际会带上的 Gemini
工具列表：Skill 能不能用某个工具最终由平台白名单决定，Skill 没声明的工具不会被打开；
Google 搜索还额外受用户本次请求的 enable_search 开关约束（设计文档 5.4 节 Permission
Resolver："Skill 只能请求能力，平台白名单决定最终是否允许"）。
"""
from __future__ import annotations

# 第一阶段两个工具都是只读、安全的检索能力，平台层面直接放行；后续如果引入更高风险的
# 工具类型，在这里加白名单开关即可，不用改调用方代码。
PLATFORM_TOOL_WHITELIST = {"google_search": True, "url_context": True}


def resolve_tools(tool_policy: dict, enable_search: bool) -> list[str]:
    tools = []
    if tool_policy.get("google_search") and PLATFORM_TOOL_WHITELIST["google_search"] and enable_search:
        tools.append("google_search")
    if tool_policy.get("url_context") and PLATFORM_TOOL_WHITELIST["url_context"]:
        tools.append("url_context")
    return tools
