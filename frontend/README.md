# claude-code-thy Frontend

这是 `claude-code-thy` 的前后端分离前端界面。

## 已接上的功能

- 会话列表加载 / 新建 / 删除
- transcript 加载
- `POST /api/chat` 的 SSE 消费
- 权限确认弹窗
- 右侧四个面板：
  - `tools`
  - `skills`
  - `mcp`
  - `tasks`

## 目录

- `src/lib/api.ts`
  前端对后端 Web API 的调用封装
- `src/lib/store.tsx`
  全局状态、SSE 消费、会话切换、权限处理
- `src/components/*`
  界面组件

## 运行方式

先启动后端：

```bash
claude-code-thy serve-web --host 127.0.0.1 --port 8002
```

再启动前端：

```bash
cd frontend
npm install --cache .npm-cache
npm run dev
```

默认前端地址：

```text
http://127.0.0.1:3000
```

## API 地址

前端默认连接：

```text
http://<当前页面主机名>:8002/api
```

也可以通过环境变量覆盖：

```bash
VITE_API_BASE_URL=http://127.0.0.1:8002/api
```

## 生产构建

```bash
cd frontend
npm run build
```
