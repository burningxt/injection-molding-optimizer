# 注塑成型工艺参数智能推荐系统 - BO 模型解释引擎设计规划

## 版本历史

| 版本 | 日期 | 说明 |
|------|------|------|
| 3.0 | 2026-03-13 | 务实重构版：从多 Agent 架构简化为 BO 白盒化解释 |
| 2.0 | 2026-03-11 | 原多 Agent 架构设计（过于复杂，暂不实现） |

---

## 1. 概述

### 1.1 当前系统现状

**已有能力：**
- 基于 BoTorch 的贝叶斯优化核心（SingleTaskGP + qLogExpectedImprovement）
- Web 界面支持人机交互迭代优化
- 实验记录保存与续跑机制

**数据现状：**
- 仅有工艺参数（温度、压力、速度等）和结果（面型误差、是否缩水）
- 历史数据量有限（单件号几十到几百条）
- **缺乏**：人机料法环测全维度数据、大量跨件号历史数据

### 1.2 设计调整原因

原多 Agent 架构（异常诊断、优化建议、知识管理）过于超前：
- 需要 LLM、向量数据库等复杂基础设施
- 在没有足够数据支撑的情况下，难以产生实际价值
- 实施周期过长（16-20周）

### 1.3 务实目标

**唯一高价值功能：BO 模型白盒化解释**

让工程师理解"为什么推荐这组参数"——将 BO 模型的内部概率统计机理可视化呈现。

---

## 2. 核心解释维度

### 2.1 预测质量地图（Predictive Quality Map）

- 展示 GP 模型对参数空间的预测分布
- 工程师可以看到：推荐点附近是预测的"好区域"

### 2.2 采集函数分析（Acquisition Analysis）

- 展示采集函数（EI）在参数空间的分布
- 解释：为什么选这个点（采集价值最高）

### 2.3 不确定性可视化（Uncertainty Visualization）

- 展示模型对各区域的不确定性估计
- 解释：推荐点平衡了探索（高不确定性）和利用（高预测值）

### 2.4 参数敏感性分析（Parameter Sensitivity）

- 基于 GP 核函数长度尺度，分析各参数对结果的影响程度
- 帮助工程师理解：调整哪个参数最可能改善结果

### 2.5 优化轨迹回顾（Optimization Trajectory）

- 展示已探索点在参数空间的分布
- 说明：推荐点是如何基于已有实验选择的

---

## 3. 简化架构设计

### 3.1 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        Web 前端                               │
│                                                             │
│   ┌─────────────────────────────────────────────────────┐  │
│   │                  主优化界面                          │  │
│   │   - 参数推荐卡片                                     │  │
│   │   - 实验记录表格                                     │  │
│   └─────────────────────────────────────────────────────┘  │
│                                                             │
│   ┌─────────────────────────────────────────────────────┐  │
│   │  洞察面板 (标签页，替换原日志区，保持原尺寸)          │  │
│   │  ┌──────┬──────┬──────┬──────┬──────┐               │  │
│   │  │ 日志 │ 预测 │ 采集 │ 敏感 │ 轨迹 │               │  │
│   │  ├──────┴──────┴──────┴──────┴──────┤               │  │
│   │  │         可视化内容区域             │               │  │
│   │  └───────────────────────────────────┘               │  │
│   └─────────────────────────────────────────────────────┘  │
│                                                             │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                      解释引擎层                               │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              BOExplainer (单类)                       │  │
│  │                                                      │  │
│  │  - analyze_prediction_map()   → 预测质量热力图        │  │
│  │  - analyze_acquisition()      → 采集函数分析          │  │
│  │  - analyze_uncertainty()      → 不确定性可视化        │  │
│  │  - analyze_sensitivity()      → 参数敏感性            │  │
│  │  - analyze_trajectory()       → 优化轨迹              │  │
│  │                                                      │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                      BO 核心层                                │
│                                                             │
│  ┌─────────────────┐  ┌─────────────────────────────────┐   │
│  │   SingleTaskGP   │  │   ExperimentRunner              │   │
│  │   (代理模型)     │  │   (数据管理)                     │   │
│  └─────────────────┘  └─────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 模块位置

```
src/injection_molding/
├── core/
│   ├── bayesian/
│   │   ├── base.py
│   │   └── standard.py          # 现有：StandardBOOptimizer
│   └── explainer/               # 新增：解释引擎
│       ├── __init__.py
│       ├── base.py              # BOExplainer 基类
│       ├── visualizer.py        # 可视化数据生成
│       └── sensitivity.py       # 敏感性分析
├── interfaces/
│   └── web/
│       └── main.py              # 新增：/explain 接口
└── domain/
    └── models.py                # 新增：ExplanationResult 模型
```

