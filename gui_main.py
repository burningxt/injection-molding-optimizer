import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext, simpledialog
import sys
import threading
import json
import os
import queue
import builtins
import pandas as pd

from config import (
    InjectionMoldingConfig,
    get_config,
    get_available_parts,
    save_config,
    CONFIG_DIR,
    DEFAULT_OUT_DIR,
    PARAM_DISPLAY_MAP,
)
from utils import get_app_path
# 假设 main.py 中有一个 run_optimization 函数，如果没有则需重构
# 目前先模拟调用 main.py
from main import main as run_algo

RECORD_COL_STAGE = "阶段"
RECORD_COL_FORM_ERROR = "面型评价指标"
RECORD_COL_IS_SHRINK = "是否缩水"

MODE_DISPLAY_VALUES = ["模拟", "正式"]
MODE_DISPLAY_TO_ARG = {
    "模拟": "auto",
    "正式": "manual",
    # 兼容旧会话/旧 UI 文案
    "模拟 (auto)": "auto",
    "正式 (manual)": "manual",
}

INIT_MODE_DISPLAY_VALUES = ["自动", "手动"]
INIT_MODE_DISPLAY_TO_ARG = {
    "自动": "auto",
    "手动": "manual",
    # 兼容旧会话/旧 UI 文案
    "自动 (auto)": "auto",
    "手动 (manual)": "manual",
}

class GUIConfigAdapter:
    """辅助类，用于 GUI 和 Config 对象之间的转换"""
    @staticmethod
    def convert_to_ui_format(source_cfg):
        # 加载配置
        cfg = source_cfg.copy()
        
        # 将固定参数也移动到可调参数列表（设为 fixed 类型），方便 UI 显示和修改
        fixed = cfg.get("fixed", {})
        tunable = cfg.get("tunable", [])
        
        # 将 fixed 参数转换为 tunable 格式
        new_tunable = []
        
        # 1. 先把原有的 tunable 加进来 (应用汉化)
        for t in tunable:
            t_new = t.copy()
            orig_name = t_new["name"]
            display_name = PARAM_DISPLAY_MAP.get(orig_name, orig_name)
            if display_name != orig_name:
                 t_new["name"] = display_name
                 # 确保 targets 存在，以便 translate_to_machine 能正确映射回原名
                 if "targets" not in t_new:
                     t_new["targets"] = [orig_name]
            new_tunable.append(t_new)
        
        # 2. 把 fixed 加进来
        for name, val in fixed.items():
            # 检查是否已经在 tunable 里（避免重复）
            # 注意：此时 new_tunable 里的 name 已经是汉化后的了，所以要比较 targets 或原始 name
            # 但这里简单起见，我们假设 tunable 里的 targets 包含了原始 name
            
            # 检查 new_tunable 中是否有任何项的 targets 包含当前 name
            already_exists = False
            for t in new_tunable:
                targets = t.get("targets", [t["name"]])
                # 如果 t["name"] 没汉化，targets 就是 [name]。如果汉化了，targets 是 [orig_name]。
                # 但是要注意，PARAM_DISPLAY_MAP 会把缩写映射为中文显示名
                # 那么 targets=["T"]。
                if name in targets:
                    already_exists = True
                    break
            
            if already_exists:
                continue
                
            if isinstance(val, (int, float)):
                display_name = PARAM_DISPLAY_MAP.get(name, name)
                new_tunable.append({
                    "name": display_name,
                    "type": "fixed",
                    "value": val,
                    "targets": [name]
                })
            elif isinstance(val, list):
                # 列表类型（如 t_pack），为了展示，可以用 mixed 或特殊 fixed
                # 针对 t_pack = [t1, t2, t3, t4] 特殊处理
                if name == "t_pack" and len(val) == 4:
                    for i, sub_name in enumerate(["t1", "t2", "t3", "t4"]):
                         disp = PARAM_DISPLAY_MAP.get(sub_name, sub_name)
                         new_tunable.append({
                             "name": disp, 
                             "type": "fixed", 
                             "value": val[i],
                             "targets": [sub_name]
                         })
                else:
                    # 其他列表，作为 json/string
                    pass

        cfg["tunable"] = new_tunable
        cfg["fixed"] = {} # 清空 fixed，因为都移到 UI 上了
        
        # 如果配置中有 ui_order，尝试根据它对 new_tunable 进行排序
        ui_order = cfg.get("ui_order", [])
        if ui_order:
            # 建立 name -> index 映射
            order_map = {name: i for i, name in enumerate(ui_order)}
            
            def sort_key(item):
                # 尝试找到该参数对应的任何一个 target 在 order_map 中的最小索引
                targets = item.get("targets", [item["name"]])
                indices = [order_map.get(t, 99999) for t in targets]
                return min(indices) if indices else 99999
                
            new_tunable.sort(key=sort_key)
            
        return cfg

class RedirectText:
    """重定向 stdout 到 Tkinter Text 控件"""
    def __init__(self, text_widget, queue):
        self.text_widget = text_widget
        self.queue = queue

    def write(self, string):
        self.queue.put(string)

    def flush(self):
        pass

