"""
配置模块 - 包含参数定义、搜索空间生成与参数转换逻辑
"""

import numpy as np
import torch
import json
import os
import glob
from typing import List, Dict, Any, Optional
from utils import get_resource_path, get_app_path

# ===========================
# 设备配置
# ===========================
torch.set_default_dtype(torch.double)
if torch.cuda.is_available():
    DEVICE = torch.device("cuda")
    print(f"[Config] Using CUDA GPU: {torch.cuda.get_device_name(0)}")
else:
    DEVICE = torch.device("cpu")
    print("[Config] Using CPU")

# ===========================
# 默认配置
# ===========================
DEFAULT_SHRINK_THRESHOLD = 30
DEFAULT_N_INIT = 10
DEFAULT_N_ITER = 20
DEFAULT_BATCH_SIZE = 4
DEFAULT_OUT_DIR = get_app_path("output")
DEFAULT_CSV_NAME = "bo_samples.csv"
CONFIG_DIR = get_app_path("configs")

# ===========================
# 参数显示名（中文）映射
# - 用于 UI、导出表格与日志显示
# ===========================
PARAM_DISPLAY_MAP = {
    "T": "模具温度",
    "Tc": "冷却时间",
    "F": "锁模力",
    "p_vp": "VP切换压力",
    "p_sw": "保压压力",
    "delay": "延时时间",
    "delay_time": "延时时间",
    "v1": "射速1",
    "v2": "射速2",
    "v3": "射速3",
    "v4": "射速4",
    "v5": "射速5",
    "t1": "保压时间1",
    "t2": "保压时间2",
    "t3": "保压时间3",
    "t4": "保压时间4",
    "Vg": "剪口速度",
    "G": "保压梯度",
    "t_pack": "保压时间",
}

# ===========================
# 默认模板数据 (仅用于初始化)
# ===========================
_TEMPLATE_PART_A = {
    "name": "LS39860A-903",
    "fixed": {
        "Tc": 16.0, 
        "F": 8.0, 
        "t_pack": [2.0, 1.0, 0.5, 0.5]
    },
    "tunable": [
        {"name": "T",    "type": "range", "min": 136, "max": 143, "step": 1},
        {"name": "p_vp", "type": "range", "min": 700, "max": 1200, "step": 20},
        {"name": "p_sw", "type": "range", "min": 250, "max": 600, "step": 20},
        {"name": "delay", "type": "range", "min": 0.0, "max": 2.0, "step": 0.5, "targets": ["delay_time"]},
        {"name": "v1", "type": "range", "min": 5, "max": 40, "step": 5},
        {"name": "v2", "type": "range", "min": 5, "max": 40, "step": 5},
        {"name": "v3", "type": "range", "min": 5, "max": 40, "step": 5},
        {"name": "v4", "type": "range", "min": 5, "max": 40, "step": 5},
        {"name": "v5", "type": "range", "min": 5, "max": 40, "step": 5},
    ]
}

_TEMPLATE_PART_B = {
    "name": "LS39929A-901",
    "fixed": {
        "G": 40,
        "v1": 30, "v4": 30, "v5": 30,
        "t1": 1.6, "t2": 1.6, "t3": 0.4, "t4": 0.4,
        "Tc": 15, "F": 15
    },
    "tunable": [
        {"name": "T",    "type": "range", "min": 135, "max": 145, "step": 1},
        {"name": "p_vp", "type": "range", "min": 800, "max": 1200, "step": 20},
        {"name": "p_sw", "type": "range", "min": 400, "max": 800, "step": 20},
        {"name": "Vg",   "type": "set",   "values": [5, 30]}
    ]
}