---

## 4. 核心实现设计

### 4.1 BOExplainer 类

```python
class BOExplainer:
    """贝叶斯优化解释引擎 - 将 BO 模型内部状态白盒化"""

    def __init__(self, model: SingleTaskGP, X_train: torch.Tensor, y_train: torch.Tensor):
        self.model = model
        self.X_train = X_train
        self.y_train = y_train

    def explain_current_recommendation(
        self,
        candidate: torch.Tensor,
        acq_value: float
    ) -> ExplanationResult:
        """解释当前推荐参数背后的机理"""
        return ExplanationResult(
            prediction=self._explain_prediction(candidate),
            acquisition=self._explain_acquisition(candidate, acq_value),
            uncertainty=self._explain_uncertainty(candidate),
            sensitivity=self._analyze_sensitivity(),
            trajectory=self._analyze_trajectory()
        )
```

### 4.2 可视化数据结构

```python
class ExplanationResult(BaseModel):
    """BO 解释结果"""
    prediction: PredictionExplanation
    acquisition: AcquisitionExplanation
    uncertainty: UncertaintyExplanation
    sensitivity: SensitivityAnalysis
    trajectory: TrajectoryAnalysis


class PredictionExplanation(BaseModel):
    """预测质量解释"""
    mean_prediction: float
    confidence_interval: Tuple[float, float]
    relative_to_best: str


class AcquisitionExplanation(BaseModel):
    """采集函数解释"""
    ei_value: float
    exploration_ratio: float
    explanation: str


class SensitivityAnalysis(BaseModel):
    """参数敏感性分析"""
    rankings: List[ParamSensitivity]
    interpretation: str
```

### 4.3 Web 接口

```python
@router.post("/explain")
async def explain_recommendation(
    session_id: str,
    candidate_index: int = 0
) -> ExplanationResult:
    """获取当前推荐参数的详细解释"""
    session = session_manager.get(session_id)
    explainer = BOExplainer(
        model=session.bo_model,
        X_train=session.X_train,
        y_train=session.y_train
    )
    candidate = session.current_recommendations[candidate_index]
    return explainer.explain_current_recommendation(...)
```

---

## 5. 前端设计（标签页方案）

### 5.1 布局方案

**将原有日志区域替换为洞察面板**，保持原有大小和高度，采用标签页组织内容：

