# BrowserSearchTool 功能测试

这份文档只测试独立的 `browser_search` 工具。

测试时，默认你就在项目根目录 `claude-code-thy` 里执行命令。

## 1. 测试前准备

先确认这 3 件事：

1. 项目已经安装到当前环境

```bash
python -m pip install -e .
```

2. Playwright 的 Chromium 已安装

```bash
python -m playwright install chromium
```

3. 你的 `.env` 或当前环境里已经配置好了模型 provider

## 2. 启动交互界面

```bash
claude-code-thy
```

或者：

```bash
python -m claude_code_thy
```

## 3. 基础搜索测试

### 搜索并返回搜索结果页摘要

输入：

```text
/browser-search -- gpt5.4 相关的信息
```

预期：

- 会打开一个新的搜索结果页
- 返回里会有：
  - `Search Query`
  - `Search Engine`
  - `Search Parser`
  - `Search URL`
  - `Top Results`
  - `Expanded Pages`

### 指定搜索结果数量和展开网页数量

输入：

```text
/browser-search --result-count 10 --open-count 3 --per-page-max-chars 2500 -- gpt5.4 相关的信息
```

预期：

- 先收集前 10 条候选结果
- 再根据打分、去重和筛选规则选出更值得展开的 3 个网页
- 每个网页快照会按 `2500` 字符左右截断

### 只收集搜索结果，不展开网页

输入：

```text
/browser-search --result-count 8 --open-count 0 -- gpt5.4 相关的信息
```

预期：

- 只返回搜索结果列表
- `Expanded Pages` 会是空

## 4. 搜索结果筛选测试

重点看返回里的这些字段：

- `Score`
- `Selected: yes/no`
- `Why: ...`

预期：

- 更像官方文档、API、README、GitHub 的结果得分更高
- 同一个域名不会无限重复展开

## 5. 搜索后查看浏览器页面

搜索后输入：

```text
/browser tabs
```

预期：

- 会看到一个新的搜索结果页
- 搜索结果页会保留在浏览器里
- 被展开抓取的临时页面通常不会长期保留

## 6. 权限确认测试

如果你给 `browser_search` 配置了 `url` 权限确认规则，例如：

```json
{
  "permissions": [
    {
      "effect": "ask",
      "tool": "browser_search",
      "target": "url",
      "pattern": "https://*",
      "description": "搜索外部网页前先确认"
    }
  ]
}
```

那么执行：

```text
/browser-search -- gpt5.4 相关的信息
```

预期：

- 可能先在搜索结果页 URL 处触发一次确认
- 展开某个结果网页前，还可能再触发一次确认

## 7. 配置默认搜索引擎

你可以在：

```text
.claude-code-thy/settings.local.json
```

里加入：

```json
{
  "browser_search": {
    "default_search_engine": "searxng",
    "search_engines": {
      "duckduckgo": {
        "url_template": "https://html.duckduckgo.com/html/?q={query}",
        "parser": "duckduckgo_html",
        "enabled": true
      },
      "searxng": {
        "url_template": "http://127.0.0.1:8080/search?q={query}&language=zh-CN",
        "parser": "generic_links",
        "enabled": true
      }
    },
    "max_same_domain": 1,
    "dedupe_domains": true
  }
}
```

然后重新启动 `claude-code-thy`。

此时执行：

```text
/browser-search -- gpt5.4 相关的信息
```

默认就会使用 `searxng`。

如果你想临时指定搜索引擎，也可以：

```text
/browser-search --search-engine duckduckgo -- gpt5.4 相关的信息
```

## 8. 自动化测试

浏览器搜索相关的自动化测试可以这样跑：

```bash
/Users/thy/miniforge3/envs/claude-code-thy/bin/python -m pytest tests/test_browser_search.py tests/test_browser_search_tool.py
```

## 9. 当前版本限制

- `browser_search` 当前是顺序展开网页，不是并发抓取
- 搜索结果筛选目前是规则打分，不是 LLM 重排
- parser 目前只内置了 `duckduckgo_html` 和 `generic_links`
- 如果搜索引擎结果页结构变化，可能需要补 parser

## 10. 最短手工测试流程

```text
/browser-search --result-count 5 --open-count 2 -- gpt5.4 相关的信息
/browser tabs
/browser focus p1
```

这 3 步正常，说明当前独立 `browser_search` 工具主链路已经通了。