# ===========================
# 通用配置类
# ===========================
class InjectionMoldingConfig:
    def __init__(self, config_dict: Dict):
        self.name = config_dict.get("name", "UnknownPart")
        # 1. 读取固定参数
        self.fixed_params = config_dict.get("fixed", {})
        
        # 2. 读取可调参数定义
        self.tunable_specs = config_dict.get("tunable", [])
        
        # 3. 读取 UI 顺序
        self.ui_order = config_dict.get("ui_order", [])

    def get_param_display_name(self, key: str) -> str:
        """
        将内部参数名（spec name / target / fixed key）映射为中文显示名。
        若无法映射，则回退为原始 key。
        """
        if key in PARAM_DISPLAY_MAP:
            return PARAM_DISPLAY_MAP[key]
        # 兼容：key 可能是 target，尝试找到其所属 spec，再用 spec.name 映射
        for spec in self.tunable_specs:
            targets = spec.get("targets", [spec["name"]])
            if key in targets:
                return PARAM_DISPLAY_MAP.get(spec["name"], spec["name"])
        return key

    def get_display_name_to_targets_map(self) -> Dict[str, List[str]]:
        """
        中文显示名 -> 目标机台参数名列表（targets）。
        用于从“中文列名”表格反向恢复到内部 machine_params 结构。
        """
        m: Dict[str, List[str]] = {}
        for spec in self.tunable_specs:
            disp = PARAM_DISPLAY_MAP.get(spec["name"], spec["name"])
            targets = spec.get("targets", [spec["name"]])
            m.setdefault(disp, [])
            for t in targets:
                if t not in m[disp]:
                    m[disp].append(t)
        for k in self.fixed_params.keys():
            disp = PARAM_DISPLAY_MAP.get(k, k)
            m.setdefault(disp, [])
            if k not in m[disp]:
                m[disp].append(k)
        return m

    def get_ordered_param_display_names(self) -> List[str]:
        """
        获取按照 UI/Config 定义顺序排列的“中文参数显示名”列表（去重后）。
        注意：此处只返回机台参数列（不包含“阶段/面型评价指标/是否缩水”等记录字段）。
        """
        ordered_keys = self.get_ordered_machine_param_keys()
        names: List[str] = []
        seen = set()
        for k in ordered_keys:
            disp = self.get_param_display_name(k)
            if disp not in seen:
                names.append(disp)
                seen.add(disp)
        return names
        
    def get_search_space(self) -> Dict[str, List[float]]:
        """
        生成算法需要的搜索网格
        """
        grid = {}
        for spec in self.tunable_specs:
            name = spec["name"]
            p_type = spec["type"]
            
            # --- A. 范围类型 (Range) ---
            if p_type == "range":
                vals = np.arange(spec["min"], spec["max"] + 1e-9, spec["step"]).tolist()
                grid[name] = [round(x, 2) for x in vals]
            
            # --- B. 集合类型 (Set) ---
            # 适用于：v2, v3 同时为 5 或 30
            elif p_type == "set":
                grid[name] = sorted(spec["values"])
                
            # --- C. 选项/套餐类型 (Choice) ---
            # 适用于复杂的 vector 映射
            elif p_type == "choice":
                # 算法只看到索引 [0, 1, 2...]
                grid[name] = list(range(len(spec["options"])))
            
            # --- D. 混合模式 (Mixed) ---
            elif p_type == "mixed":
                vals = set()
                for sub_cfg in spec["configs"]:
                    if sub_cfg["type"] == "fixed":
                        vals.add(sub_cfg["value"])
                    elif sub_cfg["type"] == "range":
                        r_vals = np.arange(sub_cfg["min"], sub_cfg["max"] + 1e-9, sub_cfg["step"])
                        for v in r_vals:
                            vals.add(round(v, 2))
                grid[name] = sorted(list(vals))
                
            # --- E. 固定模式 (Fixed) ---
            elif p_type == "fixed":
                # 固定值也需要进入搜索空间，但只有一个值
                grid[name] = [spec.get("value", 0)]

                
        return grid
    
    # 兼容性：确保能从 JSON 文件加载
    @classmethod
    def load_json(cls, path: str):
        """从 JSON 文件加载配置"""
        with open(path, 'r', encoding='utf-8') as f:
            config_dict = json.load(f)
        return cls(config_dict)

    def translate_to_machine(self, opt_point: Dict[str, float]) -> Dict[str, float]:
        """
        将算法的解（包含虚拟变量）翻译为物理参数
        """
        # 1. 先复制固定参数
        machine_params = self.fixed_params.copy()
        
        # 2. 遍历所有可调参数进行覆盖
        for spec in self.tunable_specs:
            name = spec["name"]
            val = opt_point.get(name) 
            
            if val is None:
                continue

            # 确定要赋值的目标参数名（列表）
            # 如果没有 targets 字段，说明就是通过 name 自己控制自己
            targets = spec.get("targets", [name])
            
            if spec["type"] == "choice":
                # 选项模式：从 options 里取值
                idx = int(round(val)) # 确保是整数索引
                # 防止索引越界
                if idx < 0: idx = 0
                if idx >= len(spec["options"]): idx = len(spec["options"]) - 1
                    
                selected_vals = spec["options"][idx] 
                
                # 如果是列表结构，按顺序对应 targets
                if isinstance(selected_vals, list):
                    for i, t_name in enumerate(targets):
                        if i < len(selected_vals):
                            machine_params[t_name] = selected_vals[i]
                # 如果是字典结构，直接 update
                elif isinstance(selected_vals, dict):
                     machine_params.update(selected_vals)
                     
            else:
                # 范围或集合模式：直接赋值
                # 如果 targets 有多个（绑定模式），则把同一个 val 赋给所有 target
                for t_name in targets:
                    machine_params[t_name] = val
                    
        return machine_params

    def snap_to_grid(self, opt_point: Dict[str, float]) -> Dict[str, float]:
        """
        将连续的优化结果吸附到最近的合法离散值（根据 step 或 values）
        """
        grid = self.get_search_space()
        snapped_point = {}
        
        for name, val in opt_point.items():
            if name not in grid:
                snapped_point[name] = val
                continue
                
            candidates = np.array(grid[name])
            # 找到最近的值
            idx = (np.abs(candidates - val)).argmin()
            snapped_point[name] = float(candidates[idx])
            
        return snapped_point

    def translate_to_optimization(self, machine_params_dict: Dict[str, Any]) -> torch.Tensor:
        """
        将用户输入的物理参数字典转换回归一化的张量空间 [0.0, 1.0]
        """
        opt_values = []
        search_space = self.get_search_space()
        
        for spec in self.tunable_specs:
            name = spec["name"]
            p_type = spec["type"]
            targets = spec.get("targets", [name])
            
            # 1. 提取物理值
            if p_type == "choice":
                # 选项模式：寻找最匹配的 option 索引
                best_idx = 0
                min_err = float('inf')
                for idx, opt_val in enumerate(spec["options"]):
                    err = 0.0
                    if isinstance(opt_val, list):
                        for i, t_name in enumerate(targets):
                            if i < len(opt_val) and t_name in machine_params_dict:
                                err += abs(float(machine_params_dict[t_name]) - float(opt_val[i]))
                    elif isinstance(opt_val, dict):
                        for t_name, t_val in opt_val.items():
                            if t_name in machine_params_dict:
                                err += abs(float(machine_params_dict[t_name]) - float(t_val))
                    else: # 单个值的情况（虽然 choice 通常对应列表或字典）
                        if targets[0] in machine_params_dict:
                            err = abs(float(machine_params_dict[targets[0]]) - float(opt_val))
                            
                    if err < min_err:
                        min_err = err
                        best_idx = idx
                val = float(best_idx)
            else:
                # 范围、集合、混合或固定模式：直接从字典中取值
                # 优先取 targets[0]，如果不存在则尝试 name
                val = machine_params_dict.get(targets[0])
                if val is None:
                    val = machine_params_dict.get(name)
                
                if val is None:
                    # 如果用户未提供，回退到搜索空间的中值
                    grid_vals = search_space[name]
                    val = grid_vals[len(grid_vals) // 2]
                else:
                    val = float(val)
            
            opt_values.append(val)
            
        # 2. 归一化到 [0, 1]
        opt_tensor = torch.tensor(opt_values, dtype=torch.double)
        
        # 计算 mins 和 maxs
        mins_list = []
        maxs_list = []
        for spec in self.tunable_specs:
            name = spec["name"]
            grid_vals = search_space[name]
            mins_list.append(min(grid_vals))
            maxs_list.append(max(grid_vals))
            
        mins = torch.tensor(mins_list, dtype=torch.double)
        maxs = torch.tensor(maxs_list, dtype=torch.double)
        ranges = maxs - mins
        ranges[ranges == 0] = 1.0
        
        normalized_tensor = (opt_tensor - mins) / ranges
        # 确保在 [0, 1] 范围内
        normalized_tensor = torch.clamp(normalized_tensor, 0.0, 1.0)
        
        return normalized_tensor

    def get_ordered_machine_param_keys(self) -> List[str]:
        """获取按照 UI/Config 定义顺序排列的机台参数名列表"""
        if self.ui_order:
            # 过滤掉可能存在的重复项或无效项，同时保留顺序
            keys = []
            seen = set()
            for k in self.ui_order:
                if k not in seen:
                    keys.append(k)
                    seen.add(k)
            
            # 收集所有已知参数名
            all_known = set(self.fixed_params.keys())
            for spec in self.tunable_specs:
                targets = spec.get("targets", [spec["name"]])
                all_known.update(targets)
            
            # 把遗漏的加到后面
            remaining = sorted(list(all_known - seen))
            keys.extend(remaining)
            
            # 只返回那些实际上存在的参数名
            final_keys = [k for k in keys if k in all_known]
            return final_keys

        # Fallback to old logic
        keys = []
        # 1. Tunable targets (UI order)
        for spec in self.tunable_specs:
            targets = spec.get("targets", [spec["name"]])
            for t in targets:
                if t not in keys:
                    keys.append(t)
        
        # 2. Fixed params (remaining)
        fixed_keys = sorted(self.fixed_params.keys())
        for k in fixed_keys:
            if k not in keys:
                keys.append(k)
                
        return keys

# ===========================
# 配置管理逻辑
# ===========================

def ensure_config_dir():
    """确保配置目录存在，如果为空则从资源文件拷贝或生成默认文件"""
    if not os.path.exists(CONFIG_DIR):
        try:
            os.makedirs(CONFIG_DIR)
        except Exception as e:
            print(f"[Warning] Failed to create config dir: {e}")
            return
        
    # 检查是否为空
    files = glob.glob(os.path.join(CONFIG_DIR, "*.json"))
    if not files:
        # 尝试从 bundled 资源拷贝 (PyInstaller)
        bundled_configs = get_resource_path("configs")
        if os.path.exists(bundled_configs) and os.path.abspath(bundled_configs) != os.path.abspath(CONFIG_DIR):
            import shutil
            print(f"[Config] Initializing configs from {bundled_configs}")
            for f in glob.glob(os.path.join(bundled_configs, "*.json")):
                try:
                    shutil.copy(f, CONFIG_DIR)
                except Exception as e:
                    print(f"[Warning] Failed to copy bundled config {f}: {e}")
        
        # 再次检查，如果还是空，则生成默认模板
        files = glob.glob(os.path.join(CONFIG_DIR, "*.json"))
        if not files:
            print("[Config] Generating default templates...")
            save_config("LS39860A-903", _TEMPLATE_PART_A)
            save_config("LS39929A-901", _TEMPLATE_PART_B)

def get_available_parts() -> List[str]:
    """获取所有可用件号（文件名，不含后缀）"""
    ensure_config_dir()
    files = glob.glob(os.path.join(CONFIG_DIR, "*.json"))
    parts = [os.path.splitext(os.path.basename(f))[0] for f in files]
    return sorted(parts)

def save_config(part_name: str, config_dict: Dict):
    """保存配置到文件"""
    # 仅确保目录存在，避免调用 ensure_config_dir 导致递归
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR)

    # 确保 name 字段与文件名一致
    config_dict["name"] = part_name
    path = os.path.join(CONFIG_DIR, f"{part_name}.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(config_dict, f, indent=4, ensure_ascii=False)

def get_config(name: str) -> InjectionMoldingConfig:
    """
    加载配置
    name: 可以是件号名称（不含后缀），也可以是完整路径
    """
    ensure_config_dir()
    
    # 1. 尝试直接作为路径加载
    if os.path.isfile(name):
        return InjectionMoldingConfig.load_json(name)
        
    # 2. 尝试从 configs 目录加载
    path = os.path.join(CONFIG_DIR, f"{name}.json")
    if os.path.exists(path):
        return InjectionMoldingConfig.load_json(path)
        
    # 3. 失败
    # Try alias mapping
    if name == "PartA":
        return get_config("LS39860A-903")
    if name == "PartB":
        return get_config("LS39929A-901")
        
    raise ValueError(f"Unknown config name or file not found: {name}")

# 初始化目录
ensure_config_dir()
