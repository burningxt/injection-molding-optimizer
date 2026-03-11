import torch
import numpy as np
import json
import os
import math
from typing import Tuple, Optional

# BoTorch imports
from botorch.models import SingleTaskGP
from botorch.fit import fit_gpytorch_mll
from botorch.acquisition.logei import qLogExpectedImprovement
from botorch.optim import optimize_acqf
from botorch.utils.sampling import draw_sobol_samples
from botorch.models.transforms import Standardize, Normalize
from gpytorch.mlls import ExactMarginalLogLikelihood
from gpytorch.constraints import Interval
import gpytorch

from ...domain.config import DEVICE, InjectionMoldingConfig
from ...infrastructure.utils import log
from ..runner import ExperimentRunner, RECORD_COL_FORM_ERROR, RECORD_COL_IS_SHRINK
from .base import BaseOptimizer

# Reuse helper functions from saasbo or redefine them if necessary
# To avoid circular imports or duplication, it might be better to move them to utils, 
# but for now I will copy `snap_to_grid` and `build_safe_mask` or import them if I can refactor.
# Since I cannot easily refactor existing files without potentially breaking things, I will duplicate the helpers for now,
# or better, I will assume the user is okay with me refactoring if I do it carefully.
# However, to be safe and quick, I will just copy the helper functions as they are static.

def snap_to_grid(X_continuous: torch.Tensor, config: InjectionMoldingConfig) -> Tuple[torch.Tensor, torch.Tensor]:
    # ... (Implementation same as SAASBO) ...
    meta = []
    search_space = config.get_search_space()
    for spec in config.tunable_specs:
        name = spec["name"]
        if name in search_space:
            meta.append({"name": name, "values": search_space[name]})
            
    d = len(meta)
    if X_continuous.shape[1] != d:
        raise ValueError(f"Dimension mismatch: X has {X_continuous.shape[1]}, config has {d}")

    mins = torch.tensor([min(m["values"]) for m in meta], device=DEVICE, dtype=torch.double)
    maxs = torch.tensor([max(m["values"]) for m in meta], device=DEVICE, dtype=torch.double)
    ranges = maxs - mins
    ranges[ranges == 0] = 1.0

    X_phys_cont = X_continuous * ranges + mins
    
    X_phys_snapped_list = []
    for i, spec in enumerate(config.tunable_specs):
        col_vals = X_phys_cont[:, i]
        p_type = spec["type"]
        
        if p_type == "range":
            step = spec["step"]
            min_val = spec["min"]
            snapped = torch.round((col_vals - min_val) / step) * step + min_val
            snapped = torch.clamp(snapped, spec["min"], spec["max"])
            X_phys_snapped_list.append(snapped)
            
        elif p_type in ["set", "mixed"]:
            if p_type == "set":
                allowed_vals = spec["values"]
            else:
                allowed_vals = search_space[spec["name"]]
            
            allowed = torch.tensor(sorted(allowed_vals), device=DEVICE, dtype=torch.double)
            dists = torch.abs(col_vals.unsqueeze(1) - allowed.unsqueeze(0))
            min_indices = torch.argmin(dists, dim=1)
            snapped = allowed[min_indices]
            X_phys_snapped_list.append(snapped)
            
        elif p_type == "choice":
            n_opts = len(spec["options"])
            snapped = torch.round(col_vals)
            snapped = torch.clamp(snapped, 0, n_opts - 1)
            X_phys_snapped_list.append(snapped)

        elif p_type == "fixed":
            val = spec.get("value", 0)
            snapped = torch.full_like(col_vals, val)
            X_phys_snapped_list.append(snapped)
            
    phys_snapped = torch.stack(X_phys_snapped_list, dim=1)
    X_snapped = (phys_snapped - mins) / ranges
    return X_snapped, phys_snapped

def build_safe_mask(phys, meta, Ph_min_safe):
    N = phys.shape[0]
    mask = torch.ones(N, dtype=torch.bool, device=DEVICE)
    idx_t = next((i for i,m in enumerate(meta) if "T" in m.get("targets", [])), -1)
    idx_ph = next((i for i,m in enumerate(meta) if "p_sw" in m.get("targets", [])), -1)
    
    if idx_ph == -1: return mask
    
    for i in range(N):
        min_p = Ph_min_safe.get(-1.0, 0.0)
        if idx_t >= 0:
            tm = phys[i, idx_t].item()
            for k, v in Ph_min_safe.items():
                if abs(k - tm) < 1e-4:
                    min_p = v; break
        
        if phys[i, idx_ph].item() < min_p - 1e-6:
            mask[i] = False
    return mask

