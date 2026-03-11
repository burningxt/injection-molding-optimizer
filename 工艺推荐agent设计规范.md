# 工艺推荐 Agent 设计规范

## 1. 概述

本文档定义注塑成型工艺参数智能推荐系统中 Agent 层的设计规范。

## 2. 架构设计

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                     用户交互层                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   Web 前端   │  │    CLI      │  │     API 接口         │  │
│  │  (FastAPI)  │  │  (Typer)    │  │  (REST/WebSocket)    │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
└─────────┼────────────────┼────────────────────┼─────────────┘
          │                │                    │
          └────────────────┴────────┬───────────┘
                                    │
                           ┌────────▼────────┐
                           │   Agent 网关    │
                           │  (消息路由器)   │
                           └────────┬────────┘
                                    │
┌───────────────────────────────────┼─────────────────────────┐
│                              Agent 核心层                    │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              中央协调器 (Orchestrator)               │  │
│  │        意图识别 · 任务分发 · 状态管理 · 上下文维护    │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────────┐ │
│  │参数解释  │ │异常诊断  │ │优化建议  │ │   知识管理     │ │
│  │  Agent   │ │  Agent   │ │  Agent   │ │    Agent       │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────────┬───────┘ │
└───────┼────────────┼────────────┼────────────────┼─────────┘
        │            │            │                │
        └────────────┴────────────┴───────┬────────┘
                                          │
                                 ┌────────▼────────┐
                                 │     工具层       │
                                 │  (Tools/MCP)    │
                                 └────────┬────────┘
                                          │
┌─────────────────────────────────────────┼──────────────────┐
│                                      基础设施层               │
│  ┌────────────┐ ┌────────────┐ ┌────────▼────────┐         │
│  │  贝叶斯优化 │ │  LLM 服务  │ │   向量数据库     │         │
│  │ (BoTorch)  │ │ (Claude)   │ │  (Chroma/PG)   │         │
│  └────────────┘ └────────────┘ └─────────────────┘         │
│  ┌────────────┐ ┌────────────┐ ┌─────────────────┐         │
│  │  数据持久化 │ │   Excel    │ │    配置管理      │         │
│  │ (SQLite)   │ │  导入导出   │ │   (Pydantic)   │         │
│  └────────────┘ └────────────┘ └─────────────────┘         │
└────────────────────────────────────────────────────────────┘
```

### 2.2 模块位置

```
src/injection_molding/
├── agents/                      # Agent 层
│   ├── __init__.py
│   ├── orchestrator.py          # 中央协调器
│   ├── explainer.py             # 参数解释 Agent
│   ├── diagnostician.py         # 异常诊断 Agent
│   ├── advisor.py               # 优化建议 Agent
│   ├── knowledge.py             # 知识管理 Agent
│   └── tools/                   # 工具定义
│       ├── __init__.py
│       ├── parameters.py        # 参数相关工具
│       ├── records.py           # 记录相关工具
│       └── llm.py               # LLM 工具
```

## 3. Agent 定义

### 3.1 中央协调器 (Orchestrator)

**职责**：管理所有 Agent 的协作，负责意图识别和任务分发。

```python
class AgentOrchestrator:
    """Agent 协调器"""

    def __init__(self):
        self.agents: dict[str, BaseAgent] = {
            "explain": ParameterExplainerAgent(),
            "diagnose": AnomalyDiagnosticianAgent(),
            "advise": OptimizationAdvisorAgent(),
            "knowledge": KnowledgeManagerAgent(),
        }
        self.context = ConversationContext()

    async def process(
        self,
        user_input: str,
        session_state: OptimizationState
    ) -> AgentResponse:
        """处理用户输入"""
        intent = await self.classify_intent(user_input)
        agent = self.select_agent(intent)
        return await agent.execute(user_input, session_state, self.context)
```

### 3.2 参数解释 Agent

**职责**：解释工艺参数含义、影响及安全范围。

**工具**：
- `get_parameter_definition(name: str) -> ParamDefinition`
- `get_parameter_impact(name: str, part_type: str) -> ImpactAnalysis`
- `get_safety_bounds(name: str) -> Bounds`
- `explain_coupling(params: list[str]) -> CouplingExplanation`

**系统提示词**：
```
你是注塑工艺参数专家。当用户询问参数时：
1. 解释参数的中文名称和物理含义
2. 说明该参数对产品品质的影响
3. 提示常见的设置范围和注意事项
4. 如果有耦合参数，一并说明

