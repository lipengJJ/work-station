# CodeBook — AI 驱动的代码学习书生成器 · 实现方案

> 文档版本:v1.0
> 日期:2026-08-14
> 来源:软件开发团队协作产出(产品经理需求分析 + 架构师技术方案)
> 状态:待评审,通过后按 P0→P3 阶段实施

---

## 1. 产品定位与需求摘要

**一句话定位**:CodeBook 是一个调用 LLM 分析代码库、自动生成"代码学习书"静态网站的开发者工具,让学习者从整体架构到单函数细节按需理解陌生项目。

**核心能力**:选择仓库 → LLM 分析 → 生成学习书(架构图 / 模块划分 / 函数调用关系 / 技术知识点)→ 点击任意函数查看文件+行号与逻辑说明 → 增量更新 → 后续扩展 VSCode 插件。

**需求池**:P0(输入代码库、LLM 分析、知识图谱、静态站点、交互跳转)/ P1(技术知识点、增量更新、导出分享)/ P2(VSCode 插件、monorepo、更多语言)。

**核心交互流程**:选择代码库 → 配置 LLM → 一键生成 → 概览(架构图/技术栈/模块)→ 模块页 → 函数详情(文件+行号、调用图、知识点)→ 增量更新 → 导出分享。

**设计铁律**:调用关系、行号、签名必须来自真实 AST(tree-sitter),**LLM 只做描述性增强,不参与结构化信息生成**(防幻觉、控成本)。

---

## 2. 总体架构(三层)

CLI 是核心,静态站点与 VSCode 插件共用同一份中间产物 `codebook.json`,保证"一次分析、多处呈现"。

```
┌────────────────────────────────────────────────────────────────────┐
│                 CodeBook 生成管线(CLI 核心,TypeScript/Node)         │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐ │
│  │ ① 仓库扫描 │→│ ② 代码切分 │→│ ③ 静态分析 │→│ ④ LLM增强 │→│ ⑤ 图谱合并  │ │
│  │ Scanner  │ │ Chunker  │ │ Analyzer │ │ Enricher │ │ GraphMerge│ │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └───────────┘ │
│      file tree   chunk 单元   AST/调用图/   分级摘要    codebook.json│
│      语言统计      (模块/文件)  依赖图(真实)    +缓存      +site 内容  │
└────────────────────────────────────────────────────────────────────┘
                             │ 输出
                             ▼
                  ┌─────────────────────┐
                  │ ⑥ 站点构建 (VitePress) │  → dist/ 静态文件
                  └─────────────────────┘
              ┌──────────────┴───────────────┐
              ▼                               ▼
   ┌────────────────────┐        ┌────────────────────┐
   │ A. 静态学习书网站     │        │ B. VSCode 插件(可选)  │
   │ 首页/模块列表/函数详情  │        │ Webview 内嵌查看学习书 │
   │ 调用图/代码跳转        │        │ 复用 ①-⑤ 分析管线     │
   └────────────────────┘        └────────────────────┘
```

数据流单一方向:源码 → `codebook.json` → 各端渲染。**站点与插件不直接读源码**,只消费 codebook.json(内含定位所需的内联代码片段),渲染层与解析层完全解耦。

---

## 3. 代码理解管线(核心)

### ① 仓库扫描(Scanner)
遍历目录生成文件树;读取 `.gitignore`、`.git/info/exclude` + 内置忽略规则(二进制、`node_modules`/`dist`/`target`、锁文件等);按扩展名统计语言分布与行数。输出 `scanner.json`。

### ② 代码切分(Chunker)
按"模块 → 文件 → 顶层符号(函数/类/接口)"三级边界切分:
- 模块边界:目录约定(`src/` 子目录)、`package.json`/`go.mod` 模块声明、语言约定(Go package)。
- 符号边界:由 ③ 的 tree-sitter 提供精确行区间,切分不靠正则。

### ③ 静态分析(Analyzer)—— 管线的地基
- **tree-sitter** 解析每个文件:
  - 提取函数/方法/类定义:`name, signature, params, return_type, line_start, line_end`
  - 提取 `callees`:遍历函数体内调用节点 + 局部作用域解析(本地符号 → 同文件符号 → 导入符号)
  - 跨文件引用:import/require 建立文件间引用表,解析跨文件调用边
  - 模块依赖图:包/模块级 import 图
- 语言适配:每种语言一个 grammar + 一个 `SymbolExtractor`,输出统一 IR。首版覆盖 JS/TS、Python、Go、Java、Rust、C/C++。
- 输出:`symbols.json`(符号节点)、`callgraph.json`(有向边)、`depgraph.json`(模块依赖)。

