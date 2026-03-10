# 注塑成型工艺参数智能推荐系统 - Agent 设计规划

## 1. 项目现状

### 1.1 系统架构

当前系统已具备以下两个版本：

**tkinter GUI 版（原始版）**
- 本地桌面应用，单用户操作
- 功能完整：参数配置、BO优化、Excel导入导出、历史记录管理

**Web 版（新增）**
- FastAPI + WebSocket 架构
- 支持多用户、远程访问
- 实时日志推送、会话恢复

### 1.2 核心模块

```
项目结构
├── 核心算法层
│   ├── config.py              # 件号配置管理
│   ├── optimizer_standard.py  # StandardBO 优化器
│   ├── runner.py              # 实验运行器
│   └── test_functions.py      # 仿真测试函数
│
├── Web 服务层
│   └── web_app/
│       ├── backend/
│       │   ├── app/main.py              # FastAPI 主应用
│       │   ├── app/services/
│       │   │   ├── session_manager.py   # WebSocket 会话管理
│       │   │   └── async_runner.py      # 异步优化运行器
│       │   └── app/models/schemas.py    # Pydantic 数据模型
│       └── frontend/          # 前端界面
│
└── 配置与数据
    ├── configs/               # 件号配置文件
    └── output/                # 实验记录与推荐参数
```

### 1.3 当前能力

| 功能 | tkinter版 | Web版 | 状态 |
|------|-----------|-------|------|
| 件号配置管理 | ✅ | ✅ | 完成 |
| BO参数优化 | ✅ | ✅ | 完成 |
| Human-in-loop | ✅ | ✅ | 完成 |
| 历史记录编辑 | ✅ | ⚠️ | 待完善 |
| Excel导入导出 | ✅ | ⚠️ | 待完善 |
| 收敛曲线可视化 | ✅ | ❌ | 待开发 |
| 多用户支持 | ❌ | ✅ | 完成 |

---

## 2. Agent 化演进目标

### 2.1 愿景

将当前系统演进为**智能工艺助手**，具备：

1. **智能解释**：自动解释工艺参数含义和影响
2. **异常诊断**：分析试模失败原因并提供建议
3. **主动推荐**：基于历史数据主动推荐优化方向
4. **知识沉淀**：将专家经验转化为可复用的规则

### 2.2 Agent 能力矩阵

```
                    当前能力        Phase 1        Phase 2        Phase 3
                    ─────────      ───────        ───────        ───────
参数解释              人工           LLM           多模态         交互式
异常诊断              人工          规则+LLM       智能诊断        预测性
优化建议              BO           BO+启发式      自适应          自主优化
知识管理             Excel         向量库         知识图谱        专家系统
```

---

## 3. Agent 架构设计

### 3.1 总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户交互层                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  Web 前端     │  │  tkinter GUI │  │  API/CLI 接口         │  │
│  │  (React/Vue)  │  │  (本地桌面)   │  │  (第三方集成)          │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
└─────────┼────────────────┼─────────────────────┼──────────────┘
          │                │                     │
          └────────────────┴──────────┬──────────┘
                                      │
                              ┌───────▼───────┐
                              │   Agent 网关   │
                              │  (消息路由)    │
                              └───────┬───────┘
                                      │
┌─────────────────────────────────────┼─────────────────────────────┐
│                            Agent 核心层                            │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                    中央协调器 (Orchestrator)                 │  │
│  │  • 意图识别  • 任务分发  • 状态管理  • 上下文维护           │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌─────────┐ │
│  │ 参数解释Agent │ │ 异常诊断Agent │ │ 优化建议Agent │ │ 知识Agent│ │
│  │              │ │              │ │              │ │         │ │
│  │ • 参数含义   │ │ • 缩水分析   │ │ • 方向建议   │ │ • 检索   │ │
│  │ • 影响分析   │ │ • 异常检测   │ │ • 边界探索   │ │ • 总结   │ │
│  │ • 风险提示   │ │ • 改进建议   │ │ • 参数推荐   │ │ • 沉淀   │ │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └────┬────┘ │
└─────────┼────────────────┼────────────────┼──────────────┼──────┘
          │                │                │              │
          └────────────────┴────────────────┴──────┬───────┘
                                                   │
                                          ┌────────▼────────┐
                                          │    工具层        │
                                          │  (Tools/MCP)    │
                                          └────────┬────────┘
                                                   │
┌──────────────────────────────────────────────────┼──────────────┐
│                                               基础设施层          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────▼──────────┐   │
│  │   BO 优化器   │  │   LLM 服务   │  │    向量数据库        │   │
│  │  (BoTorch)   │  │ (Claude API) │  │  (Chroma/PGVector)  │   │
│  └──────────────┘  └──────────────┘  └─────────────────────┘   │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐   │
│  │   关系数据库  │  │   文件存储   │  │    配置中心          │   │
│  │  (SQLite/PG) │  │   (本地/云)  │  │   (件号配置)         │   │
│  └──────────────┘  └──────────────┘  └─────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 Agent 详细设计