使用专业但易懂的语言，必要时举例说明。
```

### 3.3 异常诊断 Agent

**职责**：分析试模异常（缩水、高误差等）并提供改进建议。

**诊断规则示例**：
```python
DIAGNOSIS_RULES = {
    "shrinkage": {
        "condition": "is_shrink == True or form_error > threshold",
        "causes": ["保压不足", "模温过高", "冷却时间不足"],
        "suggestions": ["提高保压", "降低模温", "延长冷却"]
    },
    "high_form_error": {
        "condition": "form_error > 10 and not is_shrink",
        "causes": ["射速不当", "VP切换不准", "料温异常"],
        "suggestions": ["调整射速", "优化VP点", "检查料温"]
    }
}
```

### 3.4 优化建议 Agent

**职责**：基于历史数据提供优化方向建议。

**核心能力**：
- 分析历史优化趋势
- 识别高潜力探索方向
- 基于 GP 模型不确定性推荐

### 3.5 知识管理 Agent

**职责**：管理和检索工艺知识，支持相似案例查找。

**核心能力**：
- 实验记录向量化存储
- 相似案例检索
- 经验总结生成

## 4. 接口规范

### 4.1 WebSocket 消息格式

```typescript
// Agent 询问请求
interface AskAgentRequest {
    type: "ask_agent";
    data: {
        question: string;        // 用户问题
        context?: string;        // 可选上下文
    };
}

// Agent 响应
interface AgentResponse {
    type: "agent_response";
    data: {
        agent_type: string;      // 响应 Agent 类型
        content: string;         // 响应内容
        suggestions?: string[];  // 可选建议
        references?: Reference[]; // 参考来源
    };
}
```

### 4.2 REST API

```
POST /api/agent/ask
请求体:
{
    "question": "为什么会出现缩水？",
    "part_number": "LS39860A-903",
    "session_id": "optional-session-id"
}

响应:
{
    "agent_type": "diagnose",
    "content": "根据当前参数分析，缩水可能由...",
    "confidence": 0.85,
    "suggestions": [...]
}
```

## 5. 数据结构

### 5.1 Agent 响应

```python
class AgentResponse(BaseModel):
    agent_type: str                    # Agent 类型标识
    content: str                       # 主要响应内容
    confidence: float | None = None    # 置信度 (0-1)
    suggestions: list[str] = []        # 建议列表
    references: list[Reference] = []   # 参考来源
    metadata: dict = {}                # 附加元数据

class Reference(BaseModel):
    type: str                          # "record" | "knowledge" | "rule"
    id: str                            # 引用标识
    description: str                   # 描述
```

### 5.2 对话上下文

```python
class ConversationContext:
    """维护多轮对话上下文"""

    def __init__(self, max_history: int = 10):
        self.history: list[Message] = []
        self.max_history = max_history
        self.session_state: dict = {}

    def add_message(self, role: str, content: str):
        """添加消息到历史"""
        self.history.append(Message(role=role, content=content))
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]
```

## 6. 集成方式

### 6.1 与现有系统集成

在 `OptimizationSession` 中集成 Agent：

```python
class OptimizationSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.state: OptimizationState
        self.orchestrator = AgentOrchestrator()  # 新增

    async def handle_message(self, message: WSMessage):
        if message.type == "ask_agent":
            response = await self.orchestrator.process(
                user_input=message.data["question"],
                session_state=self.state
            )
            await self.send_agent_response(response)
```

### 6.2 前端集成

在 Web 界面添加 Agent 聊天组件：

```html
<!-- Agent 辅助面板 -->
<div class="agent-panel">
    <div class="agent-messages" id="agentMessages"></div>
    <div class="agent-input">
        <input type="text" id="agentQuestion" placeholder="询问工艺问题...">
        <button onclick="app.askAgent()">发送</button>
    </div>
</div>
```

## 7. 开发规范

### 7.1 代码规范

- 所有 Agent 继承 `BaseAgent` 基类
- 工具函数使用 `@tool` 装饰器注册
- 异步接口使用 `async/await`
- 类型注解完整

### 7.2 错误处理

```python
class AgentError(Exception):
    """Agent 错误基类"""
    pass

class ToolExecutionError(AgentError):
    """工具执行错误"""
    pass

class LLMError(AgentError):
    """LLM 调用错误"""
    pass
```

### 7.3 日志规范

```python
import structlog

logger = structlog.get_logger(__name__)

# Agent 执行日志
logger.info(
    "agent_execution",
    agent_type="explainer",
    question=question,
    latency_ms=elapsed,
)
```

## 8. 测试规范

### 8.1 单元测试

```python
@pytest.mark.asyncio
async def test_explainer_agent():
    agent = ParameterExplainerAgent()
    response = await agent.explain("melt_temp", context={})
    assert response.content is not None
    assert response.confidence > 0
```

### 8.2 集成测试

```python
@pytest.mark.asyncio
async def test_orchestrator_integration():
    orchestrator = AgentOrchestrator()
    response = await orchestrator.process(
        "为什么会出现缩水？",
        session_state=mock_state
    )
    assert response.agent_type == "diagnose"
```

## 9. 版本历史

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| 1.0 | 2026-03-11 | 初始版本 |
