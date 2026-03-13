"""参数敏感性分析模块"""

import torch
import numpy as np
from typing import List, Optional
from botorch.models import SingleTaskGP

from ...domain.models import SensitivityAnalysis, ParamSensitivity


class SensitivityAnalyzer:
    """基于 GP 核函数长度尺度的参数敏感性分析器

    基于 GP 的 RBF/SE 核函数长度尺度：
    - 长度尺度越小，函数在该维度变化越快，该参数越敏感
    - 长度尺度越大，函数在该维度变化越慢，该参数越不敏感
    """

    def __init__(
        self,
        model: SingleTaskGP,
        param_names: Optional[List[str]] = None,
    ):
        self.model = model
        self.param_names = param_names

    def analyze(self) -> SensitivityAnalysis:
        """分析各参数的敏感性

        Returns:
            SensitivityAnalysis: 敏感性分析结果，包含参数重要性排序
        """
        try:
            # 获取长度尺度
            length_scales = self._extract_length_scales()

            if length_scales is None or len(length_scales) == 0:
                return self._create_fallback_analysis("无法提取核函数参数")

            # 长度尺度越小越敏感，所以用 1/length_scale 作为敏感性度量
            raw_sensitivities = 1.0 / (length_scales + 1e-6)

            # 归一化到 0-1 范围
            min_sens = raw_sensitivities.min()
            max_sens = raw_sensitivities.max()
            if max_sens - min_sens > 1e-6:
                normalized_sens = (raw_sensitivities - min_sens) / (max_sens - min_sens)
            else:
                normalized_sens = np.ones_like(raw_sensitivities) * 0.5

            # 按敏感性排序（从高到低）
            sorted_indices = np.argsort(-normalized_sens)  # 降序

            # 构建排名列表
            rankings = []
            d = len(length_scales)
            param_names = self.param_names or [f"param_{i}" for i in range(d)]

            for rank, idx in enumerate(sorted_indices, 1):
                sens_value = normalized_sens[idx]
                length_scale = length_scales[idx]

                # 解释级别
                if sens_value > 0.7:
                    interpretation = "高敏感"
                elif sens_value > 0.3:
                    interpretation = "中等"
                else:
                    interpretation = "低敏感"

                rankings.append(ParamSensitivity(
                    param_name=param_names[idx] if idx < len(param_names) else f"param_{idx}",
                    length_scale=float(length_scale),
                    sensitivity_score=float(sens_value),
                    importance_rank=rank,
                    interpretation=interpretation,
                ))

            # 生成解释文本
            if rankings:
                top_param = rankings[0].param_name
                interpretation = f"参数 '{top_param}' 对结果影响最大，建议优先调整该参数"
            else:
                interpretation = "无法确定参数敏感性"

            return SensitivityAnalysis(
                rankings=rankings,
                interpretation=interpretation,
                kernel_type=self._get_kernel_type(),
                is_fallback=False,
            )

        except Exception as e:
            return self._create_fallback_analysis(f"分析失败: {str(e)}")

    def _extract_length_scales(self) -> Optional[np.ndarray]:
        """从 GP 模型中提取长度尺度参数

        处理 ScaleKernel 包装的情况，支持 ARD (Automatic Relevance Determination)

        Returns:
            np.ndarray: 长度尺度数组，shape (d,)
        """
        try:
            # 获取协方差模块
            covar_module = self.model.covar_module

            # 处理 ScaleKernel 包装的情况
            if hasattr(covar_module, 'base_kernel'):
                base_kernel = covar_module.base_kernel
            else:
                base_kernel = covar_module

            # 提取长度尺度
            if hasattr(base_kernel, 'lengthscale'):
                lengthscale = base_kernel.lengthscale
                if isinstance(lengthscale, torch.Tensor):
                    # 处理 ARD 情况
                    if lengthscale.dim() > 0:
                        return lengthscale.detach().cpu().numpy().flatten()
                    else:
                        return np.array([lengthscale.item()])

            # 如果无法直接获取，尝试从 raw 参数获取
            if hasattr(base_kernel, 'raw_lengthscale'):
                raw_ls = base_kernel.raw_lengthscale
                if isinstance(raw_ls, torch.Tensor):
                    # 应用约束转换
                    if hasattr(base_kernel, 'lengthscale_constraint'):
                        constraint = base_kernel.lengthscale_constraint
                        ls = constraint.transform(raw_ls)
                        return ls.detach().cpu().numpy().flatten()
                    else:
                        return raw_ls.detach().cpu().numpy().flatten()

            return None

        except Exception as e:
            print(f"[SensitivityAnalyzer] 提取长度尺度失败: {e}")
            return None

    def _get_kernel_type(self) -> str:
        """获取核函数类型"""
        try:
            covar_module = self.model.covar_module
            if hasattr(covar_module, 'base_kernel'):
                kernel_name = type(covar_module.base_kernel).__name__
            else:
                kernel_name = type(covar_module).__name__
            return kernel_name
        except:
            return "Unknown"

    def _create_fallback_analysis(self, reason: str) -> SensitivityAnalysis:
        """创建回退分析结果（当无法正常分析时使用）

        Args:
            reason: 回退原因

        Returns:
            SensitivityAnalysis: 默认分析结果
        """
        d = len(self.param_names) if self.param_names else 1
        param_names = self.param_names or [f"param_{i}" for i in range(d)]

        rankings = [
            ParamSensitivity(
                param_name=name,
                length_scale=1.0,
                sensitivity_score=0.5,
                importance_rank=i + 1,
                interpretation="未知（数据不足）",
            )
            for i, name in enumerate(param_names)
        ]

        return SensitivityAnalysis(
            rankings=rankings,
            interpretation=f"敏感性分析暂时不可用：{reason}。建议继续实验收集更多数据。",
            kernel_type="Unknown",
            is_fallback=True,
            fallback_reason=reason,
        )
