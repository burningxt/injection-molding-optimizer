#!/usr/bin/env python3
"""
测试运行脚本 - 自动化测试注塑成型优化系统

使用方法:
    python run_tests.py [test_name]

示例:
    python run_tests.py              # 运行所有测试
    python run_tests.py session      # 运行会话管理测试
    python run_tests.py optimization # 运行优化流程测试
    python run_tests.py data         # 运行数据提交测试
    python run_tests.py safety       # 运行安全边界测试
    python run_tests.py rollback     # 运行回退机制测试
    python run_tests.py save_exit    # 运行保存退出测试
    python run_tests.py exception    # 运行异常处理测试
    python run_tests.py integration  # 运行集成测试
"""
import asyncio
import sys
import argparse
from datetime import datetime

# 添加项目路径
sys.path.insert(0, '/home/xt/Code/InjectionMolding')

# 导入各测试模块
from test_01_session import run_all_tests as run_session_tests
from test_02_optimization import run_all_tests as run_optimization_tests
from test_03_data_submit import run_all_tests as run_data_tests
from test_safety_boundary import run_all_tests as run_safety_tests
from test_05_rollback import run_all_tests as run_rollback_tests
from test_save_exit import run_all_tests as run_save_exit_tests
from test_07_exceptions import run_all_tests as run_exception_tests
from test_08_integration import run_all_tests as run_integration_tests


# 测试套件映射
TEST_SUITES = {
    'session': run_session_tests,
    '01': run_session_tests,
    'optimization': run_optimization_tests,
    '02': run_optimization_tests,
    'opt': run_optimization_tests,
    'data': run_data_tests,
    '03': run_data_tests,
    'submit': run_data_tests,
    'safety': run_safety_tests,
    '04': run_safety_tests,
    'boundary': run_safety_tests,
    'rollback': run_rollback_tests,
    '05': run_rollback_tests,
    'save_exit': run_save_exit_tests,
    'saveexit': run_save_exit_tests,
    '06': run_save_exit_tests,
    'exit': run_save_exit_tests,
    'exception': run_exception_tests,
    '07': run_exception_tests,
    'exceptions': run_exception_tests,
    'integration': run_integration_tests,
    '08': run_integration_tests,
    'integ': run_integration_tests,
}


async def run_all_tests():
    """运行所有测试套件"""
    print("\n" + "=" * 70)
    print(f"INJECTION MOLDING OPTIMIZATION SYSTEM - FULL TEST SUITE")
    print(f"Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    all_results = []

    # 定义所有测试套件
    suites = [
        ("Session Management", run_session_tests),
        ("Optimization Flow", run_optimization_tests),
        ("Data Submission", run_data_tests),
        ("Safety Boundary", run_safety_tests),
        ("Rollback Mechanism", run_rollback_tests),
        ("Save and Exit", run_save_exit_tests),
        ("Exception Handling", run_exception_tests),
        ("Integration", run_integration_tests),
    ]

    for i, (name, test_func) in enumerate(suites, 1):
        print("\n" + "-" * 70)
        print(f"SUITE {i}: {name} Tests")
        print("-" * 70)
        try:
            result = await test_func()
            all_results.append((name, result))
        except Exception as e:
            print(f"Suite failed with error: {e}")
            import traceback
            traceback.print_exc()
            all_results.append((name, False))

    # 最终汇总
    print("\n" + "=" * 70)
    print("OVERALL TEST SUMMARY")
    print("=" * 70)

    for name, result in all_results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {name}")

    total_passed = sum(1 for _, r in all_results if r)
    total_tests = len(all_results)

    print(f"\nTotal: {total_passed}/{total_tests} test suites passed")
    print(f"Finished at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    return all(r for _, r in all_results)


def check_server():
    """检查服务器是否运行"""
    import urllib.request
    try:
        urllib.request.urlopen('http://localhost:8000/api', timeout=2)
        return True
    except:
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Run injection molding optimization tests',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
可用测试套件:
  session      - 会话管理测试 (test_01_session.py)
  optimization - 优化流程测试 (test_02_optimization.py)
  data         - 数据提交测试 (test_03_data_submit.py)
  safety       - 安全边界测试 (test_safety_boundary.py)
  rollback     - 回退机制测试 (test_05_rollback.py)
  save_exit    - 保存退出测试 (test_save_exit.py)
  exception    - 异常处理测试 (test_07_exceptions.py)
  integration  - 集成测试 (test_08_integration.py)
  all          - 运行所有测试

示例:
  python run_tests.py                    # 运行所有测试
  python run_tests.py session            # 只运行会话测试
  python run_tests.py safety rollback    # 运行多个特定测试
        """
    )
    parser.add_argument('test', nargs='?', default='all',
                        help='Test to run (default: all)')
    args = parser.parse_args()

    # 检查服务器
    print("Checking server status...")
    if not check_server():
        print("✗ ERROR: Server is not running at http://localhost:8000")
        print("  Please start the server first:")
        print("  cd /home/xt/Code/InjectionMolding/web_app/backend")
        print("  uvicorn app.main:app --host 0.0.0.0 --port 8000")
        sys.exit(1)
    print("✓ Server is running\n")

    # 运行测试
    test_name = args.test.lower()

    if test_name == 'all':
        success = asyncio.run(run_all_tests())
    elif test_name in TEST_SUITES:
        print(f"\nRunning {test_name} tests...\n")
        success = asyncio.run(TEST_SUITES[test_name]())
    else:
        print(f"Unknown test: {args.test}")
        print(f"Available tests: {', '.join(sorted(set(TEST_SUITES.keys())))}, all")
        sys.exit(1)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
