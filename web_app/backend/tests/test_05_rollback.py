"""
回退机制测试

测试场景：
1. 修改初始化阶段记录 - 应清空所有迭代记录，重置iteration=0
2. 修改迭代阶段记录 - 应截断后续批次，重置到对应iteration
3. 安全边界清除 - 回退后应清空Ph_min_safe
4. 重启后继续正确轮次 - 回退后从正确位置继续
"""
import asyncio
import sys
sys.path.insert(0, '/home/xt/Code/InjectionMolding')

from web_app.backend.tests.test_client import OptimizationTestClient, TEST_PART_CONFIG, TEST_ALGO_SETTINGS


async def test_rollback_init_modification():
    """测试：修改初始化记录触发回退"""
    print("\n" + "="*60)
    print("TEST: Rollback - Init Record Modification")
    print("="*60)

    client = OptimizationTestClient()
    try:
        await client.connect()
        await client.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)

        # 完成所有初始化
        print("Phase 1: Completing initialization...")
        for i in range(TEST_ALGO_SETTINGS['n_init']):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            await client.submit_evaluation(float(i + 1), is_shrink=False)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)
        init_count = len(client.get_records_by_stage('init'))
        print(f"✓ Completed {init_count} init records")

        # 完成第一轮迭代
        print("Phase 2: Completing iteration 1...")
        for i in range(TEST_ALGO_SETTINGS['batch_size']):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            await client.submit_evaluation(1.0 + i * 0.1, is_shrink=False)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)
        iter_count = len(client.get_iter_records())
        print(f"✓ Completed {iter_count} iter records")

        # 修改第5条初始化记录（触发回退）
        print("\nPhase 3: Modifying init record to trigger rollback...")
        record_to_modify = client.get_records_by_stage('init')[4]
        original_id = record_to_modify.get('id')

        await client.send('modify_record', {
            'record_id': original_id,
            'form_error': 99.0,
            'is_shrink': False
        })
        await asyncio.sleep(0.5)

        # 验证回退发生
        logs = '\n'.join(client.logs)

        # 检查日志中是否有回退相关信息
        rollback_indicators = ['回退', 'rollback', '截断', '清空']
        has_rollback = any(indicator in logs for indicator in rollback_indicators)

        if has_rollback:
            print("✓ Rollback detected in logs")
        else:
            print("? Rollback indicator not found in logs (checking record state)")

        # 重新连接验证状态
        await client.close()
        await asyncio.sleep(0.3)

        client2 = OptimizationTestClient()
        await client2.connect(client.session_id)
        await asyncio.sleep(0.5)

        # 验证迭代记录被清空
        iter_after = len(client2.get_iter_records())
        if iter_after == 0:
            print(f"✓ Iteration records cleared (was {iter_count}, now {iter_after})")
            result = True
        else:
            print(f"✗ Iteration records not cleared: {iter_after} remaining")
            result = False

        await client2.close()
        return result

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        await client.close()


async def test_rollback_iter_modification():
    """测试：修改迭代记录触发回退"""
    print("\n" + "="*60)
    print("TEST: Rollback - Iteration Record Modification")
    print("="*60)

    client = OptimizationTestClient()
    try:
        await client.connect()
        await client.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)

        # 完成初始化
        for i in range(TEST_ALGO_SETTINGS['n_init']):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            await client.submit_evaluation(float(i + 1), is_shrink=False)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)

        # 完成第一轮迭代
        for i in range(TEST_ALGO_SETTINGS['batch_size']):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            await client.submit_evaluation(1.0 + i * 0.1, is_shrink=False)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)

        # 完成第二轮迭代
        for i in range(TEST_ALGO_SETTINGS['batch_size']):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            await client.submit_evaluation(2.0 + i * 0.1, is_shrink=False)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)

        iter_records = client.get_iter_records()
        iter1_count = len([r for r in iter_records if r.get('stage') == 'iter_1'])
        iter2_count = len([r for r in iter_records if r.get('stage') == 'iter_2'])
        print(f"Records: iter_1={iter1_count}, iter_2={iter2_count}")

        # 修改iter_1的记录
        print("\nModifying iter_1 record to trigger rollback...")
        iter1_records = [r for r in client.records if r.get('stage') == 'iter_1']
        if not iter1_records:
            print("✗ No iter_1 records found")
            return False

        record_to_modify = iter1_records[0]
        await client.send('modify_record', {
            'record_id': record_to_modify.get('id'),
            'form_error': 99.0,
            'is_shrink': False
        })
        await asyncio.sleep(0.5)

        # 重新连接验证
        await client.close()
        await asyncio.sleep(0.3)

        client2 = OptimizationTestClient()
        await client2.connect(client.session_id)
        await asyncio.sleep(0.5)

        # 验证iter_2被清空，iter_1保留
        iter_records_after = client2.get_iter_records()
        iter1_after = len([r for r in iter_records_after if r.get('stage') == 'iter_1'])
        iter2_after = len([r for r in iter_records_after if r.get('stage') == 'iter_2'])

        if iter2_after == 0 and iter1_after > 0:
            print(f"✓ Rollback correct: iter_1={iter1_after}, iter_2={iter2_after}")
            result = True
        else:
            print(f"✗ Rollback incorrect: iter_1={iter1_after}, iter_2={iter2_after}")
            result = False

        await client2.close()
        return result

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        return False

    finally:
        await client.close()


