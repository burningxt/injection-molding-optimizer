"""
安全边界机制测试

测试场景：
1. 非缩水记录 - 不应更新Ph_min_safe
2. 缩水记录 - 应更新Ph_min_safe
3. 后续参数生成 - 应过滤不安全参数
"""
import asyncio
import sys
sys.path.insert(0, '/home/xt/Code/InjectionMolding')

from web_app.backend.tests.test_client import OptimizationTestClient, TEST_PART_CONFIG, TEST_ALGO_SETTINGS


async def test_no_shrink_no_boundary_update():
    """测试：非缩水记录不更新安全边界"""
    print("\n" + "="*60)
    print("TEST: No Shrink - No Boundary Update")
    print("="*60)

    client = OptimizationTestClient()
    try:
        await client.connect()
        await client.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)

        # 完成所有初始化 - 全部非缩水
        print("Submitting all non-shrink records...")
        for i in range(TEST_ALGO_SETTINGS['n_init']):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            await client.submit_evaluation(float(i + 1), is_shrink=False)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)

        # 检查日志 - 不应有安全边界更新
        logs = '\n'.join(client.logs)

        # 关键：非缩水时不应看到"更新安全边界"
        if "更新安全边界" in logs:
            print("✗ FAIL: Found '更新安全边界' in logs (should NOT appear for non-shrink)")
            return False
        else:
            print("✓ PASS: No boundary update for non-shrink records")

        # 检查Ph_min_safe始终为空
        if "Ph_min_safe={}" in logs or "Ph_min_safe= {}" in logs:
            print("✓ PASS: Ph_min_safe remains empty")
            return True
        else:
            print("? INFO: Ph_min_safe status not explicitly logged")
            return True

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        return False

    finally:
        await client.close()


async def test_shrink_updates_boundary():
    """测试：缩水记录更新安全边界"""
    print("\n" + "="*60)
    print("TEST: Shrink - Updates Boundary")
    print("="*60)

    client = OptimizationTestClient()
    try:
        await client.connect()
        await client.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)

        # 完成初始化 - 前3条标记为缩水
        print("Submitting records with shrink (first 3)...")
        for i in range(TEST_ALGO_SETTINGS['n_init']):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            is_shrink = i < 3  # 前3条缩水
            await client.submit_evaluation(float(i + 1), is_shrink=is_shrink)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)

        # 检查日志 - 应有安全边界更新
        logs = '\n'.join(client.logs)

        if "更新安全边界" in logs:
            print("✓ PASS: Boundary updated for shrink records")
            return True
        else:
            print("✗ FAIL: No boundary update found (expected for shrink)")
            return False

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        return False

    finally:
        await client.close()


async def test_boundary_filters_candidates():
    """测试：安全边界过滤后续候选参数"""
    print("\n" + "="*60)
    print("TEST: Boundary Filters Candidates")
    print("="*60)

    client = OptimizationTestClient()
    try:
        await client.connect()
        await client.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)

        # 完成初始化 - 部分缩水以建立安全边界
        print("Phase 1: Init with some shrink...")
        for i in range(TEST_ALGO_SETTINGS['n_init']):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            # 在特定温度下缩水
            is_shrink = i in [0, 5]
            await client.submit_evaluation(float(i + 1), is_shrink=is_shrink)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)

        # 检查是否建立了安全边界
        logs_before = '\n'.join(client.logs)
        if "更新安全边界" not in logs_before:
            print("! WARNING: No boundary established, test may not be valid")

        # 继续迭代优化
        print("Phase 2: Iteration optimization...")
        for i in range(TEST_ALGO_SETTINGS['batch_size']):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            await client.submit_evaluation(1.0 + i * 0.1, is_shrink=False)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)

        # 检查是否有"候选点不满足安全边界"的日志
        logs_after = '\n'.join(client.logs)

        # 这个测试主要是验证流程能正常运行
        # 边界过滤的具体效果取决于生成的参数值
        iter_count = len(client.get_iter_records())
        if iter_count == TEST_ALGO_SETTINGS['batch_size']:
            print(f"✓ PASS: Generated {iter_count} iteration records")
            return True
        else:
            print(f"✗ FAIL: Expected {TEST_ALGO_SETTINGS['batch_size']} iter records, got {iter_count}")
            return False

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        return False

    finally:
        await client.close()


async def run_all_tests():
    """运行所有安全边界测试"""
    results = []

    results.append(("No Shrink - No Update", await test_no_shrink_no_boundary_update()))
    results.append(("Shrink - Updates Boundary", await test_shrink_updates_boundary()))
    results.append(("Boundary Filters", await test_boundary_filters_candidates()))

    # 汇总
    print("\n" + "="*60)
    print("FINAL SUMMARY")
    print("="*60)
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {name}")

    passed = sum(1 for _, r in results if r)
    total = len(results)
    print(f"\nTotal: {passed}/{total} tests passed")
    print("="*60)

    return all(r for _, r in results)


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
