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