### ④ LLM 增强(Enricher)
LLM 只做三类描述性产出:
1. **函数/模块讲解**:输入 = 签名 + 调用关系摘要 + 截断代码片段 → 输出"做什么、怎么用、注意点"
2. **技术知识点**:规则匹配热点模式(设计模式、框架机制、并发模型)+ 模块级 LLM 提炼关键点
3. **架构总览**:模块级讲解 + 依赖图结构 → 分层架构描述

### ⑤ 知识图谱合并(GraphMerge)
合并 `symbols + callgraph + depgraph + LLM 描述 + 内联代码片段` 为自包含 `codebook.json`,并做一致性校验:LLM 引用的符号不在 symbol 表中则剔除(防幻觉)。

---

## 4. 数据模型(codebook.json)

```jsonc
{
  "schema_version": "1.0",
  "meta": {
    "project": "CodeBook", "root": "/abs/path",
    "default_branch": "main", "remote_url": "https://github.com/...",
    "generated_at": "2026-08-14T10:00:00Z", "git_revision": "a1b2c3d",
    "languages": [{ "name": "TypeScript", "files": 120, "lines": 18420 }]
  },
  "modules": [{
    "id": "mod_scanner", "name": "scanner", "path": "src/scanner",
    "summary": "扫描仓库文件树…", "deps": ["mod_utils"], "depended_by": ["mod_pipeline"],
    "files": ["src/scanner/index.ts"], "topics": ["topic_gitignore"]
  }],
  "functions": [{
    "id": "fn_scanner_scan", "name": "scan", "module_id": "mod_scanner",
    "file": "src/scanner/index.ts", "line_start": 42, "line_end": 78,
    "signature": "scan(root: string, ignore: IgnoreRules): FileTree",
    "callees": ["fn_ignore_load"], "callers": ["fn_pipeline_run"],   // 真实 AST 边
    "description": "遍历目录,结合 gitignore 规则产出文件树…",
    "code_snippet": "export function scan(root… { … }",              // 生成时内联截取
    "topics": ["topic_ignore_rules"]
  }],
  "topics": [{ "id": "topic_gitignore", "title": ".gitignore 匹配规则",
               "module_ids": [], "function_ids": [], "body": "…", "source": "llm" }],
  "architecture": {
    "layers": [{ "name": "分析层", "module_ids": ["mod_scanner"] }],
    "overview": "…", "diagram": "mermaid 或树状 JSON"
  }
}
```

关键设计:`functions` 是枢纽节点;`code_snippet + line_start/end + file` 三要素保证离线定位;`git_revision` 用于生成不失效的 GitHub 链接。

---

## 5. 静态站点方案

- **选型:VitePress**(Vue 3 + Vite SSG)。理由:学习书是"自定义交互组件驱动的数据型站点",VitePress 原生支持自定义 Vue 组件 + mermaid + 自动锚点路由,与 TS 管线共享 `codebook.d.ts`;Docusaurus 自定义组件笨重,Next.js SSG 偏重。
- **页面**:`/` 首页(元信息/语言统计/架构总览)、`/module/:id`(职责/依赖图/函数列表)、`/function/:id`(签名/行号徽标/内联代码高亮/可点击递归调用图/讲解/知识点)、`/topic/:id` + FlexSearch 全局搜索。
- **代码跳转三策略并存**:① 内联 code_snippet + 行号高亮(默认,离线可用);② `vscode://file/{abs}:{line}`(桌面端一键打开);③ `{remote_url}/blob/{git_revision}/{file}#L{line}`(GitHub 链接)。

---

## 6. LLM 接入与成本控制

- **多供应商抽象**:`ChatProvider` 接口(`chat(messages, opts)`),实现 OpenAI / Anthropic / Ollama(本地)/ Mock(测试)。配置走环境变量,不硬编码密钥。
- **分层摘要(关键)**:第一遍按符号粒度调用(签名+调用边+≤100 行代码);模块/架构总结只喂"符号摘要的拼接"——摘要的摘要,成本随层级近线性而非平方爆炸。
- **预算控制**:按模型上下文×0.8 设批次预算,超预算降级(跳过低优先级符号,按出度/入度/中心性排序)。
- **缓存**:LLM 输出以 `(git_blob_hash + prompt_hash)` 为 key 落盘缓存,命中即跳过。
- **隐私**:默认本地运行;调远程 LLM 前交互式确认("将发送 {n} 个文件摘要至 {provider}");提供 `--local-only`(Ollama);发送内容仅为截断摘要,支持排除路径。

---

## 7. 增量更新