class ParamRowFrame(ttk.Frame):
    """参数配置行组件"""
    def __init__(self, parent, param_data, on_delete=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.param_data = param_data
        self.on_delete = on_delete
        self.editable = True  # 默认可编辑状态
        
        # 1. Checkbox for Linking
        self.var_selected = tk.BooleanVar(value=False)
        self.chk_select = ttk.Checkbutton(self, variable=self.var_selected)
        self.chk_select.pack(side=tk.LEFT, padx=5)

        # 2. Name Entry
        self.var_name = tk.StringVar(value=param_data.get("name", ""))
        self.ent_name = ttk.Entry(self, textvariable=self.var_name, width=15)
        self.ent_name.pack(side=tk.LEFT, padx=5)

        # 3. Type Selection (汉化)
        # 内部 key 保持英文，UI 显示中文
        self.type_map = {
            "固定值": "fixed",
            "范围调节": "range",
            "离散集合": "set",
            "模式选择": "choice",
            "混合模式": "mixed"
        }
        self.type_map_rev = {v: k for k, v in self.type_map.items()}
        
        current_type = param_data.get("type", "range")
        display_type = self.type_map_rev.get(current_type, "范围调节")
        
        self.var_type = tk.StringVar(value=display_type)
        self.cbo_type = ttk.Combobox(self, textvariable=self.var_type, 
                                     values=list(self.type_map.keys()), 
                                     width=10, state="readonly")
        self.cbo_type.pack(side=tk.LEFT, padx=5)
        self.cbo_type.bind("<<ComboboxSelected>>", self._on_type_change)

        # 4. Details Frame (Dynamic)
        self.frm_details = ttk.Frame(self)
        self.frm_details.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        # 5. Delete Button
        self.btn_del = ttk.Button(self, text="❌", width=3, command=self._delete_me)
        self.btn_del.pack(side=tk.RIGHT, padx=5)

        # Init details
        self._refresh_details()

    def set_editable(self, editable):
        self.editable = editable
        state = "normal" if editable else "disabled"
        entry_state = "normal" if editable else "readonly"
        cbo_state = "readonly" if editable else "disabled"
        
        self.chk_select.configure(state=state)
        self.ent_name.configure(state=entry_state)
        self.cbo_type.configure(state=cbo_state)
        self.btn_del.configure(state=state)
        
        # 更新详情区域控件状态（不重建）
        self._update_details_state()

    def _delete_me(self):
        if self.on_delete:
            self.on_delete(self)
            
    def _on_type_change(self, event):
        # Reset the created flag to force widget recreation on type change
        if hasattr(self, '_details_created'):
            delattr(self, '_details_created')
        self._refresh_details()

    def _create_details_widgets(self, p_type):
        """Create widgets based on parameter type"""
        try:
            # Clear old widgets
            for widget in self.frm_details.winfo_children():
                widget.destroy()
    
            if p_type == "fixed":
                ttk.Label(self.frm_details, text="数值：").pack(side=tk.LEFT)
                self.ent_val = ttk.Entry(self.frm_details, width=10)
                self.ent_val.insert(0, str(self.param_data.get("value", 0)))
                self.ent_val.pack(side=tk.LEFT, padx=2)
    
            elif p_type == "range":
                ttk.Label(self.frm_details, text="最小值：").pack(side=tk.LEFT)
                self.ent_min = ttk.Entry(self.frm_details, width=5)
                self.ent_min.insert(0, str(self.param_data.get("min", 0)))
                self.ent_min.pack(side=tk.LEFT, padx=2)
    
                ttk.Label(self.frm_details, text="最大值：").pack(side=tk.LEFT)
                self.ent_max = ttk.Entry(self.frm_details, width=5)
                self.ent_max.insert(0, str(self.param_data.get("max", 100)))
                self.ent_max.pack(side=tk.LEFT, padx=2)
    
                ttk.Label(self.frm_details, text="步长：").pack(side=tk.LEFT)
                self.ent_step = ttk.Entry(self.frm_details, width=5)
                self.ent_step.insert(0, str(self.param_data.get("step", 1)))
                self.ent_step.pack(side=tk.LEFT, padx=2)
    
            elif p_type == "set":
                ttk.Label(self.frm_details, text="可选值（逗号分隔）：").pack(side=tk.LEFT)
                self.ent_values = ttk.Entry(self.frm_details, width=20)
                vals = self.param_data.get("values", [])
                self.ent_values.insert(0, ",".join(map(str, vals)))
                self.ent_values.pack(side=tk.LEFT, fill=tk.X, expand=True)
    
            elif p_type == "choice" or p_type == "mixed":
                self.btn_edit_opts = ttk.Button(self.frm_details, text="编辑选项 / JSON...",
                                                command=self._edit_complex_options)
                self.btn_edit_opts.pack(side=tk.LEFT)
    
                # Store complex data in memory, not UI
                self.complex_data = self.param_data.get("options") or self.param_data.get("configs") or []
        except Exception as e:
            print(f"Warning: Failed to create details widgets for type '{p_type}': {e}")
    def _update_details_state(self):
        """Update widget states without rebuilding"""
        entry_state = "normal" if self.editable else "readonly"
        btn_state = "normal" if self.editable else "disabled"
        
        display_type = self.var_type.get()
        p_type = self.type_map.get(display_type, "range")
        
        if p_type == "fixed" and hasattr(self, 'ent_val'):
            try:
                self.ent_val.configure(state=entry_state)
            except Exception as e:
                print(f"Warning: Failed to configure ent_val: {e}")
    
        elif p_type == "range":
            if hasattr(self, 'ent_min'):
                try:
                    self.ent_min.configure(state=entry_state)
                except Exception as e:
                    print(f"Warning: Failed to configure ent_min: {e}")
            if hasattr(self, 'ent_max'):
                try:
                    self.ent_max.configure(state=entry_state)
                except Exception as e:
                    print(f"Warning: Failed to configure ent_max: {e}")
            if hasattr(self, 'ent_step'):
                try:
                    self.ent_step.configure(state=entry_state)
                except Exception as e:
                    print(f"Warning: Failed to configure ent_step: {e}")
    
        elif p_type == "set" and hasattr(self, 'ent_values'):
            try:
                self.ent_values.configure(state=entry_state)
            except Exception as e:
                print(f"Warning: Failed to configure ent_values: {e}")
    
        elif p_type in ("choice", "mixed") and hasattr(self, 'btn_edit_opts'):
            try:
                self.btn_edit_opts.configure(state=btn_state)
            except Exception as e:
                print(f"Warning: Failed to configure btn_edit_opts: {e}")

    def _refresh_details(self):
        """Initialize or refresh details area"""
        display_type = self.var_type.get()
        p_type = self.type_map.get(display_type, "range")

        if not hasattr(self, '_details_created'):
            # First call: create widgets
            self._create_details_widgets(p_type)
            self._details_created = True
        else:
            # Subsequent calls: update states only
            self._update_details_state()
    def _edit_complex_options(self):
        # Pop up a simple text editor for JSON input
        top = tk.Toplevel(self)
        top.title("编辑复杂选项")
        txt = scrolledtext.ScrolledText(top, width=40, height=10)
        txt.pack(fill=tk.BOTH, expand=True)
        
        # Load current
        try:
            txt.insert(tk.END, json.dumps(self.complex_data, indent=2))
        except:
            pass
            
        def save():
            raw = txt.get("1.0", tk.END).strip()
            try:
                self.complex_data = json.loads(raw)
                top.destroy()
            except Exception as e:
                messagebox.showerror("错误", f"格式无效：{e}")
                
        ttk.Button(top, text="保存", command=save).pack(pady=5)

    def get_data(self):
        """Collect data from UI widgets"""
        data = {
            "name": self.var_name.get(),
            "type": self.type_map.get(self.var_type.get(), "range"),
            "targets": self.param_data.get("targets", [self.var_name.get()]) # Preserve existing targets or default to self
        }
        
        p_type = data["type"]
        if p_type == "fixed":
             try:
                data["value"] = float(self.ent_val.get())
             except ValueError:
                pass
        elif p_type == "range":
            try:
                data["min"] = float(self.ent_min.get())
                data["max"] = float(self.ent_max.get())
                data["step"] = float(self.ent_step.get())
            except ValueError:
                pass
        elif p_type == "set":
            try:
                raw = self.ent_values.get().split(",")
                data["values"] = [float(x.strip()) for x in raw if x.strip()]
            except ValueError:
                pass
        elif p_type == "choice":
            data["options"] = getattr(self, "complex_data", [])
        elif p_type == "mixed":
            data["configs"] = getattr(self, "complex_data", [])
            
        return data

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("注塑成型工艺参数智能推荐系统")
        self.geometry("1000x700")

        self.current_config_rows = []
        self.current_fixed_params = {} 
        self.current_stop_event = None
        self.current_thread = None
        
        self._init_ui()
        self._init_log_queue()
        
        # Load last session if exists, otherwise load default
        if not self._load_session():
            # 默认加载列表中的第一个
            parts = get_available_parts()
            if parts:
                self.cbo_part_number.set(parts[0])
                self._load_part_config(parts[0])

    def _init_ui(self):
        # === Top Toolbar ===
        frm_top = ttk.Frame(self)
        frm_top.pack(side=tk.TOP, fill=tk.X, padx=5, pady=5)
        
        ttk.Label(frm_top, text="件号：").pack(side=tk.LEFT)
        self.cbo_part_number = ttk.Combobox(frm_top, state="readonly", width=20)
        self.cbo_part_number.pack(side=tk.LEFT, padx=5)
        self.cbo_part_number.bind("<<ComboboxSelected>>", self._on_part_change)
        
        # 刷新件号列表
        self._refresh_part_list()

        # 删除旧的配置名称输入框和加载按钮
        # ttk.Label(frm_top, text="配置名称:").pack(side=tk.LEFT)
        # self.ent_cfg_name = ttk.Entry(frm_top, width=20)
        # self.ent_cfg_name.pack(side=tk.LEFT, padx=5)
        # ttk.Button(frm_top, text="加载配置", command=self._load_config).pack(side=tk.LEFT, padx=5)
        
        ttk.Button(frm_top, text="保存配置", command=self._save_config).pack(side=tk.LEFT, padx=5)
        
        # === Main Content ===
        # 上下可拖拽：上方(模型设置+参数配置) / 下方(交互输入+日志)
        main_paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 上方：左右两栏
        paned = ttk.PanedWindow(main_paned, orient=tk.HORIZONTAL)
        main_paned.add(paned, weight=2)
        
        # -- Left Panel: Algorithm Settings --
        frm_left = ttk.LabelFrame(paned, text="模型设置", width=250)
        paned.add(frm_left, weight=1)
        
        # Optimizer Selection
        # f_opt = ttk.Frame(frm_left)
        # f_opt.pack(fill=tk.X, padx=5, pady=2)
        # ttk.Label(f_opt, text="模型:", width=12).pack(side=tk.LEFT)
        # self.cbo_optimizer = ttk.Combobox(f_opt, values=["SAASGP (Default)", "PyBADS", "TuRBO", "StandardBO", "SMAC3"], state="readonly")
        # self.cbo_optimizer.current(3) # StandardBO is index 3
        # self.cbo_optimizer.pack(side=tk.RIGHT, expand=True, fill=tk.X)
        # self.cbo_optimizer.bind("<<ComboboxSelected>>", self._on_optimizer_change)

        # 隐藏模型选择，默认使用 StandardBO
        # 为了兼容后续代码对 self.cbo_optimizer 的引用，这里创建一个隐藏的 Combobox 或者模拟对象
        # 简单起见，我们还是创建它，但不 pack 显示出来，并设置默认值为 StandardBO
        f_opt = ttk.Frame(frm_left)
        # f_opt.pack(fill=tk.X, padx=5, pady=2) # 不显示 Frame
        self.cbo_optimizer = ttk.Combobox(f_opt, values=["StandardBO"], state="readonly")
        self.cbo_optimizer.current(0) # StandardBO


        self._add_setting(frm_left, "初始数据：", "n_init", "20")
        self._add_setting(frm_left, "批次数：", "n_iter", "10")
        self._add_setting(frm_left, "批次大小：", "batch_size", "4")
        
        # Init Mode Selection
        f_init = ttk.Frame(frm_left)
        f_init.pack(fill=tk.X, padx=5, pady=6)
        ttk.Label(f_init, text="初始采样：", width=12).pack(side=tk.LEFT)
        self.cbo_init_mode = ttk.Combobox(f_init, values=INIT_MODE_DISPLAY_VALUES, state="readonly")
        self.cbo_init_mode.current(0)
        self.cbo_init_mode.pack(side=tk.RIGHT, expand=True, fill=tk.X)
        self.cbo_init_mode.bind("<<ComboboxSelected>>", self._on_init_mode_change)

        # Excel File Selection (Hidden by default)
        self.frm_excel = ttk.Frame(frm_left)
        
        self.var_excel_path = tk.StringVar()
        self.ent_excel = ttk.Entry(self.frm_excel, textvariable=self.var_excel_path, state="readonly")
        self.ent_excel.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(self.frm_excel, text="📂", width=3, command=self._browse_excel).pack(side=tk.LEFT)

        # Mode Selection
        f_mode = ttk.Frame(frm_left)
        f_mode.pack(fill=tk.X, padx=5, pady=6)
        ttk.Label(f_mode, text="运行模式：", width=12).pack(side=tk.LEFT)
        self.cbo_mode = ttk.Combobox(f_mode, values=MODE_DISPLAY_VALUES, state="readonly")
        # 默认使用“正式模式”：需要用户手动输入面型评价指标
        self.cbo_mode.current(1)
        self.cbo_mode.pack(side=tk.RIGHT, expand=True, fill=tk.X)
        
        # -- Right Panel: Tunable Params --
        frm_right = ttk.LabelFrame(paned, text="参数配置", width=600)
        paned.add(frm_right, weight=3)
        
        # Param Toolbar
        frm_p_tool = ttk.Frame(frm_right)
        frm_p_tool.pack(fill=tk.X, padx=5, pady=5)
        
        # Edit Mode Toggle
        self.var_edit_mode = tk.BooleanVar(value=False)
        self.chk_edit_mode = ttk.Checkbutton(frm_p_tool, text="✏️ 启用编辑",
                                             variable=self.var_edit_mode, command=self._toggle_edit_mode)
        self.chk_edit_mode.pack(side=tk.LEFT, padx=5)
        
        ttk.Separator(frm_p_tool, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=5)

        self.btn_add_param = ttk.Button(frm_p_tool, text="添加参数", command=self._add_param, state="disabled")
        self.btn_add_param.pack(side=tk.LEFT, padx=2)
        
        self.btn_link_param = ttk.Button(frm_p_tool, text="🔗 绑定选中参数", command=self._link_params, state="disabled")
        self.btn_link_param.pack(side=tk.LEFT, padx=2)
        
        # Scrollable Area
        self.canvas = tk.Canvas(frm_right)
        self.scrollbar = ttk.Scrollbar(frm_right, orient="vertical", command=self.canvas.yview)
        self.scroll_frame = ttk.Frame(self.canvas)
        
        self.scroll_frame.bind(
                    "<Configure>",
                    lambda e: self._update_canvas_scrollregion()
                )
        
        self.canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # 右侧“参数配置”滚轮支持（Windows）
        def _on_param_mousewheel(event):
            # event.delta: Windows 通常为 120 的倍数
            try:
                self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except Exception:
                pass
            return "break"

        def _bind_param_mousewheel(_event=None):
            # 进入右侧区域时才绑定，避免影响其它区域滚动
            self.bind_all("<MouseWheel>", _on_param_mousewheel)

        def _unbind_param_mousewheel(_event=None):
            try:
                self.unbind_all("<MouseWheel>")
            except Exception:
                pass

        for _w in (frm_right, self.canvas, self.scroll_frame):
            _w.bind("<Enter>", _bind_param_mousewheel)
            _w.bind("<Leave>", _unbind_param_mousewheel)
        
        # === Bottom Panel: Log & Run ===
        frm_bottom = ttk.Frame(main_paned)
        main_paned.add(frm_bottom, weight=3)
        
        frm_btns = ttk.Frame(frm_bottom)
        frm_btns.pack(side=tk.TOP, pady=5)

        self.btn_run = ttk.Button(frm_btns, text="▶ 继续/开始寻优", command=self._run_optimization)
        self.btn_run.pack(side=tk.LEFT, padx=10)

        self.btn_new = ttk.Button(frm_btns, text="🗑️ 清除历史并重新开始", command=self._reset_and_run)
        self.btn_new.pack(side=tk.LEFT, padx=10)

        self.btn_history = ttk.Button(frm_btns, text="📜 历史记录管理", command=self._open_history_manager)
        self.btn_history.pack(side=tk.LEFT, padx=10)

        self.btn_exit = ttk.Button(frm_btns, text="💾 保存并退出", command=self._save_and_exit)
        self.btn_exit.pack(side=tk.LEFT, padx=10)
        
        # === 新增：交互输入区 ===
        self.frm_input = ttk.Frame(frm_bottom)
        self.frm_input.pack(side=tk.TOP, fill=tk.X, pady=5)
        
        # 用 grid 让输入框随窗口宽度自动拉伸
        self.frm_input.columnconfigure(2, weight=1)

        ttk.Label(self.frm_input, text="交互输入：", width=10).grid(row=0, column=0, padx=5, sticky="w")
        
        self.var_input_prompt = tk.StringVar(value="等待程序请求输入...")
        self.lbl_prompt = ttk.Label(self.frm_input, textvariable=self.var_input_prompt, foreground="blue")
        self.lbl_prompt.grid(row=0, column=1, padx=5, sticky="w")
        
        self.ent_input = ttk.Entry(self.frm_input, state='disabled')
        self.ent_input.grid(row=0, column=2, padx=5, sticky="ew")
        self.ent_input.bind("<Return>", lambda e: self._submit_input()) # 回车键提交
        
        # 新增：缩水标记复选框
        self.var_is_shrink = tk.BooleanVar(value=False)
        self.chk_shrink = ttk.Checkbutton(self.frm_input, text=RECORD_COL_IS_SHRINK, variable=self.var_is_shrink, state='disabled')
        self.chk_shrink.grid(row=0, column=3, padx=5, sticky="w")

        self.btn_submit = ttk.Button(self.frm_input, text="提交", command=self._submit_input, state='disabled')
        self.btn_submit.grid(row=0, column=4, padx=5, sticky="w")
        
        # 用于线程同步的事件
        self.input_event = threading.Event()
        self.input_value = None
        # =======================
        
        self.txt_log = scrolledtext.ScrolledText(frm_bottom, height=10, state='disabled')
        self.txt_log.pack(fill=tk.BOTH, expand=True)

        # 初始分隔线位置：尽量让上方高度接近左侧“运行模式”区域高度，
        # 这样右侧“参数配置”可视区不会过高，交互输入/日志获得更大空间。
        def _init_main_sash():
                    try:
                        self.update_idletasks()
                        # 让上方面板更贴近左侧最后一项（运行模式）的实际需求高度，
                        # 从而压缩左右栏底部的多余空白；左右同高，因此右侧也会对齐。
                        req_height = frm_left.winfo_reqheight()
                        paned_height = main_paned.winfo_height()
                        
                        # 修复：打包后 EXE 中 winfo_reqheight 可能返回 0 或 1，使用保底值
                        if req_height < 100:
                            # 使用硬编码的合理高度（模型设置区域约 300px）
                            req_height = 300
                        
                        # 修复：确保 paned_height 有效
                        if paned_height < 100:
                            paned_height = 700  # 窗口默认高度
                        
                        target = int(req_height + 8)
        
                        # 保底/上限，避免极端窗口尺寸下异常
                        min_top = 200  # 增加保底值确保参数配置区域可见
                        min_bottom = 200
                        target = max(min_top, target)
                        max_target = max(min_top, paned_height - min_bottom)
                        target = min(target, max_target)
                        main_paned.sashpos(0, target)
                    except Exception as e:
                        # 修复：异常时使用默认分隔位置
                        try:
                            main_paned.sashpos(0, 250)
                        except:
                            pass

        self.after(80, _init_main_sash)
        self.after(400, _init_main_sash)

    def _update_canvas_scrollregion(self):
        """更新 Canvas 滚动区域，打包后保护性调用"""
        try:
            if hasattr(self, 'canvas') and self.canvas.winfo_exists():
                bbox = self.canvas.bbox("all")
                if bbox:
                    self.canvas.configure(scrollregion=bbox)
                else:
                    # 如果没有 bbox，设置一个默认的最小滚动区域
                    self.canvas.configure(scrollregion=(0, 0, 400, 200))
        except Exception as e:
            print(f"[Warning] Canvas scrollregion update failed: {e}")

    def _refresh_part_list(self):
        """刷新件号列表"""
        parts = get_available_parts()
        # 添加新建选项
        parts.append("➕ 新建件号...")
        self.cbo_part_number['values'] = parts
        
        # 如果当前选中的不在列表里（且不是新建），则选中第一个
        current = self.cbo_part_number.get()
        if current and current not in parts:
            if len(parts) > 1:
                self.cbo_part_number.current(0)
        elif not current and len(parts) > 1:
            self.cbo_part_number.current(0)

    def _on_part_change(self, event):
        selected = self.cbo_part_number.get()
        if selected == "➕ 新建件号...":
            self._create_new_part()
        else:
            self._load_part_config(selected)

    def _create_new_part(self):
        """创建新件号"""
        new_name = simpledialog.askstring("新建件号", "请输入新件号名称：", parent=self)
        if not new_name:
            # 用户取消，恢复之前的选择
            # 这里简单处理：重新加载列表并选中第一个，或者尝试恢复上一个
            self._refresh_part_list()
            if len(self.cbo_part_number['values']) > 1:
                self.cbo_part_number.current(0)
                self._load_part_config(self.cbo_part_number.get())
            return

        # 检查是否已存在
        if new_name in get_available_parts():
            messagebox.showerror("错误", "该件号已存在！")
            return

        # 以当前界面配置为模板保存
        try:
            cfg_dict = self._build_config_from_ui()
            save_config(new_name, cfg_dict)
            
            # 刷新列表并选中
            self._refresh_part_list()
            self.cbo_part_number.set(new_name)
            
            messagebox.showinfo("成功", f"已创建新件号：{new_name}")
            
        except Exception as e:
            messagebox.showerror("错误", f"创建失败：{e}")

    def _load_part_config(self, part_name):
        """加载指定件号的配置"""
        try:
            # 直接读取 JSON 文件
            path = os.path.join(CONFIG_DIR, f"{part_name}.json")
            with open(path, 'r', encoding='utf-8') as f:
                cfg_dict = json.load(f)
            
            # 转换为 UI 格式
            cfg_dict = GUIConfigAdapter.convert_to_ui_format(cfg_dict)
            self._apply_config_dict(cfg_dict)
            
        except Exception as e:
            messagebox.showerror("错误", f"加载配置失败：{e}")

    def _add_setting(self, parent, label, attr_name, default):
        f = ttk.Frame(parent)
        # 左侧“模型设置”每行上下间距：更松一些（减少底部大空白观感）
        f.pack(fill=tk.X, padx=5, pady=6)
        ttk.Label(f, text=label, width=12).pack(side=tk.LEFT)
        ent = ttk.Entry(f)
        ent.insert(0, default)
        ent.pack(side=tk.RIGHT, expand=True, fill=tk.X)
        setattr(self, f"ent_{attr_name}", ent)

    def _init_log_queue(self):
        self.log_queue = queue.Queue()
        self.after(100, self._process_log_queue)

    def _on_optimizer_change(self, event=None):
        """Handle optimizer selection change."""
        opt = self.cbo_optimizer.get()
        if opt == "PyBADS":
            # Disable batch size and set to 1
            self.ent_batch_size.delete(0, tk.END)
            self.ent_batch_size.insert(0, "1")
            self.ent_batch_size.config(state="readonly")
        else:
            # Enable batch size
            self.ent_batch_size.config(state="normal")

    def _on_init_mode_change(self, event=None):
        val = self.cbo_init_mode.get()
        init_mode_arg = INIT_MODE_DISPLAY_TO_ARG.get(val)
        if init_mode_arg == "manual" or "manual" in val:
            self.frm_excel.pack(fill=tk.X, padx=5, pady=2, after=self.cbo_init_mode.master)
        else:
            self.frm_excel.pack_forget()

    def _browse_excel(self):
        path = filedialog.askopenfilename(filetypes=[("表格文件", "*.xlsx *.xls")])
        if path:
            self.var_excel_path.set(path)

    def _process_log_queue(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get_nowait()
            self.txt_log.config(state='normal')
            self.txt_log.insert(tk.END, msg)
            self.txt_log.see(tk.END)
            self.txt_log.config(state='disabled')
        self.after(100, self._process_log_queue)

    def _submit_input(self):
        """用户点击提交按钮或按回车时调用"""
        if self.ent_input.cget('state') == 'disabled':
            return
            
        val = self.ent_input.get()
        is_shrink = 1 if self.var_is_shrink.get() else 0
        
        # 组合字符串：数值，标记
        combined_val = f"{val}，{is_shrink}"
        
        # 清空并禁用输入框
        self.ent_input.delete(0, tk.END)
        self.ent_input.config(state='disabled')
        self.chk_shrink.config(state='disabled') # 禁用复选框
        self.btn_submit.config(state='disabled')
        self.var_input_prompt.set("输入已提交，请等待...")
        
        # 设置值并通知后台线程
        self.input_value = combined_val
        self.input_event.set()

    def _request_input_from_ui(self, prompt, stop_event=None):
        """
        后台线程调用的函数：
        1. 在主线程更新 UI (显示 Prompt, 启用输入框)
        2. 阻塞等待用户提交
        3. 返回用户输入的值
        """
        # 重置事件
        self.input_event.clear()
        self.input_value = None
        
        # 安排在主线程更新 UI
        self.after(0, lambda: self._enable_input_ui(prompt))
        
        # 阻塞等待
        while not self.input_event.is_set():
            if stop_event and stop_event.is_set():
                raise InterruptedError("用户取消寻优")
            self.input_event.wait(timeout=0.2)
            
        return self.input_value

    def _enable_input_ui(self, prompt):
        """主线程执行：启用输入控件"""
        # 如果 prompt 太长，截断或处理一下显示
        clean_prompt = prompt.strip().replace("\n", " ")
        if len(clean_prompt) > 50:
            clean_prompt = clean_prompt[:47] + "..."
            
        self.var_input_prompt.set(clean_prompt)
        self.ent_input.config(state='normal')
        self.chk_shrink.config(state='normal') # 启用复选框
        self.var_is_shrink.set(False) # 重置复选框状态
        self.btn_submit.config(state='normal')
        self.ent_input.focus_set()

    def _apply_config_dict(self, cfg_dict):
        # Reset edit mode to False when loading new config
        self.var_edit_mode.set(False)
        self._toggle_edit_mode()

        # Clear current UI
        for row in list(self.current_config_rows):
            self._remove_param_row(row)
        
        # self.ent_cfg_name.delete(0, tk.END)
        # self.ent_cfg_name.insert(0, cfg_dict.get("name", "加载的配置"))
        
        # fixed params might be empty if we moved everything to tunable
        self.current_fixed_params = cfg_dict.get("fixed", {})
        
        for p_data in cfg_dict.get("tunable", []):
            self._add_param(p_data)

    def _toggle_edit_mode(self):
        is_editing = self.var_edit_mode.get()
        state = "normal" if is_editing else "disabled"
        
        self.btn_add_param.configure(state=state)
        self.btn_link_param.configure(state=state)
        
        for row in self.current_config_rows:
            row.set_editable(is_editing)

    def _add_param(self, data=None):
        if data is None:
            data = {"name": "NewParam", "type": "range", "min": 0, "max": 100, "step": 1}
        
        row = ParamRowFrame(self.scroll_frame, data, on_delete=self._remove_param_row)
        row.pack(fill=tk.X, padx=5, pady=2)
        
        # Apply current edit mode state
        row.set_editable(self.var_edit_mode.get())
        
        self.current_config_rows.append(row)

    def _remove_param_row(self, row_widget):
        row_widget.pack_forget()
        row_widget.destroy()
        if row_widget in self.current_config_rows:
            self.current_config_rows.remove(row_widget)

    def _link_params(self):
        selected = [row for row in self.current_config_rows if row.var_selected.get()]
        if len(selected) < 2:
            messagebox.showwarning("绑定提示", "请至少选择两个参数进行绑定。")
            return
            
        names = [row.var_name.get() for row in selected]
        
        # Ask Link Type
        link_type = messagebox.askquestion("绑定类型", 
                                           "是(Yes) = 同步数值 (范围/集合)\n否(No) = 创建配置模式 (多选/矩阵)")
        
        if link_type == "yes":
            # Sync
            new_name = "_".join(names) + "_同步"
            new_data = {
                "name": new_name,
                "type": "range", # Default to range, user can change
                "targets": names,
                "min": 0, "max": 100, "step": 1
            }
        else:
            # Profile
            new_name = "_".join(names) + "_模式"
            new_data = {
                "name": new_name,
                "type": "choice",
                "targets": names,
                "options": [] # Empty init
            }
            
        # Remove old rows
        for row in selected:
            self._remove_param_row(row)
            
        # Add new row
        self._add_param(new_data)

    def _build_config_from_ui(self):
        """Helper to construct config dict from current UI state"""
        tunable = [row.get_data() for row in self.current_config_rows]
        
        final_fixed = self.current_fixed_params.copy()
        final_tunable = []
        
        # Capture UI order of parameter names (targets)
        ui_order = []
        
        for t in tunable:
            # Collect targets for ordering
            targets = t.get("targets", [t["name"]])
            ui_order.extend(targets)
            
            if t["type"] == "fixed":
                val = t.get("value", 0)
                for tgt in targets:
                    final_fixed[tgt] = val
            else:
                final_tunable.append(t)
        
        return {
            # "name": self.ent_cfg_name.get(), # Removed
            "fixed": final_fixed,
            "tunable": final_tunable,
            "ui_order": ui_order
        }

    def _save_config(self):
        # 直接保存到当前选中的件号文件
        part_name = self.cbo_part_number.get()
        if not part_name or part_name == "➕ 新建件号...":
            messagebox.showwarning("警告", "请先选择一个有效的件号！")
            return
            
        cfg_dict = self._build_config_from_ui()
        
        try:
            save_config(part_name, cfg_dict)
            messagebox.showinfo("成功", f"配置已保存到 {part_name}.json！")
        except Exception as e:
            messagebox.showerror("错误", str(e))

    def _save_session(self):
        """Save current UI state to session file"""
        try:
            algo_settings = {
                "optimizer": self.cbo_optimizer.get(),
                "n_init": self.ent_n_init.get(),
                "n_iter": self.ent_n_iter.get(),
                "batch_size": self.ent_batch_size.get(),
                "mode": self.cbo_mode.get(),
                "init_mode": self.cbo_init_mode.get(),
                "init_excel": self.var_excel_path.get()
            }
            
            # 保存当前选中的件号
            current_part = self.cbo_part_number.get()
            if current_part == "➕ 新建件号...":
                current_part = ""
            
            state = {
                "part_number": current_part,
                "algo_settings": algo_settings,
                # "config_data": cfg_dict # 不再需要保存 config_data，因为直接从文件加载
            }
            
            with open(get_app_path("gui_session.json"), "w", encoding="utf-8") as f:
                json.dump(state, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"保存会话失败：{e}")
            return False

    def _load_session(self):
        """Load UI state from session file"""
        session_path = get_app_path("gui_session.json")
        if not os.path.exists(session_path):
            return False
            
        try:
            with open(session_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            
            # 1. Restore Part Number
            part = state.get("part_number", "")
            parts = get_available_parts()
            
            # 确保 parts 列表已刷新
            self._refresh_part_list()
            
            if part and part in parts:
                self.cbo_part_number.set(part)
                self._load_part_config(part)
            elif parts:
                # 如果上次的件号不存在了，加载第一个
                self.cbo_part_number.set(parts[0])
                self._load_part_config(parts[0])
            
            # 2. Restore Algo Settings
            settings = state.get("algo_settings", {})
            if settings:
                # Restore optimizer (Commented out to keep StandardBO as fixed default)
                # if hasattr(self, "cbo_optimizer"):
                #     opt = settings.get("optimizer", "SAASGP (Default)")
                #     if opt in self.cbo_optimizer["values"]:
                #         self.cbo_optimizer.set(opt)
                #         self._on_optimizer_change()

                self.ent_n_init.delete(0, tk.END); self.ent_n_init.insert(0, settings.get("n_init", "20"))

                self.ent_n_iter.delete(0, tk.END); self.ent_n_iter.insert(0, settings.get("n_iter", "10"))
                self.ent_batch_size.delete(0, tk.END); self.ent_batch_size.insert(0, settings.get("batch_size", "4"))
                
                mode_val = settings.get("mode", "正式")
                if mode_val in self.cbo_mode["values"]:
                    self.cbo_mode.set(mode_val)

                init_mode = settings.get("init_mode", "自动")
                if init_mode in self.cbo_init_mode["values"]:
                    self.cbo_init_mode.set(init_mode)
                    self._on_init_mode_change(None) # Refresh UI visibility
                
                self.var_excel_path.set(settings.get("init_excel", ""))
                
            return True
        except Exception as e:
            print(f"加载会话失败：{e}")
            return False

    def _save_and_exit(self):
        if self._save_session():
            self.destroy()
        else:
            if messagebox.askokcancel("保存失败", "保存会话失败，仍要退出吗？"):
                self.destroy()

    def _reset_and_run(self):
        """清除 Checkpoint 并重新开始"""
        if messagebox.askyesno("确认重新开始", "确定要清除历史进度并重新开始吗？\n这将删除已有的存档、实验记录和所有导出的建议文件。"):
            # 0. 停止当前运行的任务
            if self.current_stop_event:
                self.current_stop_event.set()
                # 简单等待一下，确保文件释放
                self.txt_log.config(state='normal')
                self.txt_log.insert(tk.END, "\n【界面】正在停止当前任务并清理环境……\n")
                self.txt_log.config(state='disabled')
                # 稍微延时确保线程退出和文件句柄释放
                self.after(500)

            # 1. 收集需要删除的文件
            files_to_delete = [
                os.path.join(DEFAULT_OUT_DIR, "bo_checkpoint.pt"),
                os.path.join(DEFAULT_OUT_DIR, "experiment_records.xlsx"),
                os.path.join(DEFAULT_OUT_DIR, "bo_run.log"),
                os.path.join(DEFAULT_OUT_DIR, "bo_samples.csv")
            ]
            
            # 匹配所有导出的建议表格文件
            import glob
            files_to_delete.extend(glob.glob(os.path.join(DEFAULT_OUT_DIR, "*建议参数.xlsx")))
            files_to_delete.extend(glob.glob(os.path.join(DEFAULT_OUT_DIR, "初始试模清单.xlsx")))
            
            deleted_count = 0
            for f_path in files_to_delete:
                if os.path.exists(f_path):
                    try:
                        os.remove(f_path)
                        deleted_count += 1
                    except Exception as e:
                        print(f"删除失败：{f_path}：{e}")

            self.txt_log.config(state='normal')
            self.txt_log.insert(tk.END, f"【界面】环境清理完成，已删除 {deleted_count} 个历史文件。\n")
            self.txt_log.config(state='disabled')
            
            # 2. 自动运行
            self._run_optimization()

    def _open_history_manager(self):
        """打开历史记录管理弹窗（修正/回退后重启算法线程）"""
        HistoryManagerDialog(self, excel_path=os.path.join(DEFAULT_OUT_DIR, "experiment_records.xlsx"))

    def _stop_current_run_and_wait(self, timeout_ms: int = 5000, poll_ms: int = 150, on_stopped=None, on_timeout=None):
        """
        请求停止当前优化线程，并在主线程轮询等待线程退出后回调。
        - timeout_ms: 最大等待时间（毫秒）
        - on_stopped: 线程退出后调用
        - on_timeout: 超时仍未退出时调用
        """
        if self.current_stop_event and not self.current_stop_event.is_set():
            self.current_stop_event.set()

        t0 = self._now_ms()

        def poll():
            th = self.current_thread
            alive = bool(th and th.is_alive())
            if not alive:
                if callable(on_stopped):
                    on_stopped()
                return
            if self._now_ms() - t0 >= timeout_ms:
                if callable(on_timeout):
                    on_timeout()
                return
            self.after(poll_ms, poll)

        self.after(poll_ms, poll)

    def _now_ms(self) -> int:
        # 使用 time 模块但避免全局 import 改动太大：局部导入即可
        import time
        return int(time.time() * 1000)

    def _run_optimization(self):
        # Stop previous run if exists (safety check)
        if self.current_stop_event and not self.current_stop_event.is_set():
            self.current_stop_event.set()
        
        # Create new event
        self.current_stop_event = threading.Event()
        stop_event = self.current_stop_event

        cfg_dict = self._build_config_from_ui()
        
        # 注入件号名称
        part_name = self.cbo_part_number.get()
        if part_name and "新建件号" not in part_name:
             cfg_dict["name"] = part_name
        
        # Save temp config
        tmp_cfg_path = get_app_path("temp_gui_config.json")
        with open(tmp_cfg_path, 'w', encoding='utf-8') as f:
            json.dump(cfg_dict, f, ensure_ascii=False)
            
        # Get settings
        try:
            n_init = int(self.ent_n_init.get())
            n_iter = int(self.ent_n_iter.get())
            batch = int(self.ent_batch_size.get())
            shrink = 30.0 # Default constant
            mode_str = self.cbo_mode.get()
            mode_arg = MODE_DISPLAY_TO_ARG.get(mode_str, "manual")
            
            init_mode_str = self.cbo_init_mode.get()
            init_mode_arg = INIT_MODE_DISPLAY_TO_ARG.get(init_mode_str, "auto")
            init_excel_path = self.var_excel_path.get()
            
            # 获取优化器参数
            optimizer_arg = "StandardBO"
            
            if init_mode_arg == "manual" and not os.path.exists(init_excel_path):
                messagebox.showerror("错误", "请选择有效的Excel文件！")
                return

        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字设置。")
            return

        self.btn_run.config(state="disabled")
        
        def runner():
            # Redirect stdout
            old_stdout = sys.stdout
            sys.stdout = RedirectText(self.txt_log, self.log_queue)
            
            # 保存原始的 input 函数
            old_input = builtins.input
            
            # 定义新的 input 函数，重定向到 UI
            def gui_input(prompt=""):
                # 将 prompt 也输出到日志，方便查看上下文
                print(prompt, end='') 
                return self._request_input_from_ui(prompt, stop_event=stop_event)
            
            # 替换内置 input
            builtins.input = gui_input
            
            try:
                # Hacky way: sys.argv override
                sys.argv = [
                    "main.py",
                    "--part", tmp_cfg_path, 
                    "--n-init", str(n_init),
                    "--n-iter", str(n_iter),
                    "--batch-size", str(batch),
                    "--shrink-th", str(shrink),
                    "--mode", mode_arg,
                    "--init-mode", init_mode_arg,
                    "--optimizer", optimizer_arg
                ]
                
                if init_mode_arg == "manual" and init_excel_path:
                    sys.argv.extend(["--init-excel", init_excel_path])
                
                print(">>> 开始工艺寻优流程...")
                run_algo(stop_event=stop_event)
                print(">>> 寻优完成。")
                
            except Exception as e:
                print(f"执行出错: {e}")
                import traceback
                traceback.print_exc()
            finally:
                # 还原 stdout 和 input
                sys.stdout = old_stdout
                builtins.input = old_input  # <--- 务必还原
                
                # Use after to reset button on main thread
                def reset_ui():
                    self.btn_run.config(state="normal")
                    self.var_input_prompt.set("等待程序请求输入...")
                    self.ent_input.config(state='disabled')
                    self.chk_shrink.config(state='disabled')
                    self.btn_submit.config(state='disabled')
                    self.current_thread = None

                self.after(0, reset_ui)
        
        th = threading.Thread(target=runner, daemon=True)
        self.current_thread = th
        th.start()


class HistoryManagerDialog(tk.Toplevel):
    """
    历史记录管理（后悔药）
    - 查看/编辑 `experiment_records.xlsx` 内容（修正模式）
    - 删除末尾 N 条记录（回退模式）
    保存后会请求停止当前优化线程，并重启使其重新加载修正后的记录。
    """
    REQUIRED_COLS = [RECORD_COL_STAGE, RECORD_COL_FORM_ERROR, RECORD_COL_IS_SHRINK]

    def __init__(self, parent: App, excel_path: str):
        super().__init__(parent)
        self.parent = parent
        self.excel_path = excel_path

        self.title("历史记录管理（修正 / 回退）")
        self.geometry("1100x600")
        self.transient(parent)
        self.grab_set()

        self.df = pd.DataFrame()
        self._earliest_modified_rank = None  # 仅当修改的是“已完成（面型评价指标不为空）”记录时才触发自动回退
        self.dirty = False
        self._active_cell = None  # (row_id: str, col_index: int) 作为粘贴起点（类似 Excel 的光标单元格）

        self._build_ui()
        self._reload_from_disk()

    def _build_ui(self):
        frm_top = ttk.Frame(self)
        frm_top.pack(fill=tk.X, padx=10, pady=8)

        ttk.Label(frm_top, text="记录文件：").pack(side=tk.LEFT)
        self.var_path = tk.StringVar(value=self.excel_path)
        ent = ttk.Entry(frm_top, textvariable=self.var_path, state="readonly")
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)

        ttk.Button(frm_top, text="打开目录", command=self._open_dir).pack(side=tk.LEFT, padx=4)
        ttk.Button(frm_top, text="重新加载", command=self._reload_from_disk).pack(side=tk.LEFT, padx=4)

        frm_mid = ttk.Frame(self)
        frm_mid.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        self.tree = ttk.Treeview(frm_mid, show="headings")
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ysb = ttk.Scrollbar(frm_mid, orient="vertical", command=self.tree.yview)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        xsb = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        xsb.pack(fill=tk.X, padx=10)

        self.tree.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)

        self.tree.bind("<Double-1>", self._on_double_click_edit)
        # 记录用户点击的“起始单元格”，用于 Ctrl+V 粘贴大块表格（Excel/TSV）
        self.tree.bind("<Button-1>", self._on_left_click, add="+")
        self.tree.bind("<Button-3>", self._on_right_click)
        # 支持从 Excel 直接粘贴（Tab/换行分隔）
        self.tree.bind("<Control-v>", self._on_paste)
        self.tree.bind("<Control-V>", self._on_paste)
        # 当焦点不在 Treeview 上时，也尽量能粘贴（例如点了空白区域/按钮后）
        self.bind("<Control-v>", self._on_paste)
        self.bind("<Control-V>", self._on_paste)

        ttk.Separator(self, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=4)

        frm_actions = ttk.Frame(self)
        frm_actions.pack(fill=tk.X, padx=10, pady=8)

        self.var_status = tk.StringVar(value="就绪")
        ttk.Label(frm_actions, textvariable=self.var_status, foreground="blue").pack(side=tk.LEFT)

        ttk.Button(frm_actions, text="取消", command=self.destroy).pack(side=tk.RIGHT, padx=6)
        ttk.Button(frm_actions, text="保存并重启", command=self._save_and_restart).pack(side=tk.RIGHT, padx=6)

        tip = (
            "提示：双击单元格可编辑；右键任意行可插入/删除行（像操作 Excel）。\n"
            f"{RECORD_COL_FORM_ERROR} 留白表示该行尚未完成评估（可用于“先填推荐参数、后补测量结果”）。\n"
            f"只有当你修改了已完成（{RECORD_COL_FORM_ERROR} 非空）的记录时，保存才会按“最早被修改批次”自动回退截断后续批次。\n"
            "保存前会先停止当前优化线程，再写回表格文件，并自动重启使其重新加载历史。"
        )
        ttk.Label(self, text=tip, foreground="#555").pack(fill=tk.X, padx=10, pady=(0, 8))

        # 右键菜单
        self._menu = tk.Menu(self, tearoff=0)
        self._menu.add_command(label="在上方插入 N 行...", command=lambda: self._insert_rows(where="above"))
        self._menu.add_command(label="在下方插入 N 行...", command=lambda: self._insert_rows(where="below"))
        self._menu.add_separator()
        self._menu.add_command(label="删除该行", command=self._delete_selected_row)

    def _on_left_click(self, event):
        """记录用户点击的单元格位置，作为后续 Ctrl+V 的粘贴起点。"""
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        row_id = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)  # '#1'...
        if not row_id or not col_id:
            return
        try:
            col_index = int(col_id.replace("#", "")) - 1
        except Exception:
            return
        if col_index < 0:
            return
        self._active_cell = (row_id, col_index)

    def _on_paste(self, event=None):
        """
        支持从 Excel 复制的矩形区域直接粘贴到表格（TSV：Tab 分列，换行分行）。
        - 从“最近一次点击”的单元格作为起点
        - 行不够时自动追加空行
        - 超出列数的内容会被忽略
        """
        try:
            raw = self.clipboard_get()
        except Exception:
            return "break"

        if not raw:
            return "break"

        # Excel 常见：末尾带一行空行；这里做温和清洗
        lines = [ln for ln in raw.splitlines() if ln is not None]
        # 去掉尾部的空行
        while lines and str(lines[-1]).strip() == "":
            lines.pop()
        if not lines:
            return "break"

        data = [str(ln).split("\t") for ln in lines]

        # 1) 确定粘贴起点（行、列）
        row_id = None
        col_start = 0
        if self._active_cell:
            row_id, col_start = self._active_cell
        if not row_id:
            # 退化：用当前选中行作为起点，列从 0 开始
            sel = self.tree.selection()
            row_id = sel[0] if sel else None
            col_start = 0

        # 2) 保障 DataFrame 至少有列/行（支持在空表里直接粘贴）
        if len(self.df.columns) == 0:
            self.df = pd.DataFrame(columns=self.REQUIRED_COLS)
        if len(self.df) == 0 and row_id is None:
            # 空表且没有选中：先创建 1 行，让用户能直接 Ctrl+V 粘贴
            self.df = pd.concat([self.df, pd.DataFrame([self._blank_row_dict("init")])], ignore_index=True)
            self._render_df()
            row_id = "0"
            col_start = 0

        try:
            row_start = int(row_id) if row_id is not None else 0
        except Exception:
            row_start = 0

        if row_start < 0:
            row_start = 0
        if col_start < 0:
            col_start = 0

        columns = list(self.df.columns)
        if not columns:
            return "break"

        # 3) 若需要，自动扩展行数
        target_last_row = row_start + len(data) - 1
        if target_last_row >= len(self.df):
            # 生成追加行的默认阶段（优先取起点行阶段，否则取最后一行阶段）
            stage_default = "init"
            try:
                if RECORD_COL_STAGE in self.df.columns:
                    if 0 <= row_start < len(self.df):
                        stage_default = str(self.df.at[row_start, RECORD_COL_STAGE]).strip() or "init"
                    elif len(self.df) > 0:
                        stage_default = str(self.df.at[len(self.df) - 1, RECORD_COL_STAGE]).strip() or "init"
            except Exception:
                stage_default = "init"

            need = target_last_row - len(self.df) + 1
            rows = [self._blank_row_dict(stage_default) for _ in range(need)]
            self.df = pd.concat([self.df, pd.DataFrame(rows)], ignore_index=True)
            # Treeview 的 iid 依赖 index，扩行后统一重绘更稳妥
            self._render_df()

        # 4) 批量写入单元格
        max_cols = len(columns)
        changed_any = False
        for r_off, row_vals in enumerate(data):
            ridx = row_start + r_off
            if ridx < 0 or ridx >= len(self.df):
                continue

            # 如果这是“已完成记录”，修改前先标记用于自动回退（避免用户把评价指标清空导致不触发）
            try:
                was_completed = self._is_completed_row(ridx)
            except Exception:
                was_completed = False
            if was_completed:
                self._mark_stage_modified_if_completed(ridx)

            for c_off, cell in enumerate(row_vals):
                cidx = col_start + c_off
                if cidx < 0 or cidx >= max_cols:
                    continue
                col_name = columns[cidx]
                new_val = "" if cell is None else str(cell)
                self.df.at[ridx, col_name] = new_val
                # 同步 UI（iid = index 的字符串）
                try:
                    self.tree.set(str(ridx), col_name, new_val)
                except Exception:
                    pass
                changed_any = True

        if changed_any:
            self.dirty = True
            self.var_status.set(f"已粘贴 {len(data)} 行（未保存）。")

        # 将焦点/选择移动到粘贴起点行，方便继续操作
        try:
            self.tree.selection_set(str(row_start))
            self.tree.focus(str(row_start))
        except Exception:
            pass

        return "break"

    def _open_dir(self):
        try:
            d = os.path.dirname(self.excel_path)
            if d and os.path.exists(d):
                os.startfile(d)
        except Exception as e:
            messagebox.showerror("错误", f"无法打开目录：{e}", parent=self)

    @staticmethod
    def _normalize_record_columns_for_display(df: pd.DataFrame) -> pd.DataFrame:
        """
        将历史记录表的关键列名统一为中文显示：
        - 阶段
        - 面型评价指标
        - 是否缩水
        """
        if df is None or len(getattr(df, "columns", [])) == 0:
            return df
        rename_map = {}
        if "stage" in df.columns:
            rename_map["stage"] = RECORD_COL_STAGE
        if "form_error" in df.columns:
            rename_map["form_error"] = RECORD_COL_FORM_ERROR
        if "is_shrink" in df.columns:
            rename_map["is_shrink"] = RECORD_COL_IS_SHRINK
        # 兼容某些旧表可能用 shrink
        if "shrink" in df.columns and RECORD_COL_IS_SHRINK not in df.columns:
            rename_map["shrink"] = RECORD_COL_IS_SHRINK
        if rename_map:
            df = df.rename(columns=rename_map)
        return df

    def _reload_from_disk(self):
        if not os.path.exists(self.excel_path):
            self.df = pd.DataFrame(columns=self.REQUIRED_COLS)
            self._render_df()
            self.dirty = False
            self._earliest_modified_rank = None
            self.var_status.set("未找到历史文件：当前显示为空表（保存后会创建）。")
            return

        try:
            df = pd.read_excel(self.excel_path)
        except Exception as e:
            messagebox.showerror("错误", f"读取表格失败：{e}", parent=self)
            return

        self.df = self._normalize_record_columns_for_display(df)
        self._render_df()
        self.dirty = False
        self._earliest_modified_rank = None
        self.var_status.set(f"已加载 {len(self.df)} 条记录。")

    def _render_df(self):
        # Clear tree
        children = self.tree.get_children()
        if children:
            self.tree.delete(*children)

        cols = list(self.df.columns)
        self.tree["columns"] = cols

        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=max(80, min(220, len(str(c)) * 14)), anchor="center")

        # Insert rows
        for i in range(len(self.df)):
            row = self.df.iloc[i].tolist()
            # Treeview 里统一转字符串显示，避免 NaN 显示为 'nan'
            display = ["" if (pd.isna(v)) else str(v) for v in row]
            self.tree.insert("", "end", iid=str(i), values=display)

    def _on_double_click_edit(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return

        row_id = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)  # '#1' ...
        if not row_id or not col_id:
            return

        col_index = int(col_id.replace("#", "")) - 1
        columns = list(self.df.columns)
        if col_index < 0 or col_index >= len(columns):
            return
        col_name = columns[col_index]

        x, y, w, h = self.tree.bbox(row_id, col_id)
        old_val = self.tree.set(row_id, col_name)

        editor = ttk.Entry(self.tree)
        editor.insert(0, old_val)
        editor.place(x=x, y=y, width=w, height=h)
        editor.focus_set()
        editor.select_range(0, tk.END)

        def commit():
            new_val = editor.get()
            editor.destroy()
            self.tree.set(row_id, col_name, new_val)
            try:
                idx = int(row_id)
                was_completed = self._is_completed_row(idx)
                self.df.at[idx, col_name] = new_val
                self.dirty = True
                if was_completed:
                    # 修改前已完成：即使用户清空评价指标，也应触发自动回退判定
                    self._mark_stage_modified_if_completed(idx)
                self.var_status.set("已修改（未保存）。")
            except Exception:
                pass

        editor.bind("<Return>", lambda e: commit())
        editor.bind("<FocusOut>", lambda e: commit())

    def _on_right_click(self, event):
        row_id = self.tree.identify_row(event.y)
        if row_id:
            self.tree.selection_set(row_id)
            self.tree.focus(row_id)
        try:
            self._menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._menu.grab_release()

    def _ask_n(self, default_n: int = 1) -> int:
        n = simpledialog.askinteger("插入行数", "请输入要插入的行数 N：", parent=self, initialvalue=default_n, minvalue=1, maxvalue=500)
        return int(n) if n else 0

    def _selected_index(self) -> int:
        sel = self.tree.selection()
        if not sel:
            return -1
        try:
            return int(sel[0])
        except Exception:
            return -1

    def _blank_row_dict(self, stage_default: str) -> dict:
        row = {c: "" for c in self.df.columns}
        if RECORD_COL_STAGE in row:
            row[RECORD_COL_STAGE] = stage_default
        if RECORD_COL_FORM_ERROR in row:
            row[RECORD_COL_FORM_ERROR] = ""
        if RECORD_COL_IS_SHRINK in row:
            row[RECORD_COL_IS_SHRINK] = ""
        return row

    def _insert_rows(self, where: str):
        n = self._ask_n(default_n=1)
        if n <= 0:
            return

        if len(self.df) == 0:
            # 空表：直接追加 N 行
            if len(self.df.columns) == 0:
                self.df = pd.DataFrame(columns=self.REQUIRED_COLS)
            stage_default = "init"
            rows = [self._blank_row_dict(stage_default) for _ in range(n)]
            self.df = pd.concat([self.df, pd.DataFrame(rows)], ignore_index=True)
            self._render_df()
            self.dirty = True
            self.var_status.set(f"已插入 {n} 行（未保存）。")
            return

        idx = self._selected_index()
        if idx < 0 or idx >= len(self.df):
            messagebox.showinfo("提示", "请先右键选中一行再插入。", parent=self)
            return

        stage_default = "init"
        try:
            if RECORD_COL_STAGE in self.df.columns:
                stage_default = str(self.df.at[idx, RECORD_COL_STAGE])
                if not stage_default:
                    stage_default = "init"
        except Exception:
            stage_default = "init"

        insert_at = idx if where == "above" else (idx + 1)
        rows = [self._blank_row_dict(stage_default) for _ in range(n)]
        df_new = pd.DataFrame(rows)
        self.df = pd.concat([self.df.iloc[:insert_at], df_new, self.df.iloc[insert_at:]], ignore_index=True)
        self._render_df()
        self.dirty = True
        self.var_status.set(f"已在{'上方' if where=='above' else '下方'}插入 {n} 行（未保存）。")

    def _delete_selected_row(self):
        if len(self.df) == 0:
            return
        idx = self._selected_index()
        if idx < 0 or idx >= len(self.df):
            messagebox.showinfo("提示", "请先右键选中一行再删除。", parent=self)
            return

        if not messagebox.askyesno("确认删除", f"确定删除第 {idx+1} 行吗？（删除后保存才会生效）", parent=self):
            return

        # 删除“已完成”记录属于对历史的修改，需要参与自动回退判定
        self._mark_stage_modified_if_completed(idx)

        self.df = self.df.drop(index=idx).reset_index(drop=True)
        self._render_df()
        self.dirty = True
        self.var_status.set("已删除 1 行（未保存）。")

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

    def _is_completed_row(self, idx: int) -> bool:
        if RECORD_COL_FORM_ERROR not in self.df.columns:
            return False
        try:
            v = self.df.at[idx, RECORD_COL_FORM_ERROR]
        except Exception:
            return False
        if v is None:
            return False
        if isinstance(v, float) and pd.isna(v):
            return False
        s = str(v).strip()
        return s != ""

    def _mark_stage_modified_if_completed(self, idx: int):
        """
        只有当该行评价指标非空（即“已完成评估”）时，才记录用于自动回退的最早阶段。
        """
        if idx < 0 or idx >= len(self.df):
            return
        if not self._is_completed_row(idx):
            return
        if RECORD_COL_STAGE not in self.df.columns:
            return
        try:
            r = self._stage_rank(self.df.at[idx, RECORD_COL_STAGE])
        except Exception:
            return
        if self._earliest_modified_rank is None:
            self._earliest_modified_rank = r
        else:
            self._earliest_modified_rank = min(self._earliest_modified_rank, r)

    def _apply_auto_rollback_by_earliest_modified_stage(self):
        """
        根据最早被编辑的批次自动回退（截断更晚批次的记录）。
        规则：
        - 若修改发生在 iter_k，则删除 iter_(k+1) 及之后的记录
        - 若修改发生在 init，则删除所有 iter_* 记录（保留 init）
        """
        if self._earliest_modified_rank is None:
            return  # 没有对“已完成记录”的修改，不做自动回退
        if RECORD_COL_STAGE not in self.df.columns:
            return
        if len(self.df) == 0:
            return

        rollback_rank = self._earliest_modified_rank
        before_len = len(self.df)
        self.df["_stage_rank__tmp"] = self.df[RECORD_COL_STAGE].apply(self._stage_rank)
        self.df = self.df[self.df["_stage_rank__tmp"] <= rollback_rank].drop(columns=["_stage_rank__tmp"]).reset_index(drop=True)
        after_len = len(self.df)

        # 避免二次保存重复回退
        self._earliest_modified_rank = None

        trimmed = before_len - after_len
        if trimmed > 0:
            self.var_status.set(f"自动回退：已截断 {trimmed} 条更晚批次记录（未保存）。")

    def _validate_before_save(self) -> bool:
        missing = [c for c in self.REQUIRED_COLS if c not in self.df.columns]
        if missing:
            messagebox.showerror("错误", f"记录表缺少必要列：{missing}\n请勿删除列名。", parent=self)
            return False

        # 校验：面型评价指标允许留白；非空则必须可转 float
        bad_rows = []
        for i, v in enumerate(self.df[RECORD_COL_FORM_ERROR].tolist()):
            if v is None or (isinstance(v, float) and pd.isna(v)):
                continue
            s = str(v).strip()
            if s == "":
                continue
            try:
                float(s)
            except Exception:
                bad_rows.append(i + 1)
        if bad_rows:
            sample = bad_rows[:10]
            messagebox.showerror("错误", f"以下行的{RECORD_COL_FORM_ERROR}格式无效（行号从 1 开始）：{sample} ...", parent=self)
            return False

        return True

    def _save_to_disk(self) -> bool:
        # 先执行“最早修改批次”的自动回退逻辑
        self._apply_auto_rollback_by_earliest_modified_stage()
        # 回退可能改变表格内容，刷新一下视图（避免用户疑惑）
        self._render_df()

        if not self._validate_before_save():
            return False

        # 将关键列做基本类型清洗（尽量温和，不破坏其他列）
        try:
            self.df[RECORD_COL_STAGE] = self.df[RECORD_COL_STAGE].astype(str)
            # 留白 -> NaN；数字字符串 -> float
            self.df[RECORD_COL_FORM_ERROR] = pd.to_numeric(self.df[RECORD_COL_FORM_ERROR], errors="coerce")

            def parse_is_shrink(x):
                s = str(x).strip().lower()
                if s in ["1", "true", "yes", "y", "是", "有", "缩水", "严重缩水"]:
                    return True
                if s in ["0", "false", "no", "n", "", "否", "无", "不缩水"]:
                    return False
                # 兼容 Excel 里可能是 1.0/0.0
                try:
                    return bool(int(float(s)))
                except Exception:
                    return False

            self.df[RECORD_COL_IS_SHRINK] = self.df[RECORD_COL_IS_SHRINK].apply(parse_is_shrink)
        except Exception as e:
            messagebox.showerror("错误", f"保存前数据清洗失败：{e}", parent=self)
            return False

        # 确保输出目录存在
        out_dir = os.path.dirname(self.excel_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        try:
            self.df.to_excel(self.excel_path, index=False)
            self.dirty = False
            self.var_status.set("保存成功。")
            return True
        except Exception as e:
            messagebox.showerror("错误", f"写入表格失败：{e}\n请确认文件未被占用。", parent=self)
            return False

    def _save_and_restart(self):
        if not self.dirty:
            if not messagebox.askyesno("确认", "当前没有未保存修改，仍要重启优化线程吗？", parent=self):
                return

        def do_save_and_restart():
            if not self._save_to_disk():
                return
            # 保存成功后，重启优化线程（会重新 load_existing_records）
            self.parent._run_optimization()
            self.var_status.set("已请求重启优化线程。")
            self.after(300, self.destroy)

        def on_timeout():
            messagebox.showerror("错误", "停止优化线程超时。\n请稍等线程结束后再保存/重启。", parent=self)

        # 先停线程再保存，避免 runner 正在写同一个 Excel
        self.var_status.set("正在停止优化线程...")
        self.parent._stop_current_run_and_wait(
            timeout_ms=5000,
            poll_ms=200,
            on_stopped=do_save_and_restart,
            on_timeout=on_timeout
        )

if __name__ == "__main__":
    app = App()
    app.mainloop()
