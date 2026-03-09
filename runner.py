import os
import time
import torch
import pandas as pd
import numpy as np
import math
from typing import List, Dict, Tuple, Optional, Any

from config import DEVICE, InjectionMoldingConfig
from utils import log
from test_functions import (
    simulate_form_error_part_a, 
    simulate_form_error_part_b, 
    simulate_form_error_validation
)

RECORD_COL_STAGE = "阶段"
RECORD_COL_FORM_ERROR = "面型评价指标"
RECORD_COL_IS_SHRINK = "是否缩水"

class ExperimentRunner:
    def __init__(
        self, 
        config: InjectionMoldingConfig, 
        use_simulation: bool, 
        shrink_threshold: float, 
        out_dir: str
    ):
        self.config = config
        self.use_simulation = use_simulation
        self.shrink_threshold = shrink_threshold
        self.out_dir = out_dir
        
        # State Management
        self.all_records = []
        self.Ph_min_safe = {}
        
        # Build Meta (Search Space Info)
        self.meta = self._build_meta()
        self._init_safety_boundary()
        
        # Load existing data if any (Resume support)
        self.load_existing_records()

    @staticmethod
    def _is_missing_form_error(val) -> bool:
        """判断 form_error 是否为空/缺失（支持 Excel NaN、空字符串等）。"""
        if val is None:
            return True
        if isinstance(val, float) and math.isnan(val):
            return True
        s = str(val).strip()
        if s == "":
            return True
        if s.lower() == "nan":
            return True
        return False

    @staticmethod
    def _stage_rank(stage_val) -> int:
        """
        将 stage 映射为可比较的顺序：
        - init -> 0
        - iter_k -> k
        其他/异常 -> 极大值（视为最后）
        """
        s = "" if stage_val is None else str(stage_val).strip()
        if s.lower() == "init":
            return 0
        if s.lower().startswith("iter_"):
            try:
                return int(s.split("_", 1)[1])
            except Exception:
                return 10**9
        return 10**9

    def _machine_params_to_display(self, machine_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        将机台参数字典（内部 key：targets/fixed）转换为中文显示列（按参数配置的中文名）。
        绑定 targets 的场景会合并为同一列名（值按第一个命中的 target 取值）。
        """
        out: Dict[str, Any] = {}
        disp_to_targets = self.config.get_display_name_to_targets_map()
        for disp, targets in disp_to_targets.items():
            for t in targets:
                if t in machine_params:
                    out[disp] = machine_params.get(t)
                    break
        return out

    def _row_to_internal_record(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """
        将一行（可能是中文列名、也可能是旧版英文列名）转换为内部记录结构：
        - stage / 阶段 -> stage
        - form_error / 面型评价指标 -> form_error
        - is_shrink / shrink / 是否缩水 -> is_shrink
        - 中文参数列 -> 目标机台参数 targets（支持绑定参数一列赋值到多个 targets）
        """
        rec: Dict[str, Any] = {}

        # 关键列：兼容中英文
        rec["stage"] = row.get("stage", row.get(RECORD_COL_STAGE, ""))
        rec["form_error"] = row.get("form_error", row.get(RECORD_COL_FORM_ERROR, np.nan))
        rec["is_shrink"] = row.get("is_shrink", row.get(RECORD_COL_IS_SHRINK, row.get("shrink", np.nan)))

        # 先拷贝可能已存在的内部机台参数列（targets / fixed）
        ordered_keys = self.config.get_ordered_machine_param_keys()
        for k in ordered_keys:
            if k in row:
                rec[k] = row.get(k)

        # 再把中文参数列反向映射为 targets（若值为空则跳过）
        disp_to_targets = self.config.get_display_name_to_targets_map()
        for disp, targets in disp_to_targets.items():
            if disp not in row:
                continue
            v = row.get(disp)
            if v is None or (isinstance(v, float) and pd.isna(v)):
                continue
            if str(v).strip() == "":
                continue
            for t in targets:
                rec[t] = v

        # 其余列原样保留（避免用户自定义列丢失）
        reserved = {"stage", "form_error", "is_shrink", "shrink", RECORD_COL_STAGE, RECORD_COL_FORM_ERROR, RECORD_COL_IS_SHRINK}
        reserved |= set(ordered_keys)
        reserved |= set(disp_to_targets.keys())
        for k, v in row.items():
            if k in reserved:
                continue
            rec[k] = v

        return rec
        
    def _build_meta(self) -> List[dict]:
        meta = []
        search_space = self.config.get_search_space()
        for spec in self.config.tunable_specs:
            name = spec["name"]
            if name in search_space:
                meta.append({
                    "name": name, 
                    "values": search_space[name],
                    "targets": spec.get("targets", [name]) # Include targets for robust lookup
                })
        return meta

    def _init_safety_boundary(self):
        t_in = False
        t_vals = []
        for m in self.meta:
            # Check if this parameter controls "T"
            if "T" in m.get("targets", []):
                t_in = True; t_vals = m["values"]; break
        self.Ph_min_safe = {float(t): 0.0 for t in t_vals} if t_in else {-1.0: 0.0}

    def evaluate(self, phys_params: torch.Tensor, stage: str = "iter") -> Tuple[float, bool, dict]:
        """
        Evaluate a single physical point.
        Returns: (form_error, is_shrink, machine_params)
        """
        # Ensure phys_params is 1D tensor/array on CPU for processing
        if isinstance(phys_params, torch.Tensor):
            vals = phys_params.detach().cpu().numpy().flatten().tolist()
        else:
            vals = list(phys_params)

        opt_params = {m["name"]: vals[i] for i, m in enumerate(self.meta)}
        machine_params = self.config.translate_to_machine(opt_params)
        
        fe = 0.0
        explicit_shrink = None
        
        if self.use_simulation:
            try:
                if "Validation" in self.config.name:
                    fe = simulate_form_error_validation(
                        Tm=machine_params.get("T", 138),
                        Pv=machine_params.get("p_vp", 960),
                        Ph=machine_params.get("p_sw", 530),
                        Vg=machine_params.get("Vg", 5)
                    )
                elif "PartB" in self.config.name:
                    fe = simulate_form_error_part_b(
                        Tm=machine_params.get("T", 138),
                        Pv=machine_params.get("p_vp", 900),
                        Ph1=machine_params.get("p_sw", 600),
                        Vg=machine_params.get("Vg", 30),
                        G=machine_params.get("G", 40),
                        V1=machine_params.get("v1", 30),
                        V4=machine_params.get("v4", 30),
                        V5=machine_params.get("v5", 30),
                        t1=machine_params.get("t1", 1.6),
                        t2=machine_params.get("t2", 1.6),
                        t3=machine_params.get("t3", 0.4),
                        t4=machine_params.get("t4", 0.4),
                        Tc=machine_params.get("Tc", 15),
                        F=machine_params.get("F", 15)
                    )
                else:
                    fe = simulate_form_error_part_a(
                        Tm=machine_params.get("T", 140), 
                        Pv=machine_params.get("p_vp", 1000),
                        Ph=machine_params.get("p_sw", 400),
                        delay_time=machine_params.get("delay_time", 0.0),
                        V1=machine_params.get("v1", 30),
                        V2=machine_params.get("v2", 30),
                        V3=machine_params.get("v3", 30),
                        V4=machine_params.get("v4", 30),
                        V5=machine_params.get("v5", 30),
                        Tc=machine_params.get("Tc", 16.0),
                        F=machine_params.get("F", 8.0)
                    )
            except Exception:
                fe = 999.0
        else:
            log("\n请在机台上试模：")
            keys = self.config.get_ordered_machine_param_keys()
            for k in keys:
                if k in machine_params:
                    disp = self.config.get_param_display_name(k)
                    log(f"  {disp}：{machine_params[k]}")
            while True:
                s = input("请输入该组工艺参数的面型评价指标数值：").strip()
                s = s.replace("，", ",")
                if not s or s in [",0", ",1"]:
                    log("  【提示】输入不能为空，请输入面型评价指标数值。")
                    continue
                try:
                    if "," in s:
                        parts = s.split(",")
                        if not parts[0].strip():
                            log("  【提示】数值部分不能为空。")
                            continue
                        fe = float(parts[0])
                        explicit_shrink = bool(int(parts[1]))
                    else:
                        fe = float(s)
                        explicit_shrink = None 
                    break
                except ValueError:
                    log("  【错误】请输入有效的数字格式。")
                except Exception as e:
                    log(f"  【错误】输入处理异常：{e}")
        
        # Safety Update
        is_shrink = self._update_safety_boundary(machine_params, fe, explicit_shrink)
        
        # Record & Export
        rec = {"stage": stage, "form_error": fe, "is_shrink": is_shrink}
        rec.update(machine_params)
        self.all_records.append(rec)
        self._export_records()
        
        return fe, is_shrink, machine_params

    def _prompt_form_error(self) -> Tuple[float, Optional[bool]]:
        """
        正式模式下交互获取 form_error，可选带缩水标记：
        - "0.35" -> (0.35, None)
        - "0.35,1" -> (0.35, True)
        - "0.35,0" -> (0.35, False)
        """
        while True:
            s = input("请输入该组工艺参数的面型评价指标数值：").strip()
            s = s.replace("，", ",")
            if not s or s in [",0", ",1"]:
                log("  【提示】输入不能为空，请输入面型评价指标数值。")
                continue
            try:
                if "," in s:
                    parts = s.split(",")
                    if not parts[0].strip():
                        log("  【提示】数值部分不能为空。")
                        continue
                    fe_val = float(parts[0])
                    explicit_shrink = bool(int(parts[1]))
                else:
                    fe_val = float(s)
                    explicit_shrink = None
                return fe_val, explicit_shrink
            except ValueError:
                log("  【错误】请输入有效的数字格式。")
            except Exception as e:
                log(f"  【错误】输入处理异常：{e}")

    def evaluate_pending_records(self, stop_event=None) -> int:
        """
        若历史记录中存在 form_error 为空的行（常见于用户插入新参数但未测量），
        则按记录顺序逐行提示用户补齐结果，并回写到 experiment_records.xlsx。

        返回补齐的行数。
        """
        if not self.all_records:
            return 0

        pending_indices = []
        for i, rec in enumerate(self.all_records):
            if self._is_missing_form_error(rec.get("form_error")):
                pending_indices.append(i)

        if not pending_indices:
            return 0

        log(f"【续跑】检测到 {len(pending_indices)} 条未填写{RECORD_COL_FORM_ERROR}的记录，将从最早缺失处开始补齐。")

        filled = 0
        keys = self.config.get_ordered_machine_param_keys()
        for idx in pending_indices:
            if stop_event and stop_event.is_set():
                break

            rec = self.all_records[idx]
            stage = str(rec.get("stage", "iter")).strip() or "iter"

            # 从记录中提取机台参数（允许部分缺失；缺失项将不显示/用默认推断）
            machine_params = {k: rec.get(k) for k in keys if k in rec}

            if self.use_simulation:
                # 仿真模式：直接算出 fe
                try:
                    if "Validation" in self.config.name:
                        fe = simulate_form_error_validation(
                            Tm=machine_params.get("T", 138),
                            Pv=machine_params.get("p_vp", 960),
                            Ph=machine_params.get("p_sw", 530),
                            Vg=machine_params.get("Vg", 5)
                        )
                    elif "PartB" in self.config.name:
                        fe = simulate_form_error_part_b(
                            Tm=machine_params.get("T", 138),
                            Pv=machine_params.get("p_vp", 900),
                            Ph1=machine_params.get("p_sw", 600),
                            Vg=machine_params.get("Vg", 30),
                            G=machine_params.get("G", 40),
                            V1=machine_params.get("v1", 30),
                            V4=machine_params.get("v4", 30),
                            V5=machine_params.get("v5", 30),
                            t1=machine_params.get("t1", 1.6),
                            t2=machine_params.get("t2", 1.6),
                            t3=machine_params.get("t3", 0.4),
                            t4=machine_params.get("t4", 0.4),
                            Tc=machine_params.get("Tc", 15),
                            F=machine_params.get("F", 15)
                        )
                    else:
                        fe = simulate_form_error_part_a(
                            Tm=machine_params.get("T", 140), 
                            Pv=machine_params.get("p_vp", 1000),
                            Ph=machine_params.get("p_sw", 400),
                            delay_time=machine_params.get("delay_time", 0.0),
                            V1=machine_params.get("v1", 30),
                            V2=machine_params.get("v2", 30),
                            V3=machine_params.get("v3", 30),
                            V4=machine_params.get("v4", 30),
                            V5=machine_params.get("v5", 30),
                            Tc=machine_params.get("Tc", 16.0),
                            F=machine_params.get("F", 8.0)
                        )
                    explicit_shrink = None
                except Exception:
                    fe = 999.0
                    explicit_shrink = None
            else:
                # 正式模式：打印该条参数，等待用户输入
                log("\n请在机台上试模（补齐历史缺失记录）：")
                for k in keys:
                    if k in machine_params and machine_params[k] is not None and str(machine_params[k]).strip() != "":
                        disp = self.config.get_param_display_name(k)
                        log(f"  {disp}：{machine_params[k]}")
                fe, explicit_shrink = self._prompt_form_error()

            is_shrink = self._update_safety_boundary(machine_params, fe, explicit_shrink)

            # 回写到原记录（而不是 append 新记录）
            rec["stage"] = stage
            rec["form_error"] = fe
            rec["is_shrink"] = is_shrink
            self.all_records[idx] = rec
            self._export_records()
            filled += 1

            log(f"  【补齐】阶段：{stage}，行：{idx+1}，{RECORD_COL_FORM_ERROR}：{fe:.4f}，{RECORD_COL_IS_SHRINK}：{is_shrink}")

        return filled

    def append_pending_records(self, phys_points: torch.Tensor, stage: str) -> List[int]:
        """
        将一批“待测”的推荐参数写入 experiment_records.xlsx（form_error / is_shrink 留白）。
        这样用户可在 GUI 的“历史记录管理”里，在输入结果前先修改表格。

        返回：新追加记录在 self.all_records 中的 index 列表（与 phys_points 顺序一致）。
        """
        if phys_points is None:
            return []

        new_indices: List[int] = []
        for phys in phys_points:
            if isinstance(phys, torch.Tensor):
                vals = phys.detach().cpu().numpy().flatten().tolist()
            else:
                vals = list(phys)

            opt_params = {m["name"]: vals[i] for i, m in enumerate(self.meta)}
            machine_params = self.config.translate_to_machine(opt_params)

            # 留白：pandas 写入 Excel 会变成空单元格；读回时通常为 NaN
            rec = {"stage": stage, "form_error": np.nan, "is_shrink": np.nan}
            rec.update(machine_params)
            self.all_records.append(rec)
            new_indices.append(len(self.all_records) - 1)

        # 立刻落地，供“历史记录管理”打开/编辑
        self._export_records()
        return new_indices

    def fill_record_at_index(self, idx: int, stop_event=None) -> Tuple[float, bool, dict]:
        """
        将指定 index 的记录补齐 form_error/is_shrink（正式模式下会请求交互输入）。
        与 evaluate() 的区别：不会 append 新记录，而是回写已有行，避免重复。
        """
        if idx < 0 or idx >= len(self.all_records):
            raise IndexError(f"record index out of range: {idx}")

        rec = self.all_records[idx]
        stage = str(rec.get("stage", "")).strip() or "iter"

        # 从记录中提取机台参数
        keys = self.config.get_ordered_machine_param_keys()
        machine_params = {k: rec.get(k) for k in keys if k in rec}

        explicit_shrink = None
        if self.use_simulation:
            # 仿真模式：直接算出 fe（与 evaluate_pending_records 保持一致）
            try:
                if "Validation" in self.config.name:
                    fe = simulate_form_error_validation(
                        Tm=machine_params.get("T", 138),
                        Pv=machine_params.get("p_vp", 960),
                        Ph=machine_params.get("p_sw", 530),
                        Vg=machine_params.get("Vg", 5)
                    )
                elif "PartB" in self.config.name:
                    fe = simulate_form_error_part_b(
                        Tm=machine_params.get("T", 138),
                        Pv=machine_params.get("p_vp", 900),
                        Ph1=machine_params.get("p_sw", 600),
                        Vg=machine_params.get("Vg", 30),
                        G=machine_params.get("G", 40),
                        V1=machine_params.get("v1", 30),
                        V4=machine_params.get("v4", 30),
                        V5=machine_params.get("v5", 30),
                        t1=machine_params.get("t1", 1.6),
                        t2=machine_params.get("t2", 1.6),
                        t3=machine_params.get("t3", 0.4),
                        t4=machine_params.get("t4", 0.4),
                        Tc=machine_params.get("Tc", 15),
                        F=machine_params.get("F", 15)
                    )
                else:
                    fe = simulate_form_error_part_a(
                        Tm=machine_params.get("T", 140),
                        Pv=machine_params.get("p_vp", 1000),
                        Ph=machine_params.get("p_sw", 400),
                        delay_time=machine_params.get("delay_time", 0.0),
                        V1=machine_params.get("v1", 30),
                        V2=machine_params.get("v2", 30),
                        V3=machine_params.get("v3", 30),
                        V4=machine_params.get("v4", 30),
                        V5=machine_params.get("v5", 30),
                        Tc=machine_params.get("Tc", 16.0),
                        F=machine_params.get("F", 8.0)
                    )
            except Exception:
                fe = 999.0
        else:
            # 正式模式：打印该条参数，等待用户输入
            log("\n请在机台上试模：")
            for k in keys:
                if k in machine_params and machine_params[k] is not None and str(machine_params[k]).strip() != "":
                    disp = self.config.get_param_display_name(k)
                    log(f"  {disp}：{machine_params[k]}")
            fe, explicit_shrink = self._prompt_form_error()

        is_shrink = self._update_safety_boundary(machine_params, fe, explicit_shrink)

        # 回写该行
        rec["stage"] = stage
        rec["form_error"] = fe
        rec["is_shrink"] = is_shrink
        self.all_records[idx] = rec
        self._export_records()
        return fe, is_shrink, machine_params

    def export_recommendations(self, phys_points: torch.Tensor, stage: str):
        """
        导出一批推荐参数到表格文件，列名使用中文显示名。
        """
            
        # 将阶段名映射为更便于现场阅读的中文
        if stage == "init":
            cn_stage = "初始试模清单"
        elif stage.startswith("iter_"):
            try:
                iter_num = stage.split("_")[1]
                cn_stage = f"第{iter_num}批次建议参数"
            except:
                cn_stage = stage
        else:
            cn_stage = stage

        log(f"\n【导出】正在导出{cn_stage}到表格文件……")
        
        recommendations = []
        for i, phys in enumerate(phys_points):
            if isinstance(phys, torch.Tensor):
                vals = phys.detach().cpu().numpy().flatten().tolist()
            else:
                vals = list(phys)
                
            opt_params = {m["name"]: vals[i] for i, m in enumerate(self.meta)}
            machine_params = self.config.translate_to_machine(opt_params)
            
            # 生成推荐表时，同时预留“面型评价指标/是否缩水”两列（留白），便于现场直接回填/标记
            rec = {"序号": i + 1, RECORD_COL_STAGE: cn_stage, RECORD_COL_FORM_ERROR: "", RECORD_COL_IS_SHRINK: ""}
            rec.update(self._machine_params_to_display(machine_params))
            recommendations.append(rec)
            
        df = pd.DataFrame(recommendations)
        ordered_cols = ["序号", RECORD_COL_STAGE, RECORD_COL_FORM_ERROR, RECORD_COL_IS_SHRINK] + self.config.get_ordered_param_display_names()
        final_cols = [c for c in ordered_cols if c in df.columns]
        remaining = [c for c in df.columns if c not in final_cols]
        df = df[final_cols + remaining]
        
        filename = f"{cn_stage}.xlsx"
        path = os.path.join(self.out_dir, filename)
        try:
            df.to_excel(path, index=False)
            log(f"  【成功】文件已保存至：{path}")
        except Exception as e:
            log(f"  【失败】无法导出表格文件：{e}")

    def _update_safety_boundary(self, machine_params, fe, explicit_shrink) -> bool:
        is_shrink = False
        if explicit_shrink is not None:
            is_shrink = explicit_shrink
        else:
            if fe > self.shrink_threshold:
                is_shrink = True
                Tm = machine_params.get("T", -1.0)
                Ph = machine_params.get("p_sw", 0.0)
                if self.all_records:
                    min_good = float('inf')
                    for r in self.all_records:
                        if r.get("form_error", 999) <= self.shrink_threshold:
                            rt = r.get("T", -1); rp = r.get("p_sw", float('inf'))
                            if abs(rt-Tm)<0.5 or rt<Tm-0.5:
                                if rp < min_good: min_good = rp
                    if min_good < float('inf') and Ph > min_good + 50:
                        is_shrink = False
        
        if not is_shrink: return False
        
        Tm = machine_params.get("T", -1.0)
        Ph = machine_params.get("p_sw", 0.0)
        
        # Find spec for p_sw by targets
        ph_spec = next((s for s in self.config.tunable_specs if "p_sw" in s.get("targets", [s["name"]])), None)
        next_ph = None
        if ph_spec:
            if ph_spec["type"] == "range" and Ph + ph_spec["step"] <= ph_spec["max"]:
                next_ph = Ph + ph_spec["step"]
            elif ph_spec["type"] == "set":
                vals = sorted(ph_spec["values"])
                for v in vals:
                    if v > Ph + 1e-6:
                        next_ph = v; break
        
        if next_ph is not None:
            updated = 0
            for k in self.Ph_min_safe.keys():
                if k <= Tm + 1e-4:
                    if self.Ph_min_safe[k] < next_ph:
                        self.Ph_min_safe[k] = next_ph
                        updated += 1
            if updated > 0:
                log(f"  【安全边界更新】检测到缩水：模具温度：{Tm}，保压压力：{Ph} → 将安全保压下限提升至 {next_ph}")
                
        return True

    def _export_records(self):
        if not self.all_records:
            return
        rows = []
        ordered_machine_keys = self.config.get_ordered_machine_param_keys()
        disp_keys = set(self.config.get_display_name_to_targets_map().keys())

        for rec in self.all_records:
            row = {
                RECORD_COL_STAGE: rec.get("stage", ""),
                RECORD_COL_FORM_ERROR: rec.get("form_error", np.nan),
                RECORD_COL_IS_SHRINK: rec.get("is_shrink", np.nan),
            }

            # 机台参数（中文显示列）
            row.update(self._machine_params_to_display(rec))

            # 其他列原样保留（避免丢失）
            for k, v in rec.items():
                if k in ["stage", "form_error", "is_shrink"]:
                    continue
                if k in ordered_machine_keys:
                    continue
                if k in disp_keys:
                    continue
                row[k] = v

            rows.append(row)

        df = pd.DataFrame(rows)
        # 排序：关键列 + 参数列（按配置顺序）+ 其余列
        ordered_cols = [RECORD_COL_STAGE, RECORD_COL_FORM_ERROR, RECORD_COL_IS_SHRINK] + self.config.get_ordered_param_display_names()
        final_cols = [c for c in ordered_cols if c in df.columns]
        remaining = [c for c in df.columns if c not in final_cols]
        df = df[final_cols + remaining]
        
        path = os.path.join(self.out_dir, "experiment_records.xlsx")
        try:
            df.to_excel(path, index=False)
        except Exception as e:
            log(f"【警告】导出历史记录失败：{e}")

    def load_initial_data(self, excel_path: str) -> Optional[torch.Tensor]:
        if not excel_path or not os.path.exists(excel_path):
            return None
        try:
            df = pd.read_excel(excel_path)
        except:
            return None
            
        collected_data = {}
        meta_names = [m["name"] for m in self.meta]
        name_to_target = {}
        for spec in self.config.tunable_specs:
            name_to_target[spec["name"]] = spec.get("targets", [spec["name"]])

        for name in meta_names:
            if name in df.columns:
                collected_data[name] = df[name].values
                continue

            # 兼容中文列名（按参数配置显示名）
            disp_name = self.config.get_param_display_name(name)
            if disp_name in df.columns:
                collected_data[name] = df[disp_name].values
                continue

            targets = name_to_target.get(name, [])
            found = False
            for t in targets:
                if t in df.columns:
                    collected_data[name] = df[t].values
                    found = True
                    break
                # 兼容中文列名（target 对应的显示名）
                disp_t = self.config.get_param_display_name(t)
                if disp_t in df.columns:
                    collected_data[name] = df[disp_t].values
                    found = True
                    break
            if not found:
                m = next((m for m in self.meta if m["name"] == name), None)
                if m and len(m["values"]) == 1:
                    collected_data[name] = np.full(len(df), m["values"][0])
                else:
                    return None
                    
        target_list = []
        for i in range(len(df)):
            row_vals = [collected_data[n][i] for n in meta_names]
            target_list.append(row_vals)
        return torch.tensor(target_list, dtype=torch.double, device=DEVICE)

    def load_existing_records(self):
        """
        Load existing records from experiment_records.xlsx and update state.
        """
        path = os.path.join(self.out_dir, "experiment_records.xlsx")
        if not os.path.exists(path):
            return
            
        try:
            raw_df = pd.read_excel(path)

            # 兼容：将“中文列名 / 旧版英文列名”统一解析为内部记录结构
            raw_rows = raw_df.to_dict("records")
            internal_records = [self._row_to_internal_record(r) for r in raw_rows]
            df = pd.DataFrame(internal_records)

            # Ensure required columns exist（内部列名）
            required = ["stage", "form_error", "is_shrink"]
            if not all(c in df.columns for c in required):
                log(f"【警告】历史记录文件缺少必要列，已跳过：{path}")
                return

            # 若存在未完成记录（评价指标为空/NaN），则自动从最早缺失批次回退截断更晚批次
            try:
                missing_mask = df["form_error"].apply(self._is_missing_form_error)
                if missing_mask.any():
                    df["_stage_rank__tmp"] = df["stage"].apply(self._stage_rank)
                    earliest_rank = int(df.loc[missing_mask, "_stage_rank__tmp"].min())
                    before_len = len(df)
                    df = df[df["_stage_rank__tmp"] <= earliest_rank].drop(columns=["_stage_rank__tmp"]).reset_index(drop=True)
                    trimmed = before_len - len(df)
                    if trimmed > 0:
                        log(f"【续跑】检测到缺失{RECORD_COL_FORM_ERROR}，已自动回退：截断 {trimmed} 条更晚批次记录（将按流程补齐后再继续）。")
                        # 写回（中文列名），避免 GUI 与实际运行不一致；失败也不影响本次运行
                        try:
                            self.all_records = df.to_dict("records")
                            self._export_records()
                        except Exception as e:
                            log(f"【警告】自动回退写回失败（可忽略）：{e}")
            except Exception as e:
                log(f"【警告】自动检测缺失记录失败：{e}")
                
            records = df.to_dict("records")
            self.all_records = records
            log(f"【续跑】已加载 {len(records)} 条历史记录：{path}")
            
            # Re-update safety boundary for each record to restore Ph_min_safe
            self._init_safety_boundary()
            for rec in records:
                # 跳过未完成的记录（form_error 留白/NaN）
                try:
                    fe_val = float(rec.get("form_error"))
                    if not math.isfinite(fe_val):
                        continue
                except Exception:
                    continue
                # Extract machine params
                m_params = {k: rec[k] for k in self.config.get_ordered_machine_param_keys() if k in rec}
                self._update_safety_boundary(m_params, rec["form_error"], rec["is_shrink"])
                
        except Exception as e:
            log(f"【警告】加载历史记录失败：{e}")
