"""BOExplainer - 贝叶斯优化解释引擎基类"""

import torch
from typing import Optional, List
from botorch.models import SingleTaskGP

from ...domain.models import ExplanationResult
from .sensitivity import SensitivityAnalyzer
from .prediction_viz import PredictionVisualizer


class BOExplainer:
    """贝叶斯优化解释引擎 - 将 BO 模型内部状态白盒化"""

    def __init__(
        self,
        model: SingleTaskGP,
        X_train: torch.Tensor,
        y_train: torch.Tensor,
        param_names: Optional[List[str]] = None,
    ):
        """
        Args:
            model: 训练好的 SingleTaskGP 模型
            X_train: 训练输入数据 (已归一化到 [0,1])
            y_train: 训练输出数据
            param_names: 参数名称列表
        """
        self.model = model
        self.model.eval()
        self.X_train = X_train
        self.y_train = y_train
        self.param_names = param_names or [f"param_{i}" for i in range(X_train.shape[1])]
        self.d = X_train.shape[1]

        # 初始化子模块
        self.sensitivity_analyzer = SensitivityAnalyzer(model, param_names)
        self.prediction_visualizer = PredictionVisualizer(
            model, X_train, y_train, param_names
        )
