"""
主程序入口 - 负责参数解析、初始化和调用贝叶斯优化
Refactored to use ExperimentRunner and Optimizer Strategy Pattern
"""

import argparse
import os
import sys

from config import (
    DEFAULT_SHRINK_THRESHOLD,
    DEFAULT_N_INIT,
    DEFAULT_N_ITER,
    DEFAULT_BATCH_SIZE,
    DEFAULT_OUT_DIR,
    DEFAULT_CSV_NAME,
    get_config
)
from utils import log, setup_logger
from runner import ExperimentRunner, RECORD_COL_FORM_ERROR
from optimizer_standard import StandardBOOptimizer

def main(stop_event=None):
    # 只有当作为脚本运行时才解析参数，被调用时可以跳过或由调用者设置 sys.argv
    parser = argparse.ArgumentParser(description="注塑成型贝叶斯优化（通用）")
    # 默认使用正式模式（manual）：由用户在机台试模后手动输入面型评价指标
    parser.add_argument("--mode", choices=["auto", "manual"], default="manual",
                        help="auto：仿真模式；manual：真实试模手动输入面型评价指标")
    
    # 新增 part 参数
    parser.add_argument("--part", type=str, default="PartA",
                        help="选择件号配置：PartA、PartB，或配置文件路径")
    
    parser.add_argument("--optimizer", choices=["StandardBO"], default="StandardBO",
                        help="选择优化器：StandardBO（默认）")
                        
    parser.add_argument("--init-mode", choices=["auto", "manual"], default="auto",
                        help="初始采样点来源：auto=随机；manual=表格导入")
    parser.add_argument("--init-excel", type=str, default=None,
                        help="当 init-mode=manual 时，指定表格文件路径")
    parser.add_argument("--shrink-th", type=float, default=DEFAULT_SHRINK_THRESHOLD,
                        help="判定严重缩水/高不良的面型评价指标阈值")
    parser.add_argument("--n-init", type=int, default=DEFAULT_N_INIT,
                        help="初始化随机采样数量")
    parser.add_argument("--n-iter", type=int, default=DEFAULT_N_ITER,
                        help="BO 迭代轮数")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help="每轮推荐的参数组数")
    parser.add_argument("--out-dir", type=str, default=DEFAULT_OUT_DIR,
                        help="所有结果文件输出目录")
    parser.add_argument("--csv-name", type=str, default=DEFAULT_CSV_NAME,
                        help="采样结果输出文件名")

    args = parser.parse_args()

    # 创建输出目录
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    # 初始化 logger
    log_path = os.path.join(out_dir, "bo_run.log")
    setup_logger(log_path)

    # 获取配置对象
    try:
        config = get_config(args.part)
    except Exception as e:
        log(f"【错误】加载配置失败：{e}")
        return

    use_sim = (args.mode == "auto")
    shrink_threshold = args.shrink_th
    
    log("运行设置：")
    log(f"  件号配置：{config.name}")
    log(f"  严重缩水阈值：{shrink_threshold}")
    log(f"  初始采样数：{args.n_init}")
    log(f"  迭代轮数：{args.n_iter}")
    log(f"  批次大小：{args.batch_size}")
    log(f"  输出目录：{out_dir}")
    log(f"  日志文件：{log_path}")
    
    # 1. Initialize Runner
    runner = ExperimentRunner(
        config=config,
        use_simulation=use_sim,
        shrink_threshold=shrink_threshold,
        out_dir=out_dir
    )
    
    # 2. Initialize Optimizer
    optimizer = StandardBOOptimizer(runner)
        
    # 3. Run Optimization
    best_phys, best_fe = optimizer.run(
        n_init=args.n_init,
        n_iter=args.n_iter,
        batch_size=args.batch_size,
        init_mode=args.init_mode,
        init_excel_path=args.init_excel,
        stop_event=stop_event
    )

    if best_phys is None:
        log("寻优已停止。")
        return

    log("\n=== 最终结果 ===")
    log(f"最佳{RECORD_COL_FORM_ERROR}：{best_fe:.6f}")
    
    # 打印最优参数
    if hasattr(best_phys, "tolist"):
        best_phys_list = best_phys.tolist()
    else:
        best_phys_list = list(best_phys)

    opt_params = {}
    for i, m in enumerate(runner.meta):
        opt_params[m["name"]] = best_phys_list[i]
    
    # Snap to grid to ensure discrete values are respected
    opt_params = config.snap_to_grid(opt_params)
        
    machine_params = config.translate_to_machine(opt_params)
    
    log("对应机台参数：")
    keys = config.get_ordered_machine_param_keys()
    for k in keys:
        if k in machine_params:
            disp = config.get_param_display_name(k)
            log(f"  {disp}：{machine_params[k]}")

if __name__ == "__main__":
    main()
