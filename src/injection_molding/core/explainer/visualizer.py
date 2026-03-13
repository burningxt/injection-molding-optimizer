"""解释可视化数据生成模块 - 框架"""

import torch
from typing import List, Optional
from botorch.models import SingleTaskGP


class ExplanationVisualizer:
    """生成用于前端可视化的数据 - 框架"""

    def __init__(
        self,
        model: SingleTaskGP,
        X_train: torch.Tensor,
        y_train: torch.Tensor,
        param_names: Optional[List[str]] = None,
    ):
        self.model = model
        self.X_train = X_train
        self.y_train = y_train
        self.param_names = param_names or [f"param_{i}" for i in range(X_train.shape[1])]
        self.d = X_train.shape[1]