1. `git diff` 得变更文件集 → 按 blob_hash 比对,未变跳过
2. 变更文件局部重跑 ②③ 解析
3. 通过旧 callgraph 找 `callers` 集合,标记受影响符号需重生成描述;未受影响复用缓存
4. 重跑 ⑤ 合并 → 站点增量构建
5. 无 git 时退化为全量扫描

---

## 8. VSCode 插件扩展路径

- **复用方式**:分析管线打包为独立 npm 库 `@codebook/engine`(纯 Node + tree-sitter,无 CLI 副作用),CLI 与插件共同依赖;插件调用 `engine.analyze()` Node API,不 shell 外包 CLI。
- **内嵌查看**:`WebviewPanel` 加载生成器 `dist/`,`asWebviewUri` 映射静态资源,`onDidReceiveMessage` 桥接"跳转 vscode://file/:line"。
- **边界**:CLI 负责生成(适合 CI);插件负责命令入口、调用 engine、webview 呈现、编辑器跳转、监听文件保存/git 变更触发增量。插件**不重新实现**解析/生成逻辑。

---

## 9. 任务分解

| 阶段 | 内容 | 验收标准 |
|---|---|---|
| **P0 骨架** | 扫描 + 切分 + tree-sitter 静态分析(先 JS/TS)+ 最小静态站 | 中型 TS 仓库(5k 行)离线生成站点,函数详情页显示真实 callees/callers,零 LLM 调用 |
| **P1 LLM 增强** | ChatProvider 抽象、分层摘要、缓存、函数/模块讲解、topics | 完整 codebook.json;缓存命中二次运行零 token;MockProvider 跑通全流程 |
| **P2 交互/增量** | 搜索、调用图交互、GitHub/vscode 跳转、git diff 增量 | 改一个函数签名后仅该函数及其 callers 重算,耗时 < 全量 10% |
| **P3 VSCode 插件** | `@codebook/engine` 库化、插件骨架(命令+webview+跳转桥接) | VSCode 一键生成并内嵌浏览,点击函数在编辑器定位,与 CLI 共享 engine |

主要文件:`packages/engine/src/{scanner,chunker,analyzer,llm,enricher,cache,graph,incremental,index}.ts`、`packages/cli/src/index.ts`、`packages/site/`、`packages/vscode-ext/src/{extension,panel}.ts`。

---

## 10. 技术栈

- **主栈:TypeScript + Node.js(≥18)**。理由:tree-sitter 有 node/web 双绑定;与 VSCode 插件零桥接共享 engine;站点同栈共享类型。Python 双栈不可复用,否决。
- 解析:`tree-sitter` + 各语言 grammar(typescript、python、go、java、rust、cpp),`SymbolExtractor` 接口可插拔
- 图渲染:d3 / cytoscape.js(调用图交互)+ mermaid(架构图)
- 站点:VitePress + FlexSearch(预构建索引)
- LLM SDK:openai、@anthropic-ai/sdk、Ollama HTTP API
- 缓存:文件系统 JSON(量大换 better-sqlite3)
- 其他:fast-glob(扫描)、chokidar(插件监听)、picocolors(CLI 输出)

---

## 11. 风险与对策

| 风险 | 对策 |
|---|---|
| LLM 幻觉(编造调用关系/行号) | 调用边/行号/签名一律 AST 产出;合并时一致性校验剔除;描述中禁止 LLM 输出行号/文件名 |
| 大仓库 token 爆炸 | 分层摘要(摘要的摘要);按符号重要性分配预算;缓存 + 增量 |
| 隐私合规 | 默认本地;远程调用前交互确认;`--local-only`;只发截断摘要;排除路径可配 |
| 超长单文件/非 git 仓库 | 单符号超上下文丢弃函数体仅留签名;非 git 降级全量扫描 |
| 多语言解析缺失 | 未支持语言降级为"仅展示 + 纯静态描述";extractor 可插拔补充 |

**实施顺序**:P0 → P1 → P2 → P3;P0 不依赖 LLM,风险最低,可立即验证静态分析正确性(整个产品可信度的根)。

---

## 12. 待确认问题(启动实施前需决策)

1. 代码分析本地还是云端?敏感代码是否有"不上传"硬要求?(影响默认模式设计)
2. 首版语言范围?建议 JS/TS + Python(与现有 workbench 项目强相关)
3. LLM 供应商/模型?是否需要多家可切换?(建议 OpenAI 兼容 + Ollama 双支持)
4. 静态站托管方式?(本地浏览 / GitHub Pages / 内网)
5. 生成是"全量自动"还是"先大纲再深入"?(成本与体验取舍,建议 MVP 全量自动)
6. 学习书是否需要多语言输出?