#### 3.2.1 中央协调器 (Orchestrator)

```python
class AgentOrchestrator:
    """Agent 协调器 - 管理所有 Agent 的协作"""

    def __init__(self):
        self.agents = {
            "parameter_explainer": ParameterExplainerAgent(),
            "anomaly_detector": AnomalyDetectorAgent(),
            "optimization_advisor": OptimizationAdvisorAgent(),
            "knowledge_manager": KnowledgeManagerAgent(),
        }
        self.context = ConversationContext()

    async def process(self, user_input: str, session_state: dict) -> AgentResponse:
        """处理用户输入，协调 Agent 响应"""
        # 1. 意图识别
        intent = await self.classify_intent(user_input)

        # 2. 选择 Agent
        agent = self.select_agent(intent)

        # 3. 执行并返回
        return await agent.execute(user_input, session_state, self.context)
```

#### 3.2.2 参数解释 Agent

```python
class ParameterExplainerAgent:
    """参数解释 Agent - 解释工艺参数含义和影响"""

    TOOLS = [
        "get_parameter_definition",    # 获取参数定义
        "get_parameter_impact",        # 获取参数影响分析
        "get_safety_bounds",           # 获取安全边界
        "explain_coupling_effect",     # 解释耦合效应
    ]

    SYSTEM_PROMPT = """
    你是注塑工艺参数专家。当用户询问参数时：
    1. 解释参数的中文名称和物理含义
    2. 说明该参数对产品品质的影响
    3. 提示常见的设置范围和注意事项
    4. 如果有耦合参数，一并说明

    使用专业但易懂的语言，必要时举例说明。
    """

    async def explain(self, param_name: str, context: dict) -> str:
        # 1. 从知识库获取参数定义
        definition = await self.tools.get_parameter_definition(param_name)

        # 2. 基于当前件号分析影响
        impact = await self.tools.get_parameter_impact(
            param_name, context["part_number"]
        )

        # 3. 调用 LLM 生成解释
        return await self.llm.generate_explanation(definition, impact)
```

#### 3.2.3 异常诊断 Agent

```python
class AnomalyDetectorAgent:
    """异常诊断 Agent - 分析试模异常并提供建议"""

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

    async def diagnose(self, record: ExperimentRecord) -> DiagnosisReport:
        """诊断单条实验记录"""
        # 1. 规则匹配
        matched_rules = self.apply_rules(record)

        # 2. LLM 深度分析
        analysis = await self.llm.analyze(record, matched_rules)

        # 3. 生成建议
        suggestions = await self.generate_suggestions(record, analysis)

        return DiagnosisReport(
            record=record,
            matched_rules=matched_rules,
            analysis=analysis,
            suggestions=suggestions
        )
```

#### 3.2.4 优化建议 Agent

```python
class OptimizationAdvisorAgent:
    """优化建议 Agent - 基于历史数据提供优化建议"""

    async def advise(self, session_state: OptimizationState) -> Advice:
        """基于当前状态提供优化建议"""
        # 1. 分析历史趋势
        trend = self.analyze_trend(session_state.all_records)

        # 2. 识别探索方向
        directions = self.identify_exploration_directions(session_state)

        # 3. 生成建议
        return Advice(
            current_best=session_state.best_form_error,
            trend=trend,
            recommended_directions=directions,
            rationale="基于GP模型的不确定性分析和历史数据模式"
        )

    def identify_exploration_directions(self, state: OptimizationState) -> List[Direction]:
        """识别值得探索的参数方向"""
        # 基于 GP 模型的不确定性进行探索
        gp_model = self.train_gp_model(state.X_train, state.y_train)

        # 计算各参数的敏感度
        sensitivities = self.calculate_sensitivity(gp_model)

        # 推荐高潜力方向
        return sorted(sensitivities, key=lambda x: x.potential, reverse=True)[:3]
```

#### 3.2.5 知识管理 Agent

```python
class KnowledgeManagerAgent:
    """知识管理 Agent - 管理和检索工艺知识"""

    def __init__(self):
        self.vector_store = ChromaVectorStore()
        self.experience_db = ExperienceDatabase()

    async def retrieve_similar_cases(
        self,
        part_number: str,
        params: Dict[str, float],
        top_k: int = 5
    ) -> List[SimilarCase]:
        """检索相似案例"""
        # 1. 向量检索
        query_vector = self.encode_params(params)
        similar_cases = await self.vector_store.search(
            collection=part_number,
            query=query_vector,
            top_k=top_k
        )

        # 2. 过滤和排序
        return self.filter_and_rank(similar_cases, params)

    async def summarize_experience(
        self,
        records: List[ExperimentRecord]
    ) -> ExperienceSummary:
        """总结实验经验"""
        # 1. 提取成功模式
        success_patterns = self.extract_patterns(
            [r for r in records if r.form_error < 5]
        )

        # 2. 提取失败教训
        failure_lessons = self.extract_patterns(
            [r for r in records if r.is_shrink or r.form_error > 50]
        )

        # 3. LLM 生成总结
        return await self.llm.summarize(success_patterns, failure_lessons)
```

