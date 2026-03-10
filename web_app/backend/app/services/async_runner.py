"""异步实验运行器 - 移植自 runner.py"""

import asyncio
import json
import sys
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd
import torch

from ..core.config import settings
from ..models.schemas import (
    ExperimentRecord,
    OptimizationState,
    PartConfig,
    AlgoSettings,
)
from .session_manager import OptimizationSession


class AsyncExperimentRunner:
    """异步实验运行器"""

    def __init__(
        self,
        session: OptimizationSession,
        part_config: PartConfig,
        algo_settings: AlgoSettings,
    ):
        self.session = session
        self.part_config = part_config
        self.algo_settings = algo_settings
        self.state = session.state

        # 加载原始 config.py 中的配置转换逻辑
        self._load_config_logic()

    def _load_config_logic(self):
        """加载配置转换逻辑"""
        # 从原始项目导入必要的函数
        import sys
        # BASE_DIR.parent.parent 指向 InjectionMolding 根目录
        injection_molding_root = settings.BASE_DIR.parent.parent
        if str(injection_molding_root) not in sys.path:
            sys.path.insert(0, str(injection_molding_root))

        from config import InjectionMoldingConfig
        from test_functions import (
            simulate_form_error_part_a,
            simulate_form_error_part_b,
            simulate_form_error_validation,
        )

        # 保存模拟函数引用
        self._simulate_func_a = simulate_form_error_part_a
        self._simulate_func_b = simulate_form_error_part_b
        self._simulate_func_validation = simulate_form_error_validation

        # 创建配置对象
        config_dict = {
            "name": self.part_config.name,
            "fixed": self.part_config.fixed,
            "tunable": [t.model_dump() for t in self.part_config.tunable],
        }
        self.config = InjectionMoldingConfig(config_dict)

        # 搜索空间
        self.search_space = self.config.get_search_space()

    async def log(self, message: str, level: str = "info"):
        """异步日志"""
        await self.session.send_log(message, level)

    async def run(self):
        """运行优化流程"""
        try:
            await self.log(">>> 开始工艺寻优流程...")
            await self.log(f"件号: {self.part_config.name}")
            await self.log(f"初始数据: {self.algo_settings.n_init}, 批次数: {self.algo_settings.n_iter}")

            # 1. 检查是否需要恢复（resume）
            if self.state.all_records:
                await self.log(f">>> 检测到 {len(self.state.all_records)} 条历史记录，尝试恢复...")
                await self._resume_pending_records()

            # 2. 初始化阶段
            await self._run_initialization()

            # 3. 迭代优化阶段
            for iteration in range(self.state.iteration, self.algo_settings.n_iter):
                if not self.session.is_running:
                    await self.log("优化已停止")
                    return

                self.state.iteration = iteration
                await self._run_iteration(iteration)

                # 保存 checkpoint
                await self.session.save_checkpoint()

            await self.log(">>> 寻优完成！")
            await self.session.send_message(
                "optimization_completed",
                {"best_form_error": self.state.best_form_error, "best_params": self.state.best_params}
            )

        except asyncio.CancelledError:
            await self.log("优化被取消", "warning")
            raise
        except Exception as e:
            await self.log(f"错误: {str(e)}", "error")
            raise

    async def _resume_pending_records(self):
        """恢复待完成的记录"""
        pending_indices = [
            i for i, r in enumerate(self.state.all_records)
            if r.form_error is None
        ]

        if not pending_indices:
            await self.log("没有待完成的记录")
            return

        await self.log(f"需要补齐 {len(pending_indices)} 条待测记录")

        for idx in pending_indices:
            if not self.session.is_running:
                return

            record = self.state.all_records[idx]
            await self.log(f"\n>>> 补齐记录 [{idx+1}/{len(self.state.all_records)}] - {record.stage}")

            # 请求用户输入
            result = await self._request_evaluation(record.params, idx)

            # 更新记录
            record.form_error = result["form_error"]
            record.is_shrink = result["is_shrink"]

            # 添加到训练集
            if not result["is_shrink"]:
                x_norm = self._params_to_normalized(record.params)
                self.state.X_train.append(x_norm)
                self.state.y_train.append(result["form_error"])

            await self.session.save_checkpoint()

        await self.log("历史记录补齐完成")

    async def _run_initialization(self):
        """运行初始化阶段"""
        await self.log("\n=== 初始化阶段 ===")

        # 使用 Sobol 序列生成初始点
        from torch.quasirandom import SobolEngine

        dim = len(self.search_space)
        sobol = SobolEngine(dimension=dim, scramble=True)

        init_params_list = []
        for i in range(self.algo_settings.n_init):
            # 生成归一化参数
            x_norm = sobol.draw(1).squeeze().tolist()

            # 转换为物理参数
            params = self._normalized_to_params(x_norm)
            init_params_list.append(params)

            # 创建记录
            record = ExperimentRecord(
                stage="init",
                params=params,
            )
            self.state.all_records.append(record)

        # 导出初始试模清单
        await self._export_recommendations(init_params_list, "初始试模清单.xlsx")

        # 如果是正式模式，等待用户输入
        if self.algo_settings.mode == "manual":
            await self.log(f"\n>>> 请在机台上试模，并输入 {self.algo_settings.n_init} 组参数的评价指标")

            for i, params in enumerate(init_params_list):
                if not self.session.is_running:
                    return

                await self.log(f"\n--- 第 {i+1}/{self.algo_settings.n_init} 组 ---")
                result = await self._request_evaluation(params, i)

                # 更新记录
                record = self.state.all_records[i]
                record.form_error = result["form_error"]
                record.is_shrink = result["is_shrink"]

                # 添加到训练集
                if not result["is_shrink"]:
                    # 重新计算该参数的归一化值（避免使用循环外变量）
                    x_norm_i = self._params_to_normalized(params)
                    self.state.X_train.append(x_norm_i)
                    self.state.y_train.append(result["form_error"])

                # 更新安全边界
                await self._update_safety_boundary(params, result["form_error"], result["is_shrink"])

        else:  # 模拟模式
            for i, params in enumerate(init_params_list):
                # 模拟计算
                fe = self._simulate_form_error(params)

                record = self.state.all_records[i]
                record.form_error = fe
                record.is_shrink = fe > self.algo_settings.shrink_threshold

                # 重新计算该参数的归一化值（避免使用循环外变量）
                x_norm_i = self._params_to_normalized(params)
                self.state.X_train.append(x_norm_i)
                self.state.y_train.append(fe)

                await self.log(f"  模拟结果: form_error={fe:.4f}")

        # 更新最佳结果
        self._update_best_result()
        await self.session.save_checkpoint()

    async def _run_iteration(self, iteration: int):
        """运行一轮迭代"""
        stage = f"iter_{iteration + 1}"
        await self.log(f"\n=== 第 {iteration + 1} 轮优化 ===")

        # 训练 GP 模型
        await self.log("> 训练 GP 模型...")

        if len(self.state.X_train) < 2:
            await self.log("训练数据不足，跳过本轮", "warning")
            return

        # 使用 BoTorch 训练模型
        from botorch.models import SingleTaskGP
        from botorch.fit import fit_gpytorch_mll
        from gpytorch.mlls import ExactMarginalLogLikelihood

        # 转换为 tensor，并取负号（BoTorch 默认最大化，我们要最小化 form_error）
        train_X = torch.tensor(self.state.X_train, dtype=torch.float64)
        train_Y = -torch.tensor(self.state.y_train, dtype=torch.float64).unsqueeze(-1)

        # Log 变换处理（处理 form_error 的 spike）
        # 先转回正数，取 log，再取负保持最小化方向
        fe_values = -train_Y  # 转回正数
        log_fe = torch.log(fe_values + 1e-6)
        train_y_log = -log_fe  # 再取负，保持最小化方向
        train_Y_std = (train_y_log - train_y_log.mean()) / (train_y_log.std() + 1e-6)

        # 训练模型
        gp = SingleTaskGP(train_X, train_Y_std)

        # 添加 lengthscale 约束（与原始版本一致）
        from gpytorch.constraints import Interval
        if hasattr(gp.covar_module, "base_kernel"):
            gp.covar_module.base_kernel.register_constraint("raw_lengthscale", Interval(0.01, 1.0))
        elif hasattr(gp.covar_module, "raw_lengthscale_constraint"):
            gp.covar_module.register_constraint("raw_lengthscale", Interval(0.01, 1.0))

        mll = ExactMarginalLogLikelihood(gp.likelihood, gp)
        fit_gpytorch_mll(mll)

        best_fe = min(self.state.y_train)
        await self.log(f"> 训练完成: n={len(train_X)}, best_fe={best_fe:.4f}")

        # 优化采集函数
        await self.log("> 生成推荐参数...")

        from botorch.acquisition import qLogExpectedImprovement
        from botorch.optim import optimize_acqf

        # 因为 y 取了负号，max 对应原始最小值
        best_f = train_Y_std.max()
        acq_func = qLogExpectedImprovement(gp, best_f)

        # 优化
        candidates, acq_value = optimize_acqf(
            acq_function=acq_func,
            bounds=torch.tensor([[0.0] * train_X.shape[1], [1.0] * train_X.shape[1]], dtype=torch.float64),
            q=self.algo_settings.batch_size,
            num_restarts=10,
            raw_samples=512,
            options={"batch_limit": 5, "maxiter": 200},
        )

        # 转换为物理参数并进行后处理
        rec_params_list = []
        X_train_tensor = torch.tensor(self.state.X_train, dtype=torch.float64)

        for i in range(candidates.shape[0]):
            x_norm = candidates[i].tolist()

            # 检查与训练集的距离，避免重复点
            max_jitter_tries = 5
            jitter_scale = 0.05
            for _ in range(max_jitter_tries):
                x_norm_tensor = torch.tensor([x_norm], dtype=torch.float64)
                dist_to_train = torch.norm(X_train_tensor - x_norm_tensor, dim=1).min()
                if dist_to_train < 1e-4:
                    # 添加随机扰动
                    x_norm = [max(0.0, min(1.0, v + torch.randn(1).item() * jitter_scale)) for v in x_norm]
                else:
                    break

            params = self._normalized_to_params(x_norm)

            # 检查安全边界
            safe_mask = self._build_safe_mask([params])
            if not safe_mask[0]:
                await self.log(f"  候选点 {i+1} 不满足安全边界，尝试随机回退", "warning")
                # 随机生成一个替代点
                import random
                x_norm = [random.random() for _ in range(len(self.search_space))]
                params = self._normalized_to_params(x_norm)

            rec_params_list.append(params)

            # 创建记录
            record = ExperimentRecord(
                stage=stage,
                params=params,
            )
            self.state.all_records.append(record)

        # 导出推荐
        await self._export_recommendations(rec_params_list, f"第{iteration+1}批次建议参数.xlsx")

        # 等待评估
        if self.algo_settings.mode == "manual":
            await self.log(f">>> 请试模并输入 {len(rec_params_list)} 组参数的评价指标")

            start_idx = len(self.state.all_records) - len(rec_params_list)
            for i, params in enumerate(rec_params_list):
                if not self.session.is_running:
                    return

                await self.log(f"\n--- 批次内第 {i+1}/{len(rec_params_list)} 组 ---")
                result = await self._request_evaluation(params, start_idx + i)

                # 更新记录
                record = self.state.all_records[start_idx + i]
                record.form_error = result["form_error"]
                record.is_shrink = result["is_shrink"]

                # 添加到训练集
                if not result["is_shrink"]:
                    x_norm = self._params_to_normalized(params)
                    self.state.X_train.append(x_norm)
                    self.state.y_train.append(result["form_error"])

                # 更新安全边界
                await self._update_safety_boundary(params, result["form_error"], result["is_shrink"])

                # 更新最佳结果
                self._update_best_result()

        else:  # 模拟模式
            for i, params in enumerate(rec_params_list):
                fe = self._simulate_form_error(params)

                start_idx = len(self.state.all_records) - len(rec_params_list)
                record = self.state.all_records[start_idx + i]
                record.form_error = fe
                record.is_shrink = fe > self.algo_settings.shrink_threshold

                x_norm = self._params_to_normalized(params)
                self.state.X_train.append(x_norm)
                self.state.y_train.append(fe)

                await self.log(f"  模拟结果: form_error={fe:.4f}")

            self._update_best_result()

    async def _request_evaluation(self, params: Dict[str, Any], record_idx: int) -> Dict[str, Any]:
        """请求用户评估"""
        # 格式化参数显示
        display_params = self._format_params(params)

        prompt = f"""请在机台上试模：
{display_params}
输入面型评价指标（数值）："""

        # 通过 WebSocket 请求输入
        future = self.session.request_input(prompt, params)

        try:
            result = await future
            return result
        except asyncio.CancelledError:
            raise

    def _build_safe_mask(self, params_list: List[Dict[str, Any]]) -> List[bool]:
        """构建安全掩码，过滤可能导致缩水的参数组合

        基于 Ph_min_safe 安全边界，检查每组参数的保压是否安全。
        """
        if not self.state.Ph_min_safe:
            # 没有安全边界数据，全部通过
            return [True] * len(params_list)

        # 找到温度索引和保压索引
        temp_idx = None
        pressure_idx = None
        for i, spec in enumerate(self.part_config.tunable):
            if spec.name in ['T', 'Tm']:
                temp_idx = i
            elif spec.name in ['p_sw', 'Ph', 'ph']:
                pressure_idx = i

        if temp_idx is None or pressure_idx is None:
            # 无法判断，全部通过
            return [True] * len(params_list)

        # 计算每个参数的安全边界
        mask = []
        for params in params_list:
            # 获取归一化参数值
            x_norm = self._params_to_normalized(params)

            # 获取温度值
            temp_val = x_norm[temp_idx] if temp_idx < len(x_norm) else 0.5

            # 查找对应温度的最小安全保压
            min_p = self.state.Ph_min_safe.get(-1.0, 0.0)
            for k, v in self.state.Ph_min_safe.items():
                if isinstance(k, (int, float)) and abs(k - temp_val) < 1e-4:
                    min_p = v
                    break

            # 获取当前保压值
            pressure_val = x_norm[pressure_idx] if pressure_idx < len(x_norm) else 0.5

            # 检查是否安全（当前保压 >= 最小安全保压）
            is_safe = pressure_val >= min_p - 1e-6
            mask.append(is_safe)

        return mask

    async def _update_safety_boundary(self, params: Dict[str, Any], fe: float, is_shrink: bool):
        """更新安全边界（防止缩水）

        当检测到缩水时，更新该温度下的最小安全保压值。
        """
        if not is_shrink:
            # 非缩水点，可以更新安全边界
            temp_idx = None
            pressure_idx = None
            for i, spec in enumerate(self.part_config.tunable):
                if spec.name in ['T', 'Tm']:
                    temp_idx = i
                elif spec.name in ['p_sw', 'Ph', 'ph']:
                    pressure_idx = i

            if temp_idx is not None and pressure_idx is not None:
                x_norm = self._params_to_normalized(params)
                temp_val = x_norm[temp_idx] if temp_idx < len(x_norm) else None
                pressure_val = x_norm[pressure_idx] if pressure_idx < len(x_norm) else None

                if temp_val is not None and pressure_val is not None:
                    # 更新该温度下的最大安全保压（非缩水时的保压）
                    current_max = self.state.Ph_min_safe.get(temp_val, 0.0)
                    self.state.Ph_min_safe[temp_val] = max(current_max, pressure_val)
            return

        # 检测到缩水，更新安全边界
        temp_idx = None
        pressure_idx = None
        for i, spec in enumerate(self.part_config.tunable):
            if spec.name in ['T', 'Tm']:
                temp_idx = i
            elif spec.name in ['p_sw', 'Ph', 'ph']:
                pressure_idx = i

        if temp_idx is not None and pressure_idx is not None:
            x_norm = self._params_to_normalized(params)
            temp_val = x_norm[temp_idx] if temp_idx < len(x_norm) else None
            pressure_val = x_norm[pressure_idx] if pressure_idx < len(x_norm) else None

            if temp_val is not None and pressure_val is not None:
                # 设置该温度下的最小安全保压（缩水时的保压 + 小 margin）
                current_min = self.state.Ph_min_safe.get(temp_val, float('inf'))
                self.state.Ph_min_safe[temp_val] = min(current_min, pressure_val + 0.05)
                await self.log(f"  更新安全边界: T={temp_val:.2f}, Ph_min={self.state.Ph_min_safe[temp_val]:.2f}", "warning")

    def _params_to_normalized(self, params: Dict[str, Any]) -> List[float]:
        """将物理参数转换为归一化值"""
        # 简化实现，实际需要根据 config.py 的逻辑
        x_norm = []
        for spec in self.part_config.tunable:
            name = spec.name
            val = params.get(name, 0)

            if spec.type == "range":
                if spec.max and spec.min:
                    norm = (val - spec.min) / (spec.max - spec.min)
                    x_norm.append(max(0, min(1, norm)))
                else:
                    x_norm.append(0.5)
            else:
                x_norm.append(0.5)

        return x_norm

    def _normalized_to_params(self, x_norm: List[float]) -> Dict[str, Any]:
        """将归一化值转换为物理参数"""
        params = {}
        for i, spec in enumerate(self.part_config.tunable):
            if i < len(x_norm):
                norm = x_norm[i]

                if spec.type == "range":
                    if spec.max is not None and spec.min is not None:
                        val = spec.min + norm * (spec.max - spec.min)
                        # 对齐步长
                        if spec.step:
                            val = round(val / spec.step) * spec.step
                        params[spec.name] = val
                    else:
                        params[spec.name] = norm
                else:
                    params[spec.name] = norm

        # 添加固定参数
        params.update(self.part_config.fixed)

        return params

    def _format_params(self, params: Dict[str, Any]) -> str:
        """格式化参数显示"""
        lines = []
        for name, val in params.items():
            lines.append(f"  {name}: {val}")
        return "\n".join(lines)

    def _simulate_form_error(self, params: Dict[str, Any]) -> float:
        """模拟计算面型评价指标

        根据参数数量自动选择 Part A 或 Part B 模拟函数
        """
        tunable_count = len(self.part_config.tunable)

        # 获取固定参数
        fixed = self.part_config.fixed
        Tc = fixed.get("Tc", 16.0)
        F = fixed.get("F", 8.0)

        # 获取可调参数
        T = params.get("T", params.get("Tm", 138.0))
        Pv = params.get("p_vp", params.get("Pv", 900.0))
        Ph = params.get("p_sw", params.get("Ph", 400.0))

        if tunable_count >= 8:
            # Part A: 完整参数 (9个可调参数)
            delay_time = params.get("delay", params.get("delay_time", 0.5))
            V1 = params.get("v1", 25.0)
            V2 = params.get("v2", 25.0)
            V3 = params.get("v3", 30.0)
            V4 = params.get("v4", 30.0)
            V5 = params.get("v5", 30.0)

            # 从 fixed 获取 t_pack
            t_pack = fixed.get("t_pack", [2.0, 1.0, 0.5, 0.5])

            return self._simulate_func_a(
                Tm=T,
                Pv=Pv,
                Ph=Ph,
                delay_time=delay_time,
                V1=V1,
                V2=V2,
                V3=V3,
                V4=V4,
                V5=V5,
                Tc=Tc,
                F=F,
                noise_std=0.0,
            )
        elif tunable_count <= 5:
            # Part B: 简化参数 (4个可调参数)
            Vg = params.get("Vg", 5.0)

            # 从 fixed 获取其他参数
            G = fixed.get("G", 40)
            V1 = fixed.get("v1", 30.0)
            V4 = fixed.get("v4", 30.0)
            V5 = fixed.get("v5", 30.0)
            t1 = fixed.get("t1", 1.6)
            t2 = fixed.get("t2", 1.6)
            t3 = fixed.get("t3", 0.4)
            t4 = fixed.get("t4", 0.4)

            return self._simulate_func_b(
                Tm=T,
                Pv=Pv,
                Ph1=Ph,
                Vg=Vg,
                G=G,
                V1=V1,
                V4=V4,
                V5=V5,
                t1=t1,
                t2=t2,
                t3=t3,
                t4=t4,
                Tc=Tc,
                F=F,
                noise_std=0.0,
            )
        else:
            # 默认使用 validation 函数
            Vg = params.get("Vg", 5.0)
            return self._simulate_func_validation(
                Tm=T,
                Pv=Pv,
                Ph=Ph,
                Vg=Vg,
                noise_std=0.0,
            )

    def _update_best_result(self):
        """更新最佳结果"""
        if not self.state.y_train:
            return

        best_idx = np.argmin(self.state.y_train)
        self.state.best_form_error = self.state.y_train[best_idx]

        # 找到对应的参数
        if best_idx < len(self.state.all_records):
            self.state.best_params = self.state.all_records[best_idx].params

    async def _export_recommendations(self, params_list: List[Dict], filename: str):
        """导出推荐参数到 Excel"""
        try:
            df = pd.DataFrame(params_list)
            filepath = settings.OUTPUT_DIR / filename
            df.to_excel(filepath, index=False)
            await self.log(f"> 导出文件: {filepath}")
        except Exception as e:
            await self.log(f"导出失败: {e}", "error")