class StandardBOOptimizer(BaseOptimizer):
    def run(self, n_init: int, n_iter: int, batch_size: int, init_mode: str = "auto", init_excel_path: str = None, stop_event=None):
        config = self.runner.config
        meta = self.runner.meta
        d = len(meta)

        def _record_stage(rec) -> str:
            try:
                return str(rec.get("stage", "")).strip()
            except Exception:
                return ""

        def _is_completed_record(rec) -> bool:
            """已完成：form_error 可转 float 且为有限数。"""
            try:
                fe_val = float(rec.get("form_error"))
                return math.isfinite(fe_val)
            except Exception:
                return False

        def _is_pending_record(rec) -> bool:
            """未完成：form_error 为空/NaN。"""
            try:
                return self.runner._is_missing_form_error(rec.get("form_error"))
            except Exception:
                # 保守：无法判断时按“非 pending”处理
                return False

        def _stage_indices(stage: str):
            return [i for i, r in enumerate(self.runner.all_records) if _record_stage(r) == stage]

        # --- Resume logic: 补齐历史中缺失的 form_error（用户插入参数但未填写结果） ---
        try:
            filled = self.runner.evaluate_pending_records(stop_event=stop_event)
            if stop_event and stop_event.is_set():
                return None, None
            if filled > 0:
                log(f"【续跑】已补齐 {filled} 条缺失记录，继续执行后续批次。")
        except Exception as e:
            log(f"【警告】补齐缺失记录失败（将继续尝试运行，但可能导致续跑不符合预期）：{e}")
        
        mins = torch.tensor([min(m["values"]) for m in meta], device=DEVICE)
        maxs = torch.tensor([max(m["values"]) for m in meta], device=DEVICE)
        ranges = maxs - mins
        ranges[ranges == 0] = 1.0
        
        # --- Resume logic: Process existing records ---
        safe_phys = []
        y_fe = []
        init_done_count = 0
        iter_done_count = 0
        
        if self.runner.all_records:
            log(f"【续跑】检测到 {len(self.runner.all_records)} 条历史记录，正在筛选训练数据……")
            for rec in self.runner.all_records:
                stage = str(rec.get("stage", ""))
                # 仅使用“已完成记录”（form_error 非空且为有限数）
                try:
                    fe_val = float(rec.get("form_error"))
                    if not math.isfinite(fe_val):
                        continue
                except Exception:
                    continue

                if not rec.get("is_shrink", False):
                    # Convert machine params back to physical params
                    m_keys = config.get_ordered_machine_param_keys()
                    m_params = {k: rec[k] for k in m_keys if k in rec}
                    # Get normalized tensor and convert back to physical space for safe_phys
                    norm_tensor = config.translate_to_optimization(m_params).to(DEVICE)
                    phys = norm_tensor * ranges + mins
                    safe_phys.append(phys)
                    y_fe.append(fe_val)
                
                if stage == "init":
                    init_done_count += 1
                elif stage.startswith("iter_"):
                    try:
                        it_num = int(stage.split("_")[1])
                        if it_num > iter_done_count:
                            iter_done_count = it_num
                    except:
                        pass
            log(f"【续跑】初始化已完成：{init_done_count} 条；已完成批次：{iter_done_count} 轮")

        # --- Initialization Phase ---
        # 关键修复：
        # - 只要 experiment_records.xlsx 里已经存在任何 init 记录（无论是否已完成），
        #   就把它视为“初始化清单已生成”，重启后不再重新生成/追加 init 行，避免删行后又回来的错觉。
        # - 若 init 记录不存在（全新开始），才生成 n_init 行。
        init_indices = _stage_indices("init")
        if len(init_indices) == 0:
            init_phys = None
            if init_mode == "manual":
                init_phys = self.runner.load_initial_data(init_excel_path)
                
            if init_phys is None:
                log(f"【初始化】Sobol 采样 {n_init} 组")
                X_raw = draw_sobol_samples(bounds=torch.tensor([[0.0]*d, [1.0]*d], device=DEVICE), n=n_init, q=1).squeeze(1)
                _, init_phys = snap_to_grid(X_raw, config)
                
            # Export initial recommendations if in manual mode
            self.runner.export_recommendations(init_phys, "init")
            # 正式模式：先把待测行写入 experiment_records.xlsx（form_error/shrink 留白），
            # 这样用户可先打开“历史记录管理”修改表格，再回填结果。
            if self.runner.use_simulation:
                for i, phys in enumerate(init_phys):
                    # Skip already evaluated init points
                    if i < init_done_count:
                        continue

                    if stop_event and stop_event.is_set():
                        return None, None
                    fe, is_shrink, _ = self.runner.evaluate(phys, stage="init")
                    log(f"  > 初始{i+1}：{RECORD_COL_FORM_ERROR}：{fe:.4f}，{RECORD_COL_IS_SHRINK}：{is_shrink}")
                    if not is_shrink:
                        safe_phys.append(phys)
                        y_fe.append(fe)
            else:
                pending_indices = self.runner.append_pending_records(init_phys, stage="init")

                for j, phys in enumerate(init_phys):
                    if stop_event and stop_event.is_set():
                        return None, None
                    fe, is_shrink, _ = self.runner.fill_record_at_index(pending_indices[j], stop_event=stop_event)
                    log(f"  > 初始{j + 1}：{RECORD_COL_FORM_ERROR}：{fe:.4f}，{RECORD_COL_IS_SHRINK}：{is_shrink}")
                    if not is_shrink:
                        safe_phys.append(phys)
                        y_fe.append(fe)
        else:
            log(f"【初始化】检测到已存在的初始化记录（{len(init_indices)} 行），续跑时跳过生成初始化清单。")
        
        if not safe_phys:
            log("【警告】未找到有效的初始点。")
            return None, None
            
        X_train = (torch.stack(safe_phys) - mins) / ranges
        y_train = -torch.tensor(y_fe, device=DEVICE, dtype=torch.double).unsqueeze(-1)
        
        best_fe = -y_train.max().item()
        log(f"当前最优{RECORD_COL_FORM_ERROR}为：{best_fe:.4f}")

        # --- Iteration Phase ---
        for it in range(n_iter):
            stage_name = f"iter_{it+1}"
            existing_idx = _stage_indices(stage_name)

            # 关键修复：
            # - 只要该阶段在 experiment_records.xlsx 中已经存在记录（哪怕是待测/pending），
            #   就不再生成/追加新行，避免重启后重复追加导致“行数不变但尾部空行/上移”的问题。
            # - 若存在 pending 行，则按现有行补齐并纳入训练；补齐后直接进入下一轮。
            if existing_idx:
                pending_idx = [i for i in existing_idx if _is_pending_record(self.runner.all_records[i])]
                if pending_idx:
                    log(f"【续跑】检测到 {stage_name} 有 {len(pending_idx)} 条待补齐记录，将补齐已有行（不会追加新行）。")
                    for ridx in pending_idx:
                        if stop_event and stop_event.is_set():
                            break
                        fe, is_shrink, machine_params = self.runner.fill_record_at_index(ridx, stop_event=stop_event)
                        log(f"  > {stage_name} 第{ridx+1}行：{RECORD_COL_FORM_ERROR}：{fe:.4f}，{RECORD_COL_IS_SHRINK}：{is_shrink}")
                        if not is_shrink:
                            # 将该行纳入训练集
                            try:
                                norm_tensor = config.translate_to_optimization(machine_params).to(DEVICE)
                                X_new = norm_tensor.unsqueeze(0)
                                y_new = -torch.tensor([fe], dtype=torch.double, device=DEVICE).unsqueeze(-1)
                                X_train = torch.cat([X_train, X_new], dim=0)
                                y_train = torch.cat([y_train, y_new], dim=0)
                                best_fe = -y_train.max().item()
                            except Exception:
                                pass
                    continue
                continue
                
            if stop_event and stop_event.is_set(): break
            log(f"\n=== 第{it+1}/{n_iter}批次推荐参数 ===")
            
            # Save dummy checkpoint for GUI reset functionality
            ckpt_path = os.path.join(self.runner.out_dir, "bo_checkpoint.pt")
            try:
                torch.save({"it": it, "best_fe": best_fe}, ckpt_path)
            except:
                pass

            # 1. Fit Standard GP Model
            try:
                # Log transform to handle spikes in FormError (fe_values = -y_train)
                fe_values = -y_train
                log_fe = torch.log(fe_values + 1e-6)
                train_y_log = -log_fe
                train_Y_std = (train_y_log - train_y_log.mean()) / (train_y_log.std() + 1e-6)
                
                gp = SingleTaskGP(X_train, train_Y_std)
                
                if hasattr(gp.covar_module, "base_kernel"):
                    gp.covar_module.base_kernel.register_constraint("raw_lengthscale", Interval(0.01, 1.0))
                elif hasattr(gp.covar_module, "raw_lengthscale_constraint"):
                    gp.covar_module.register_constraint("raw_lengthscale", Interval(0.01, 1.0))
                
                mll = ExactMarginalLogLikelihood(gp.likelihood, gp)
                fit_gpytorch_mll(mll)
                
            except Exception as e:
                log(f"  【错误】模型拟合失败：{e}")
                break
            
            # 2. Acquisition Function
            best_f = train_Y_std.max()
            acq = qLogExpectedImprovement(
                model=gp,
                best_f=best_f,
            )
            
            # 3. Batch Generation (Algorithm only)
            # 交互式“手动插入参数”已关闭：统一由算法推荐；如需人为调整，请通过历史记录管理修改后重启回退。
            n_manual = 0
            n_algo = batch_size
            
            if n_algo > 0:
                algo_candidates, acq_values = optimize_acqf(
                    acq_function=acq,
                    bounds=torch.tensor([[0.0]*d, [1.0]*d], device=DEVICE),
                    q=n_algo,
                    num_restarts=10,
                    raw_samples=512,
                    options={"batch_limit": 5, "maxiter": 200}
                )
            else:
                algo_candidates = torch.empty((0, d), device=DEVICE, dtype=torch.double)
            
            candidates = algo_candidates
            
            # 4. Snap and Filter
            X_cand_snapped, phys_cand = snap_to_grid(candidates, config)
            
            for i in range(batch_size):
                max_jitter_tries = 5
                jitter_scale = 0.05
                for _ in range(max_jitter_tries):
                    dist_to_train = torch.norm(X_train - X_cand_snapped[i], dim=1).min()
                    if dist_to_train < 1e-4:
                        candidates[i] = torch.clamp(candidates[i] + torch.randn_like(candidates[i]) * jitter_scale, 0.0, 1.0)
                        X_cand_snapped[i], phys_cand[i] = snap_to_grid(candidates[i:i+1], config)
                    else:
                        break 
            
            unique_mask = torch.ones(batch_size, dtype=torch.bool, device=DEVICE)
            for i in range(batch_size):
                dist_to_train = torch.norm(X_train - X_cand_snapped[i], dim=1).min()
                if dist_to_train < 1e-4:
                    unique_mask[i] = False
            
            safe_mask = build_safe_mask(phys_cand, meta, self.runner.Ph_min_safe)
            valid_mask = unique_mask & safe_mask
            valid_indices = torch.nonzero(valid_mask, as_tuple=False).squeeze(-1)
            
            if len(valid_indices) == 0:
                log("  【警告】本批次候选点均不满足约束，将随机回退采样。")
                candidates = draw_sobol_samples(bounds=torch.tensor([[0.0]*d, [1.0]*d], device=DEVICE), n=batch_size, q=1).squeeze(1)
                X_cand_snapped, phys_cand = snap_to_grid(candidates, config)
                valid_indices = torch.arange(batch_size, device=DEVICE)
            
            to_eval_idx = valid_indices[:batch_size]
            phys_batch = phys_cand[to_eval_idx]
            X_batch = X_cand_snapped[to_eval_idx]
            
            self.runner.export_recommendations(phys_batch, f"iter_{it+1}")

            # 5. Evaluate / Fill
            if self.runner.use_simulation:
                new_fe_list = []
                valid_batch_idx = []

                for i, phys in enumerate(phys_batch):
                    fe, is_shrink, _ = self.runner.evaluate(phys, stage=f"iter_{it+1}")
                    log(f"  > 候选{i+1}：{RECORD_COL_FORM_ERROR}：{fe:.4f}，{RECORD_COL_IS_SHRINK}：{is_shrink}")

                    if not is_shrink:
                        new_fe_list.append(fe)
                        valid_batch_idx.append(i)

                if valid_batch_idx:
                    X_new = X_batch[valid_batch_idx]
                    y_new = -torch.tensor(new_fe_list, dtype=torch.double, device=DEVICE).unsqueeze(-1)

                    X_train = torch.cat([X_train, X_new], dim=0)
                    y_train = torch.cat([y_train, y_new], dim=0)

                    best_fe = -y_train.max().item()
                    log(f"  > 本轮最优{RECORD_COL_FORM_ERROR}：{best_fe:.4f}")
                else:
                    log("  > 本批次无有效点。")
            else:
                pending_indices = self.runner.append_pending_records(phys_batch, stage=f"iter_{it+1}")
                any_valid = False

                for i in range(len(phys_batch)):
                    if stop_event and stop_event.is_set():
                        break
                    fe, is_shrink, _ = self.runner.fill_record_at_index(pending_indices[i], stop_event=stop_event)
                    log(f"  > 候选{i+1}：{RECORD_COL_FORM_ERROR}：{fe:.4f}，{RECORD_COL_IS_SHRINK}：{is_shrink}")
                    if not is_shrink:
                        X_new = X_batch[i:i+1]
                        y_new = -torch.tensor([fe], dtype=torch.double, device=DEVICE).unsqueeze(-1)
                        X_train = torch.cat([X_train, X_new], dim=0)
                        y_train = torch.cat([y_train, y_new], dim=0)
                        any_valid = True

                if any_valid and len(y_train) > 0:
                    best_fe = -y_train.max().item()
                    log(f"  > 本轮最优{RECORD_COL_FORM_ERROR}：{best_fe:.4f}")
                else:
                    log("  > 本批次无有效点。")

        if len(y_train) > 0:
            best_idx = y_train.argmax()
            best_fe = -y_train[best_idx].item()
            best_phys = X_train[best_idx] * ranges + mins
            return best_phys, best_fe
        else:
            return None, None
