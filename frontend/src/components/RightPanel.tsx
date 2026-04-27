import { useAppState } from "../lib/store";

function ToolsTab() {
  const { tools } = useAppState();
  if (!tools) {
    return <div className="panel-empty">暂无工具数据</div>;
  }
  return (
    <div className="tab-content">
      <section>
        <h3>手动可执行工具</h3>
        {tools.execution_tools.map((tool) => (
          <div key={`exec-${tool.name}`} className="info-card">
            <div className="info-title">{tool.name}</div>
            <div className="info-subtitle">{tool.description}</div>
            <div className="badge-row">
              {tool.execution_available ? <span className="badge">execution</span> : null}
              {tool.model_visible ? <span className="badge">model</span> : null}
              {tool.read_only ? <span className="badge">read-only</span> : null}
              {tool.dynamic ? <span className="badge">dynamic</span> : null}
            </div>
            {tool.usage ? <pre>{tool.usage}</pre> : null}
          </div>
        ))}
      </section>
      <section>
        <h3>主链可见工具</h3>
        {tools.model_tools.map((tool) => (
          <div key={`model-${tool.name}`} className="info-card compact-card">
            <div className="info-title">{tool.name}</div>
            <div className="info-subtitle">{tool.description}</div>
          </div>
        ))}
      </section>
    </div>
  );
}

function SkillsTab() {
  const { skills } = useAppState();
  if (!skills) {
    return <div className="panel-empty">暂无 skills 数据</div>;
  }
  return (
    <div className="tab-content">
      <section>
        <h3>用户可调用</h3>
        {skills.user_commands.map((skill) => (
          <div key={`user-${skill.name}`} className="info-card">
            <div className="info-title">{skill.name}</div>
            <div className="info-subtitle">{skill.description}</div>
            <div className="badge-row">
              <span className="badge">{skill.kind}</span>
              <span className="badge">{skill.loaded_from}</span>
              {skill.disable_model_invocation ? <span className="badge">no-model</span> : null}
            </div>
          </div>
        ))}
      </section>
      <section>
        <h3>模型可调用</h3>
        {skills.model_commands.map((skill) => (
          <div key={`model-${skill.name}`} className="info-card compact-card">
            <div className="info-title">{skill.name}</div>
            <div className="info-subtitle">{skill.description}</div>
          </div>
        ))}
      </section>
    </div>
  );
}

function McpTab() {
  const { mcp } = useAppState();
  if (!mcp) {
    return <div className="panel-empty">暂无 MCP 数据</div>;
  }
  return (
    <div className="tab-content">
      <section>
        <h3>连接</h3>
        {mcp.connections.map((connection) => (
          <div key={connection.name} className="info-card">
            <div className="info-title">{connection.name}</div>
            <div className="info-subtitle">
              {connection.scope} / {connection.transport} / {connection.status}
            </div>
            <div className="info-muted">{connection.url || connection.command || connection.error || "-"}</div>
          </div>
        ))}
      </section>
      <section>
        <h3>Tools</h3>
        {mcp.tools.map((tool) => (
          <div key={`${tool.server_name}-${tool.resolved_name}`} className="info-card compact-card">
            <div className="info-title">{tool.resolved_name}</div>
            <div className="info-subtitle">{tool.server_name}</div>
          </div>
        ))}
      </section>
      <section>
        <h3>Resources</h3>
        {mcp.resources.map((resource) => (
          <div key={`${resource.server_name}-${resource.uri}`} className="info-card compact-card">
            <div className="info-title">{resource.name}</div>
            <div className="info-subtitle">{resource.uri}</div>
          </div>
        ))}
      </section>
    </div>
  );
}

function TasksTab() {
  const { tasks } = useAppState();
  if (!tasks.length) {
    return <div className="panel-empty">当前没有任务</div>;
  }
  return (
    <div className="tab-content">
      {tasks.map((task) => (
        <div key={task.task_id} className="info-card">
          <div className="info-title">{task.task_id}</div>
          <div className="info-subtitle">
            {task.task_type} / {task.task_kind || "-"} / {task.status}
          </div>
          <div className="info-muted">{task.description || task.command}</div>
          <div className="info-muted">{task.output_path}</div>
        </div>
      ))}
    </div>
  );
}

export function RightPanel() {
  const { rightTab, setRightTab } = useAppState();

  return (
    <aside className="right-panel">
      <div className="right-tabs">
        {(["tools", "skills", "mcp", "tasks"] as const).map((tab) => (
          <button
            key={tab}
            className={rightTab === tab ? "right-tab right-tab-active" : "right-tab"}
            onClick={() => setRightTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="right-panel-body">
        {rightTab === "tools" ? <ToolsTab /> : null}
        {rightTab === "skills" ? <SkillsTab /> : null}
        {rightTab === "mcp" ? <McpTab /> : null}
        {rightTab === "tasks" ? <TasksTab /> : null}
      </div>
    </aside>
  );
}