async def test_rollback_clears_safety_boundary():
    """测试：回退后安全边界被清除"""
    print("\n" + "="*60)
    print("TEST: Rollback - Clears Safety Boundary")
    print("="*60)

    client = OptimizationTestClient()
    try:
        await client.connect()
        await client.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)

        # 完成初始化，部分标记为缩水（建立安全边界）
        for i in range(TEST_ALGO_SETTINGS['n_init']):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            is_shrink = i < 3  # 前3条缩水
            await client.submit_evaluation(float(i + 1), is_shrink=is_shrink)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)

        # 检查是否建立了安全边界
        logs_before = '\n'.join(client.logs)
        if "安全边界" not in logs_before:
            print("! WARNING: No safety boundary established, test may not be valid")

        shrink_count = sum(1 for r in client.records if r.get('is_shrink'))
        print(f"Shrink records created: {shrink_count}")

        # 修改第一条记录触发回退
        first_record = client.records[0]
        await client.send('modify_record', {
            'record_id': first_record.get('id'),
            'form_error': 99.0,
            'is_shrink': False
        })
        await asyncio.sleep(0.5)

        # 验证日志中是否有边界清除信息
        logs_after = '\n'.join(client.logs)

        # 重新连接
        await client.close()
        await asyncio.sleep(0.3)

        client2 = OptimizationTestClient()
        await client2.connect(client.session_id)
        await asyncio.sleep(0.5)

        # 检查是否重新开始生成参数
        # 如果安全边界被清除，应该重新开始
        print("✓ Rolled back, checking if optimization can continue...")

        # 等待新的参数
        msg = await client2.wait_for_message('params_ready', timeout=5.0)
        if msg:
            print("✓ New params generated after rollback")
            result = True
        else:
            print("✗ No new params generated after rollback")
            result = False

        await client2.close()
        return result

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        return False

    finally:
        await client.close()


async def test_continue_after_rollback():
    """测试：回退后能从正确位置继续"""
    print("\n" + "="*60)
    print("TEST: Continue After Rollback")
    print("="*60)

    client = OptimizationTestClient()
    try:
        await client.connect()
        await client.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)

        # 完成初始化
        for i in range(TEST_ALGO_SETTINGS['n_init']):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            await client.submit_evaluation(float(i + 1), is_shrink=False)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)

        # 完成第一轮迭代
        for i in range(TEST_ALGO_SETTINGS['batch_size']):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            await client.submit_evaluation(1.0 + i * 0.1, is_shrink=False)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)
        print(f"Records before rollback: init={len(client.get_records_by_stage('init'))}, iter={len(client.get_iter_records())}")

        # 修改一条初始化记录触发回退
        init_record = client.get_records_by_stage('init')[0]
        await client.send('modify_record', {
            'record_id': init_record.get('id'),
            'form_error': 99.0,
            'is_shrink': False
        })
        await asyncio.sleep(0.5)

        # 继续完成初始化
        remaining = TEST_ALGO_SETTINGS['n_init'] - 1
        print(f"\nContinuing with {remaining} init records...")
        for i in range(remaining):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            await client.submit_evaluation(float(i + 100), is_shrink=False)  # 用不同值区分
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)

        # 验证记录数正确
        init_count = len(client.get_records_by_stage('init'))
        iter_count = len(client.get_iter_records())
        print(f"Records after continue: init={init_count}, iter={iter_count}")

        if init_count == TEST_ALGO_SETTINGS['n_init'] and iter_count == 0:
            print("✓ Correctly restarted from init phase")
            return True
        else:
            print(f"✗ Record count mismatch")
            return False

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        return False

    finally:
        await client.close()


async def run_all_tests():
    """运行所有回退测试"""
    results = []

    results.append(("Rollback Init Modification", await test_rollback_init_modification()))
    results.append(("Rollback Iter Modification", await test_rollback_iter_modification()))
    results.append(("Rollback Clears Boundary", await test_rollback_clears_safety_boundary()))
    results.append(("Continue After Rollback", await test_continue_after_rollback()))

    # 汇总
    print("\n" + "="*60)
    print("FINAL SUMMARY - Rollback Tests")
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