```
┌─────────────────────────────────────────────────────────────────┐
│  洞察面板                                          [设置▼]     │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────┬──────────┬──────────┬──────────┬──────────┐      │
│  │ 运行日志 │ 预测质量 │ 采集函数 │ 参数敏感 │ 优化轨迹 │      │
│  ├──────────┴──────────┴──────────┴──────────┴──────────┤      │
│  │                                                     │      │
│  │                    标签页内容区                      │      │
│  │                  (与日志区等高)                      │      │
│  │                                                     │      │
│  └─────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 各标签页内容

| 标签 | 内容 |
|------|------|
| **运行日志** | 保持现有日志功能不变 |
| **预测质量** | 2D 热力图展示 GP 模型预测的质量分布 |
| **采集函数** | EI（Expected Improvement）分布热力图 |
| **参数敏感** | 水平条形图展示各参数重要性排序 |
| **优化轨迹** | 散点图展示已探索点在参数空间的分布 |

---

## 6. 分阶段实施路线图

### Phase 1: 基础框架（可验证）

**目标**：建立解释引擎的基础框架，可在 UI 上看到第一个解释标签

**验收标准**：
- [ ] 启动优化后，可以在洞察面板切换到"参数敏感"标签
- [ ] 看到基于 GP 长度尺度的参数重要性排序列表（文字形式）
- [ ] 即使数据不足也能显示友好提示

**任务清单**：
1. 创建 `src/injection_molding/core/explainer/` 目录结构
2. 在 `domain/models.py` 添加 `ExplanationResult` 等基础模型
3. 实现 `SensitivityAnalyzer` 类（仅长度尺度提取）
4. 实现基础 `BOExplainer` 类（仅敏感性分析）
5. 添加 `/api/explain/sensitivity` 接口
6. 前端：将日志区改为标签页面板
7. 前端：添加"参数敏感"标签页（仅显示文字排序）

**预计时间**：3-4 天

---

### Phase 2: 预测质量热力图

**目标**：实现预测质量可视化，工程师能看到"好区域"

**验收标准**：
- [ ] 在"预测质量"标签页看到热力图
- [ ] 热力图显示 GP 预测的 form_error 分布
- [ ] 可以切换 X/Y 轴参数（默认选择敏感性最高的两个）
- [ ] 白色点显示已探索点，红色星显示当前推荐点

**任务清单**：
1. 实现 `ExplanationVisualizer.generate_prediction_heatmap()`
2. 添加 `/api/explain/prediction-map` 接口
3. 前端：集成 ECharts 热力图组件
4. 前端：添加参数选择下拉框
5. 添加坐标转换（归一化 → 物理值）

**预计时间**：4-5 天

---

### Phase 3: 采集函数与不确定性

**目标**：展示 EI 分布和不确定性，解释为什么选这个点

**验收标准**：
- [ ] "采集函数"标签页显示 EI 热力图
- [ ] 显示探索/利用比例进度条
- [ ] 显示自然语言解释（如"以探索为主"）
- [ ] "不确定性"标签页显示方差热力图

**任务清单**：
1. 实现 `generate_acquisition_heatmap()`
2. 实现 `_explain_acquisition()` 方法（探索/利用分解）
3. 实现 `generate_uncertainty_heatmap()`
4. 添加相应 API 接口
5. 前端：添加两个标签页和可视化

**预计时间**：4-5 天

---

### Phase 4: 优化轨迹

**目标**：展示优化历史，帮助理解推荐逻辑

**验收标准**：
- [ ] "优化轨迹"标签页显示散点图
- [ ] 点按迭代轮次着色
- [ ] 连线显示优化顺序
- [ ] 悬停显示具体参数值和 form_error

**任务清单**：
1. 实现 `_analyze_trajectory()` 方法
2. 添加 `/api/explain/trajectory` 接口
3. 前端：集成散点图组件
4. 添加连线动画效果

**预计时间**：3-4 天

---

### Phase 5: 工程完善

**目标**：提升可用性和鲁棒性

**验收标准**：
- [ ] 冷启动时（数据<10条）显示"数据不足"提示
- [ ] 解释结果缓存，避免重复计算
- [ ] 导出解释报告功能
- [ ] 性能优化（热力图计算 < 1s）

**任务清单**：
1. 添加数据量检查逻辑
2. 实现解释结果缓存机制
3. 添加导出图片/PDF功能
4. 优化热力图计算（批量处理、降采样）
5. 完善错误处理和边界情况

**预计时间**：4-5 天

---

## 7. 与原设计的对比

| 维度 | 原设计 | 新设计 |
|------|--------|--------|
| **核心功能** | 4个Agent（解释、诊断、建议、知识） | 1个解释引擎 |
| **技术栈** | LLM、向量数据库、Agent框架 | 纯数值计算 + 可视化 |
| **基础设施** | 需额外部署 | 复用现有BO模型 |
| **实施周期** | 16-20周 | 3-4周（分5个阶段） |
| **数据依赖** | 需要大量历史数据 | 仅需当前BO模型状态 |
| **核心价值** | 模糊的智能辅助 | 清晰的白盒化解释 |
| **可验证性** | 难以量化 | 每阶段有明确验收标准 |

---

## 8. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| GP 模型复杂度高，解释困难 | 工程师看不懂 | 用自然语言摘要 + 可视化，避免公式 |
| 高维参数空间可视化困难 | 只能看2D切片 | 默认展示最敏感的两个参数 |
| 冷启动时数据不足 | 解释不准确 | 数据量<10时显示"数据不足，解释可能不准确" |
| 热力图计算慢 | 用户体验差 | 降采样、缓存、异步计算 |

---

## 9. 验收测试用例

### 9.1 Phase 1 验收测试

```python
def test_sensitivity_analysis():
    """测试敏感性分析"""
    # 1. 启动优化，运行至少一轮
    # 2. 调用 /api/explain/sensitivity
    # 3. 验证返回结果包含 rankings 列表
    # 4. 验证 rankings 按 sensitivity_score 排序
    # 5. 验证每个 ranking 包含 param_name、length_scale、interpretation
```

### 9.2 Phase 2 验收测试

```python
def test_prediction_heatmap():
    """测试预测质量热力图"""
    # 1. 启动优化，运行至少一轮
    # 2. 调用 /api/explain/prediction-map?x_param=0&y_param=1
    # 3. 验证返回 HeatmapData 结构
    # 4. 验证 values 是二维数组
    # 5. 验证 x_values 和 y_values 长度匹配 values 维度
```

---

*文档版本: 3.0 - 务实重构版*
*更新时间: 2026-03-13*
