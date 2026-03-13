"""Pydantic 数据模型"""

from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class ParamType(str, Enum):
    """参数类型"""
    FIXED = "fixed"
    RANGE = "range"
    SET = "set"
    CHOICE = "choice"
    MIXED = "mixed"


class ParamSpec(BaseModel):
    """参数规格"""
    name: str
    type: ParamType
    targets: Optional[List[str]] = None
    # range 类型
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    # fixed 类型
    value: Optional[Union[float, int, str]] = None
    # set 类型
    values: Optional[List[Union[float, int]]] = None
    # choice/mixed 类型
    options: Optional[List[Dict[str, Any]]] = None
    configs: Optional[List[Dict[str, Any]]] = None


class PartConfig(BaseModel):
    """件号配置"""
    name: str
    fixed: Dict[str, Any] = Field(default_factory=dict)
    tunable: List[ParamSpec] = Field(default_factory=list)
    ui_order: Optional[List[str]] = None


class AlgoSettings(BaseModel):
    """算法设置"""
    n_init: int = Field(default=20, ge=1, le=100)
    n_iter: int = Field(default=10, ge=1, le=100)
    batch_size: int = Field(default=4, ge=1, le=20)
    shrink_threshold: float = Field(default=30.0, ge=0)
    mode: Literal["auto", "manual"] = "manual"
    init_mode: Literal["auto", "manual"] = "auto"
    init_excel_path: Optional[str] = None


class ExperimentRecord(BaseModel):
    """实验记录"""
    stage: str  # "init" 或 "iter_1", "iter_2" ...
    form_error: Optional[float] = None
    is_shrink: bool = False
    params: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)


class OptimizationState(BaseModel):
    """优化状态（用于 checkpoint）"""
    session_id: str
    part_config: PartConfig
    algo_settings: AlgoSettings

    # 运行状态
    stage: str = "init"  # init, iter_X, completed
    iteration: int = 0
    all_records: List[ExperimentRecord] = Field(default_factory=list)
    pending_indices: List[int] = Field(default_factory=list)

    # BO 训练数据
    X_train: List[List[float]] = Field(default_factory=list)
    y_train: List[float] = Field(default_factory=list)
    Ph_min_safe: Dict[Union[str, int, float], float] = Field(default_factory=dict)

    # BO 模型状态（用于解释引擎）
    bo_model_state: Optional[Dict[str, Any]] = None  # 序列化的 GP 模型状态
    param_names: List[str] = Field(default_factory=list)  # 参数名称列表

    # 当前批次
    current_recommendations: List[Dict[str, Any]] = Field(default_factory=list)

    # 统计信息
    best_form_error: Optional[float] = None
    best_params: Optional[Dict[str, Any]] = None

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


# WebSocket 消息模型

class WSMessageType(str, Enum):
    """WebSocket 消息类型"""
    # 客户端 -> 服务器
    START_OPTIMIZATION = "start_optimization"
    STOP_OPTIMIZATION = "stop_optimization"
    SAVE_AND_EXIT = "save_and_exit"
    SUBMIT_EVALUATION = "submit_evaluation"
    UPDATE_CONFIG = "update_config"

    # 服务器 -> 客户端
    OPTIMIZATION_STARTED = "optimization_started"
    OPTIMIZATION_STOPPED = "optimization_stopped"
    OPTIMIZATION_COMPLETED = "optimization_completed"
    PARAMS_READY = "params_ready"
    LOG_MESSAGE = "log_message"
    STATE_UPDATE = "state_update"
    ERROR = "error"
    HISTORY_RECORDS = "history_records"
    CONVERGENCE_DATA = "convergence_data"
    NEW_RECORD = "new_record"


class WSMessage(BaseModel):
    """WebSocket 消息"""
    type: WSMessageType
    data: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class StartOptimizationData(BaseModel):
    """开始优化请求数据"""
    part_number: str
    algo_settings: AlgoSettings


class SubmitEvaluationData(BaseModel):
    """提交评价数据"""
    record_index: int
    form_error: float
    is_shrink: bool = False


class LogMessageData(BaseModel):
    """日志消息数据"""
    level: Literal["info", "warning", "error", "debug"] = "info"
    message: str


# ============================================================================
# BO 解释引擎模型 (Phase 1)
# ============================================================================

class ParamSensitivity(BaseModel):
    """单个参数的敏感性信息"""
    param_name: str
    length_scale: float
    sensitivity_score: float
    importance_rank: int
    interpretation: str


class SensitivityAnalysis(BaseModel):
    """参数敏感性分析结果"""
    rankings: List[ParamSensitivity] = Field(default_factory=list)
    interpretation: str = ""
    kernel_type: str = "Unknown"
    is_fallback: bool = False
    fallback_reason: Optional[str] = None


class PredictionExplanation(BaseModel):
    """预测质量解释"""
    mean_prediction: float = 0.0
    confidence_interval: tuple[float, float] = (0.0, 0.0)
    std: float = 0.0
    relative_to_best: str = ""


class AcquisitionExplanation(BaseModel):
    """采集函数解释"""
    ei_value: float = 0.0
    exploration_ratio: float = 0.0
    exploitation_ratio: float = 0.0
    explanation: str = ""


class UncertaintyExplanation(BaseModel):
    """不确定性解释"""
    variance: float = 0.0
    std: float = 0.0
    relative_level: float = 0.0
    level_description: str = ""
    min_distance_to_train: float = 0.0
    avg_distance_to_train: float = 0.0
    description: str = ""


class TrajectoryPoint(BaseModel):
    """优化轨迹点"""
    index: int
    params: List[float]
    form_error: float
    iteration: int


class TrajectoryAnalysis(BaseModel):
    """优化轨迹分析"""
    points: List[TrajectoryPoint] = Field(default_factory=list)
    total_points: int = 0
    best_point_index: int = 0
    improvement_indices: List[int] = Field(default_factory=list)
    description: str = ""


class HeatmapData(BaseModel):
    """热力图数据"""
    x_param: str
    y_param: str
    x_param_idx: int
    y_param_idx: int
    x_values: List[float]
    y_values: List[float]
    values: List[List[float]]


class ExplanationResult(BaseModel):
    """BO 解释结果"""
    prediction: PredictionExplanation = Field(default_factory=PredictionExplanation)
    acquisition: AcquisitionExplanation = Field(default_factory=AcquisitionExplanation)
    uncertainty: UncertaintyExplanation = Field(default_factory=UncertaintyExplanation)
    sensitivity: SensitivityAnalysis = Field(default_factory=SensitivityAnalysis)
    trajectory: TrajectoryAnalysis = Field(default_factory=TrajectoryAnalysis)
