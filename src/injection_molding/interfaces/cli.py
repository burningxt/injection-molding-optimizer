"""命令行接口

基于贝叶斯优化的注塑成型工艺参数推荐 CLI。
"""

import argparse
import json
import sys
from pathlib import Path

from ..domain.config import InjectionMoldingConfig
from ..core.runner import ExperimentRunner
from ..core.bayesian.standard import BayesianOptimizer


def main():
    """CLI 主函数"""
    parser = argparse.ArgumentParser(
        description="注塑成型工艺参数智能推荐系统 - 贝叶斯优化"
    )
    parser.add_argument(
        "--config", "-c",
        required=True,
        help="件号配置文件路径 (JSON)"
    )
    parser.add_argument(
        "--output", "-o",
        default="output",
        help="输出目录 (默认: output)"
    )
    parser.add_argument(
        "--n-init",
        type=int,
        default=10,
        help="初始数据数量 (默认: 10)"
    )
    parser.add_argument(
        "--n-iter",
        type=int,
        default=20,
        help="优化迭代次数 (默认: 20)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=4,
        help="每批建议数量 (默认: 4)"
    )
    parser.add_argument(
        "--simulate", "-s",
        action="store_true",
        help="使用仿真模式（自动计算）"
    )
    parser.add_argument(
        "--shrink-threshold",
        type=float,
        default=30.0,
        help="缩水临界值 (默认: 30)"
    )

    args = parser.parse_args()

    # 加载配置
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"错误: 配置文件不存在: {config_path}")
        return 1

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
        config = InjectionMoldingConfig.from_dict(config_data)
    except Exception as e:
        print(f"错误: 加载配置失败: {e}")
        return 1

    print(f"件号: {config.name}")
    print(f"可调参数: {len(config.tunable_specs)}")
    print(f"初始数据: {args.n_init}")
    print(f"迭代次数: {args.n_iter}")
    print(f"批次大小: {args.batch_size}")
    print(f"模式: {'仿真' if args.simulate else '手动输入'}")
    print()

    # 创建输出目录
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 创建运行器
    runner = ExperimentRunner(
        config=config,
        use_simulation=args.simulate,
        shrink_threshold=args.shrink_threshold,
        out_dir=str(output_dir)
    )

    # 创建优化器并运行
    optimizer = BayesianOptimizer(runner)
    try:
        optimizer.run(
            n_init=args.n_init,
            n_iter=args.n_iter,
            batch_size=args.batch_size
        )
    except KeyboardInterrupt:
        print("\n用户中断")
        return 0
    except Exception as e:
        print(f"\n错误: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