---

## 4. 实施路线图

### 4.1 Phase 1: 基础 Agent 能力 (4-6周)

**目标**：实现核心 Agent 的基础功能

| 周 | 任务 | 产出 |
|----|------|------|
| 1-2 | 搭建 Agent 框架 | Orchestrator + 消息总线 |
| 2-3 | 参数解释 Agent | 支持所有工艺参数的解释 |
| 3-4 | 异常诊断 Agent | 缩水、高误差等常见异常诊断 |
| 4-5 | 知识库搭建 | 向量数据库 + 基础问答 |
| 5-6 | 集成与测试 | 前端集成 + 端到端测试 |

### 4.2 Phase 2: 智能增强 (4-6周)

**目标**：提升 Agent 的智能化水平

- 优化建议 Agent 实现
- 历史案例自动学习
- 主动式建议推送
- 多轮对话能力

### 4.3 Phase 3: 高级功能 (6-8周)

**目标**：实现高级智能化功能

- 预测性分析（提前预警）
- 多目标优化支持
- 跨件号知识迁移
- 专家系统沉淀

---

## 5. 技术实现要点

### 5.1 LLM 集成

```python
# 配置 Claude API
from anthropic import AsyncAnthropic

class LLMService:
    def __init__(self):
        self.client = AsyncAnthropic()

    async def generate(
        self,
        system_prompt: str,
        messages: List[Message],
        tools: Optional[List[Tool]] = None
    ) -> LLMResponse:
        """调用 LLM 生成响应"""
        response = await self.client.messages.create(
            model="claude-3-sonnet-20241022",
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            tools=tools
        )
        return self.parse_response(response)
```

### 5.2 向量数据库

```python
# 使用 ChromaDB 存储工艺知识
import chromadb

class VectorStore:
    def __init__(self):
        self.client = chromadb.PersistentClient(path="./knowledge_db")

    def add_experience(self, record: ExperimentRecord):
        """添加实验经验到知识库"""
        collection = self.client.get_or_create_collection(
            name=record.part_number
        )

        # 编码实验记录
        embedding = self.encode_record(record)

        collection.add(
            embeddings=[embedding],
            documents=[self.format_record(record)],
            metadatas=[{
                "form_error": record.form_error,
                "is_shrink": record.is_shrink,
                "stage": record.stage
            }],
            ids=[str(record.timestamp)]
        )
```

### 5.3 Agent 与现有系统集成

```python
# 扩展现有的 WebSocket 会话
class OptimizationSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.agent_orchestrator = AgentOrchestrator()

    async def handle_message(self, message: WSMessage):
        """处理 WebSocket 消息"""
        # 原有优化逻辑...

        # 新增：Agent 辅助
        if message.type == "ask_agent":
            response = await self.agent_orchestrator.process(
                user_input=message.data["question"],
                session_state=self.state
            )
            await self.send_agent_response(response)
```

---

## 6. 评估指标

### 6.1 Agent 效果评估

| 指标 | 说明 | 目标值 |
|------|------|--------|
| 参数解释准确率 | 用户对参数解释的满意度 | > 90% |
| 异常诊断准确率 | 诊断结果与实际情况的匹配度 | > 85% |
| 建议采纳率 | 用户采纳 Agent 建议的比例 | > 70% |
| 对话轮次减少 | 相比人工咨询减少的轮次 | > 50% |

### 6.2 系统性能评估

| 指标 | 说明 | 目标值 |
|------|------|--------|
| 响应延迟 | Agent 响应时间 | < 2s |
| 并发用户 | 同时在线用户 | > 20 |
| 知识库命中率 | 相似案例检索成功率 | > 80% |

---

## 7. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| LLM 幻觉 | 提供错误工艺建议 | 规则校验 + 人工确认机制 |
| 知识库覆盖不足 | 新件号无法提供建议 | 冷启动策略 + 专家介入 |
| 响应延迟高 | 用户体验差 | 缓存 + 异步预加载 |
| 数据隐私 | 工艺参数泄露 | 本地部署 + 数据脱敏 |

---

## 8. 附录

### 8.1 相关文件

| 文件路径 | 说明 |
|----------|------|
| `web_app/backend/app/services/async_runner.py` | 异步优化运行器 |
| `web_app/backend/app/services/session_manager.py` | WebSocket 会话管理 |
| `web_app/backend/app/models/schemas.py` | 数据模型定义 |
| `optimizer_standard.py` | StandardBO 优化器 |
| `test_functions.py` | 仿真测试函数 |

### 8.2 技术栈

- **后端**: FastAPI, WebSocket, Uvicorn
- **Agent 框架**: 自定义 (FastAPI + LLM)
- **LLM**: Claude API (Anthropic)
- **向量数据库**: ChromaDB / PGVector
- **前端**: HTML + Vanilla JS (可升级至 React/Vue)

---

*文档版本: 1.0*
*更新时间: 2026-03-10*
*作者: Claude Sonnet 4.6*
