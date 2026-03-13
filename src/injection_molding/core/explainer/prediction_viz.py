"""预测质量可视化模块 - 生成GP模型预测热力图数据"""

import torch
import numpy as np
from typing import Optional, List, Dict, Any, Tuple
from botorch.models import SingleTaskGP

from ...domain.models import PredictionHeatmapData


class PredictionVisualizer:
    """基于GP模型的预测质量可视化器

    生成2D热力图展示GP模型对form_error的预测分布，帮助工程师理解：
    - 参数空间中的质量分布
    - 已探索区域与未探索区域的对比
    - 当前推荐点在参数空间中的位置
    """

    def __init__(
        self,
        model: SingleTaskGP,
        X_train: torch.Tensor,
        y_train: torch.Tensor,
        param_names: Optional[List[str]] = None,
        y_mean: Optional[float] = None,
        y_std: Optional[float] = None,
    ):
        """
        Args:
            model: 训练好的SingleTaskGP模型
            X_train: 训练输入数据(已归一化到[0,1])
            y_train: 训练输出数据(已标准化)
            param_names: 参数名称列表
            y_mean: y标准化时的均值(用于反标准化)
            y_std: y标准化时的标准差(用于反标准化)
        """
        self.model = model
        self.model.eval()
        self.X_train = X_train
        self.y_train = y_train
        self.param_names = param_names or [f"param_{i}" for i in range(X_train.shape[1])]
        self.d = X_train.shape[1]
        self.y_mean = y_mean or 0.0
        self.y_std = y_std or 1.0

    def generate_heatmap(
        self,
        x_param_idx: int,
        y_param_idx: int,
        grid_size: int = 50,
        fixed_values: Optional[torch.Tensor] = None
    ) -> PredictionHeatmapData:
        """生成2D热力图数据

        Args:
            x_param_idx: X轴参数索引
            y_param_idx: Y轴参数索引
            grid_size: 网格大小(默认50x50)
            fixed_values: 其他参数的固定值(默认为训练数据均值)

        Returns:
            PredictionHeatmapData: 热力图数据结构
        """
        # 参数索引有效性检查
        if x_param_idx < 0 or x_param_idx >= self.d:
            raise ValueError(f"x_param_idx {x_param_idx} out of range [0, {self.d})")
        if y_param_idx < 0 or y_param_idx >= self.d:
            raise ValueError(f"y_param_idx {y_param_idx} out of range [0, {self.d})")
        if x_param_idx == y_param_idx:
            raise ValueError("x_param_idx and y_param_idx must be different")

        # 确定固定值(其他参数使用训练数据均值)
        if fixed_values is None:
            fixed_values = self.X_train.mean(dim=0)
        else:
            fixed_values = torch.as_tensor(fixed_values, dtype=torch.double)

        # 创建2D网格
        x_values_norm = torch.linspace(0, 1, grid_size, dtype=torch.double)
        y_values_norm = torch.linspace(0, 1, grid_size, dtype=torch.double)

        # 生成网格点
        grid_x, grid_y = torch.meshgrid(x_values_norm, y_values_norm, indexing='xy')
        grid_points = torch.stack([grid_x.flatten(), grid_y.flatten()], dim=-1)  # [grid_size^2, 2]

        # 构建完整参数向量
        X_grid = self._build_full_params(grid_points, x_param_idx, y_param_idx, fixed_values)

        # GP预测(批处理)
        with torch.no_grad():
            posterior = self.model.posterior(X_grid)
            mean_std = posterior.mean.squeeze(-1)  # [grid_size^2]
            var_std = posterior.variance.squeeze(-1)  # [grid_size^2]

        # 检查GP预测结果
        if torch.isnan(mean_std).any():
            print(f"[PredictionVisualizer] mean_std contains NaN after GP prediction")
            raise ValueError("GP prediction mean contains NaN")
        if torch.isnan(var_std).any():
            print(f"[PredictionVisualizer] var_std contains NaN after GP prediction")
            raise ValueError("GP prediction variance contains NaN")

        # 反标准化(从标准化空间回到对数空间)
        mean_log = mean_std * self.y_std + self.y_mean
        # var在对数变换后近似处理: var_log ≈ var_std * y_std^2
        var_log = var_std * (self.y_std ** 2)

        # 检查反标准化后的值
        if torch.isnan(mean_log).any():
            print(f"[PredictionVisualizer] mean_log contains NaN: y_mean={self.y_mean}, y_std={self.y_std}")
            raise ValueError("mean_log contains NaN")

        # 逆对数变换: 从-log(form_error)回到form_error
        # train_Y_log = -log(fe_values + 1e-6)
        # 所以 fe = exp(-mean_log) - 1e-6
        mean_fe = torch.exp(-mean_log) - 1e-6

        # 检查指数变换后的值
        if torch.isnan(mean_fe).any():
            print(f"[PredictionVisualizer] mean_fe contains NaN: mean_log min={mean_log.min()}, max={mean_log.max()}")
            raise ValueError("mean_fe contains NaN")

        # 方差也通过误差传播近似转换
        # d(fe)/d(mean_log) = -exp(-mean_log)
        # var_fe ≈ (exp(-mean_log))^2 * var_log
        var_fe = torch.exp(-2 * mean_log) * var_log

        # reshape到2D网格 [grid_size, grid_size]
        predictions = mean_fe.reshape(grid_size, grid_size).cpu().numpy()
        variance = var_fe.reshape(grid_size, grid_size).cpu().numpy()

        # 转换坐标到物理值(假设归一化空间[0,1]映射到物理范围)
        # 注意: 这里我们返回归一化值，前端根据参数范围转换
        x_values = x_values_norm.cpu().numpy().tolist()
        y_values = y_values_norm.cpu().numpy().tolist()

        # 准备训练数据点
        training_points = self._prepare_training_points(x_param_idx, y_param_idx)

        # 找出当前最优点
        current_best = self._find_current_best(x_param_idx, y_param_idx)

        return PredictionHeatmapData(
            param_x=self.param_names[x_param_idx],
            param_y=self.param_names[y_param_idx],
            param_x_idx=x_param_idx,
            param_y_idx=y_param_idx,
            x_values=x_values,
            y_values=y_values,
            predictions=predictions.tolist(),
            variance=variance.tolist(),
            x_range=(0.0, 1.0),
            y_range=(0.0, 1.0),
            training_points=training_points,
            current_best=current_best,
        )

    def _build_full_params(
        self,
        grid_points: torch.Tensor,
        x_param_idx: int,
        y_param_idx: int,
        fixed_values: torch.Tensor
    ) -> torch.Tensor:
        """构建完整参数向量

        Args:
            grid_points: 2D网格点 [N, 2]，包含(x, y)坐标
            x_param_idx: X轴参数索引
            y_param_idx: Y轴参数索引
            fixed_values: 固定参数值

        Returns:
            torch.Tensor: 完整参数向量 [N, d]
        """
        N = grid_points.shape[0]
        X_full = fixed_values.unsqueeze(0).expand(N, -1).clone()
        X_full[:, x_param_idx] = grid_points[:, 0]
        X_full[:, y_param_idx] = grid_points[:, 1]
        return X_full

    def _prepare_training_points(self, x_param_idx: int, y_param_idx: int) -> List[Dict[str, Any]]:
        """准备训练数据点用于在热力图上标记

        Args:
            x_param_idx: X轴参数索引
            y_param_idx: Y轴参数索引

        Returns:
            List[Dict]: 训练点列表，每个点包含x、y坐标和实际form_error
        """
        points = []
        X_np = self.X_train.cpu().numpy()
        y_np = self.y_train.cpu().numpy()

        for i in range(len(X_np)):
            point = {
                self.param_names[x_param_idx]: float(X_np[i, x_param_idx]),
                self.param_names[y_param_idx]: float(X_np[i, y_param_idx]),
                "form_error": float(y_np[i]) if y_np.ndim == 1 else float(y_np[i, 0]),
            }
            points.append(point)

        return points

    def _find_current_best(self, x_param_idx: int, y_param_idx: int) -> Optional[Dict[str, float]]:
        """找出当前最优点的坐标

        Args:
            x_param_idx: X轴参数索引
            y_param_idx: Y轴参数索引

        Returns:
            Dict: 最优点坐标，或None如果没有训练数据
        """
        if len(self.y_train) == 0:
            return None

        # y_train存储的是-log(fe)，越大表示fe越小(越好)
        best_idx = self.y_train.argmax().item()
        X_np = self.X_train.cpu().numpy()

        return {
            self.param_names[x_param_idx]: float(X_np[best_idx, x_param_idx]),
            self.param_names[y_param_idx]: float(X_np[best_idx, y_param_idx]),
        }

    def get_most_sensitive_params(self, n: int = 2) -> List[int]:
        """获取最敏感的n个参数索引

        基于GP核函数长度尺度，长度尺度越小越敏感。
        用于默认选择热力图显示的参数。

        Args:
            n: 返回的参数数量

        Returns:
            List[int]: 参数索引列表(按敏感性从高到低排序)
        """
        try:
            covar_module = self.model.covar_module

            # 处理ScaleKernel包装的情况
            if hasattr(covar_module, 'base_kernel'):
                base_kernel = covar_module.base_kernel
            else:
                base_kernel = covar_module

            # 提取长度尺度
            if hasattr(base_kernel, 'lengthscale'):
                lengthscale = base_kernel.lengthscale
                if isinstance(lengthscale, torch.Tensor):
                    if lengthscale.dim() > 0:
                        length_scales = lengthscale.detach().cpu().numpy().flatten()
                    else:
                        length_scales = np.array([lengthscale.item()] * self.d)
                else:
                    length_scales = np.ones(self.d)
            else:
                length_scales = np.ones(self.d)

            # 长度尺度越小越敏感
            sensitivities = 1.0 / (length_scales + 1e-6)
            sorted_indices = np.argsort(-sensitivities)  # 降序

            return sorted_indices[:min(n, self.d)].tolist()

        except Exception:
            # 出错时返回前n个参数
            return list(range(min(n, self.d)))
