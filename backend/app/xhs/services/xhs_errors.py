"""
xhs 数据爬取异常体系（参考 MediaCrawler 的异常分类设计）。

核心思想：把"失败"按可处理方式分类——
- 网络错误：可重试
- 风控/限流：退避后重试
- 登录态失效：不可重试，需要用户重新登录
- 内容不存在：不可重试，跳过即可（不拖垮整个任务）

统一请求层（xhs_request_client）负责把原始响应翻译成这些异常，
上层（spider / tasks / tracking）按类型决策。
"""


class XhsError(Exception):
    """xhs 数据爬取基础异常"""


class XhsRateLimitError(XhsError):
    """触发平台风控/限流（code 300013 或 msg 含"频繁"），应退避后重试"""


class XhsAuthError(XhsError):
    """登录态失效/未登录，不应重试，需要用户重新登录后重跑任务"""


class XhsNotFoundError(XhsError):
    """笔记/内容不存在或已删除，不应重试，调用方应跳过该条"""


class XhsNetworkError(XhsError):
    """网络层错误（连接失败/超时/响应非 JSON），可重试"""
