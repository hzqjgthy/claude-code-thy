# BrowserTool 功能测试

这份文档是给当前 `claude-code-thy` 里已经实现的浏览器工具用的。

测试时，默认你就在项目根目录 `claude-code-thy` 里执行命令。

## 1. 测试前准备

先确认这 3 件事：

1. 项目已经安装到当前环境

```bash
python -m pip install -e .
```

1. Playwright 的 Chromium 已安装

```bash
python -m playwright install chromium
```

1. 你的 `.env` 或当前环境里已经配置好了模型 provider

只要你平时能正常启动 `claude-code-thy`，这一条一般就已经没问题。

## 2. 启动交互界面

```bash
claude-code-thy
```

如果你平时是源码方式启动，也可以用：

```bash
python -m claude_code_thy
```

进入交互界面后，下面的命令都直接在输入框里输。

## 3. 基础状态测试

### 测试浏览器状态

输入：

```text
/browser status
```

预期：

- 会看到 `enabled`、`running`、`page_count`、`profile_dir`、`artifacts_dir`
- 第一次通常是 `running: False`

### 启动浏览器

输入：

```text
/browser start
```

预期：

- 会看到浏览器状态更新为 `running: True`
- 会自动创建浏览器 profile 目录

### 再看一次状态

输入：

```text
/browser status
```

预期：

- 现在应该是 `running: True`

## 4. 标签页测试

### 查看当前页面列表

输入：

```text
/browser tabs
```

预期：

- 会列出当前页面
- 页面一般会显示成 `p1`、`p2` 这种 `page_id`

### 打开一个网页

输入：

```text
/browser open https://example.com
```

预期：

- 会打开一个新页面
- 返回里会有 `page_id`、`title`、`url`

### 再看页面列表

输入：

```text
/browser tabs
```

预期：

- 能看到刚才打开的页面

### 切换页面

假设页面里有 `p1`、`p2`，输入：

```text
/browser focus p1
```

预期：

- 当前页面切换到 `p1`

### 关闭页面

输入：

```text
/browser close p1
```

或者不带参数，关闭当前页：

```text
/browser close
```

预期：

- 页面数量减少

## 5. 导航测试

### 当前页跳转到新地址

输入：

```text
/browser navigate https://www.example.com
```

预期：

- 当前页地址变成新的 URL

如果你想指定页面：

```text
/browser navigate https://www.example.com --page-id p1
```

## 6. 快照测试

### 获取页面快照

输入：

```text
/browser snapshot
```

预期：

- 返回里会有：
  - `Page Title`
  - `Page URL`
  - `Interactive Elements`
  - 一批像 `e1`、`e2` 这样的 ref
- 这些 ref 是后面 `click` / `type` 用的

### 限制快照长度

输入：

```text
/browser snapshot --max-chars 2000
```

预期：

- 返回内容更短

## 7. 截图测试

### 普通截图

输入：

```text
/browser screenshot
```

预期：

- 会返回一条“截图已保存”
- 输出里会有文件路径
- 文件默认保存在：

```text
.claude-code-thy/browser-artifacts
```

### 整页截图

输入：

```text
/browser screenshot --full-page
```

预期：

- 生成一张整页截图

## 8. 页面交互测试

这一组测试前，先执行一次：

```text
/browser snapshot
```

记住返回里的某个 ref，比如 `e1`、`e2`。

### 点击元素

输入：

```text
/browser click e1
```

预期：

- 页面发生点击动作
- 如果页面跳转或 DOM 大改，旧 ref 可能失效

### 输入文本

输入：

```text
/browser type e2 -- hello browser
```

预期：

- 对应输入框被填入 `hello browser`

### 输入后回车提交

输入：

```text
/browser type e2 --submit -- hello browser
```

预期：

- 输入完成后自动按 Enter

### 键盘按键

输入：

```text
/browser press Enter
```

或者：

```text
/browser press Escape
```

预期：

- 当前页面收到对应按键

## 9. wait 测试

### 等待固定时间

输入：

```text
/browser wait --time-ms 1000
```

预期：

- 大约等 1 秒后返回

### 等待页面出现某段文字

先打开 example.com：

```text
/browser open https://example.com
```

再输入：

```text
/browser wait --text "Example Domain"
```

预期：

- 页面出现该文本后返回成功

### 等待 URL 包含某段字符串

输入：

```text
/browser wait --url-contains example
```

预期：

- 当前地址里包含 `example` 时返回成功

## 10. 权限确认测试

当前浏览器工具已经接了 `url` 权限能力。

如果你要专门测试这一点，可以先在：

```text
.claude-code-thy/settings.local.json
```

里加入：

```json
{
  "permissions": [
    {
      "effect": "ask",
      "tool": "browser",
      "target": "url",
      "pattern": "https://*",
      "description": "访问外部网址前先确认"
    }
  ]
}
```

浏览器配置，加入：

```json
{
  "browser": {
    "enabled": true,
    "headless": false
  }
}

```

然后重新启动 `claude-code-thy`。

再输入：

```text
/browser open https://example.com
```

预期：

- 界面会弹出权限确认提示
- 你输入 `yes` 后继续执行
- 你输入 `no` 后取消执行

## 11. 自动化测试

如果你想直接跑这次浏览器模块相关的自动化测试，可以在项目根目录执行：

```bash
/Users/thy/miniforge3/envs/claude-code-thy/bin/python -m pytest tests/test_browser_tool.py tests/test_settings.py tests/test_ui_tool_views.py
```

预期：

- 当前浏览器模块相关测试全部通过

## 12. 产物位置

### 浏览器 profile

默认在：

```text
.claude-code-thy/browser-profile
```

### 截图等产物

默认在：

```text
.claude-code-thy/browser-artifacts
```

## 13. 当前版本已知限制

当前是第一版，重点先把主链路做通，所以你测试时要知道这些限制是正常的：

- 现在只支持“隔离浏览器”，还不支持接管你系统里已经打开的 Chrome 标签页
- `snapshot` 里的 `ref` 在页面跳转、DOM 变化后可能失效
- 如果 `ref` 失效，重新执行一次 `/browser snapshot` 再继续操作
- 现在还没有做 OpenClaw 那种 browser relay / remote node / sandbox browser container
- 网页搜索已经从 `browser` 拆分到独立工具 `browser_search`
- 如果提示缺少 Playwright 或 Chromium，就先执行：

```bash
python -m playwright install chromium
```

## 14. 一套最短的手工测试流程

你如果只想快速确认浏览器主链路是否通了，按下面顺序输就行：

```text
/browser status
/browser start
/browser open https://example.com
/browser snapshot
/browser screenshot
/browser wait --text "Example Domain"
/browser tabs
/browser stop
```

这 8 步都正常的话，说明当前第一版浏览器模块已经基本可用了。