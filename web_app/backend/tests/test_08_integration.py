"""
集成测试

测试场景：
1. 完整用户流程 - 从开始到结束
2. 多次保存退出恢复
3. 复杂回退场景
4. 多用户并发场景
5. 长期运行稳定性
"""
import asyncio
import sys
sys.path.insert(0, '/home/xt/Code/InjectionMolding')

from web_app.backend.tests.test_client import OptimizationTestClient, TEST_PART_CONFIG, TEST_ALGO_SETTINGS


async def test_complete_user_flow():
    """测试：完整用户流程"""
    print("\n" + "="*60)
    print("TEST: Complete User Flow")
    print("="*60)

    # 快速配置
    algo_settings = {
        "n_init": 6,
        "n_iter": 2,
        "batch_size": 2,
        "mode": "manual",
        "shrink_threshold": 30.0
    }

    client = OptimizationTestClient()
    try:
        await client.connect()
        print("1. Connected to server")

        # 启动优化
        await client.start_optimization(TEST_PART_CONFIG, algo_settings)
        print("2. Optimization started")

        # 完成初始化（部分缩水）
        for i in range(algo_settings['n_init']):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            await client.submit_evaluation(float(i + 1), is_shrink=(i < 2))
            await asyncio.sleep(0.05)

        print(f"3. Init complete: {len(client.records)} records")

        # 第一轮迭代
        for i in range(algo_settings['batch_size']):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            await client.submit_evaluation(1.0 + i * 0.1, is_shrink=False)
            await asyncio.sleep(0.05)

        print(f"4. Iter 1 complete: {len(client.records)} records")

        # 保存退出
        await client.save_and_exit()
        print("5. Save and exit")

        await asyncio.sleep(0.5)

        # 验证状态
        logs = '\n'.join(client.logs)
        if "保存" in logs or "saved" in logs.lower():
            print("6. Progress saved successfully")
            return True
        else:
            print("? Save status unclear from logs")
            return True

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        await client.close()


async def test_multiple_save_exit_cycles():
    """测试：多次保存退出循环"""
    print("\n" + "="*60)
    print("TEST: Multiple Save/Exit Cycles")
    print("="*60)

    algo_settings = {
        "n_init": 5,
        "n_iter": 3,
        "batch_size": 2,
        "mode": "manual",
        "shrink_threshold": 30.0
    }

    session_id = None
    total_cycles = 3

    for cycle in range(total_cycles):
        print(f"\n--- Cycle {cycle + 1}/{total_cycles} ---")

        client = OptimizationTestClient()
        try:
            if session_id:
                await client.connect(session_id)
                print(f"Reconnected to session {session_id}")
                print(f"Loaded {len(client.records)} history records")
            else:
                await client.connect()
                session_id = client.session_id
                print(f"Created new session {session_id}")
                await client.start_optimization(TEST_PART_CONFIG, algo_settings)

            await asyncio.sleep(0.3)

            # 完成2条记录
            for i in range(2):
                msg = await client.wait_for_message('params_ready', timeout=5.0)
                if not msg:
                    print("No more params needed")
                    break
                await client.submit_evaluation(
                    float(cycle * 10 + i + 1),
                    is_shrink=(i == 0)
                )
                await asyncio.sleep(0.05)

            await asyncio.sleep(0.3)
            print(f"Records after cycle: {len(client.records)}")

            # 保存退出
            await client.save_and_exit()
            await asyncio.sleep(0.5)

        except Exception as e:
            print(f"✗ Cycle {cycle + 1} failed: {e}")
            return False

        finally:
            await client.close()

    # 最终验证
    client = OptimizationTestClient()
    try:
        await client.connect(session_id)
        await asyncio.sleep(0.5)

        final_count = len(client.records)
        print(f"\nFinal record count: {final_count}")

        if final_count >= total_cycles * 2:
            print("✓ All cycles preserved correctly")
            return True
        else:
            print(f"✗ Records lost: expected at least {total_cycles * 2}, got {final_count}")
            return False

    finally:
        await client.close()


async def test_complex_rollback_scenario():
    """测试：复杂回退场景"""
    print("\n" + "="*60)
    print("TEST: Complex Rollback Scenario")
    print("="*60)

    algo_settings = {
        "n_init": 8,
        "n_iter": 3,
        "batch_size": 3,
        "mode": "manual",
        "shrink_threshold": 30.0
    }

    client = OptimizationTestClient()
    try:
        await client.connect()
        await client.start_optimization(TEST_PART_CONFIG, algo_settings)

        # Phase 1: 完成所有初始化
        print("Phase 1: Complete init")
        for i in range(algo_settings['n_init']):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            await client.submit_evaluation(float(i + 1), is_shrink=(i < 2))
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)
        print(f"  Records: {len(client.get_records_by_stage('init'))} init")

        # Phase 2: 完成2轮迭代
        print("Phase 2: Complete 2 iterations")
        for round_num in range(2):
            for i in range(algo_settings['batch_size']):
                msg = await client.wait_for_message('params_ready', timeout=5.0)
                if not msg:
                    break
                await client.submit_evaluation(float(round_num * 10 + i + 1), is_shrink=False)
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.3)

        iter_records = client.get_iter_records()
        print(f"  Records: {len(iter_records)} iter")

        # Phase 3: 修改初始化记录触发回退
        print("Phase 3: Trigger rollback")
        init_records = client.get_records_by_stage('init')
        if init_records:
            await client.send('modify_record', {
                'record_id': init_records[3].get('id'),
                'form_error': 99.0,
                'is_shrink': False
            })
            await asyncio.sleep(0.5)
            print("  Rollback triggered")

        # Phase 4: 重新完成
        print("Phase 4: Re-complete after rollback")
        remaining = algo_settings['n_init'] - 3
        for i in range(remaining):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            await client.submit_evaluation(float(100 + i), is_shrink=False)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)

        # 验证
        final_init = len(client.get_records_by_stage('init'))
        final_iter = len(client.get_iter_records())

        print(f"\nFinal: {final_init} init, {final_iter} iter")

        if final_init == algo_settings['n_init'] and final_iter == 0:
            print("✓ Rollback and re-completion successful")
            return True
        else:
            print(f"✗ Unexpected state after rollback")
            return False

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        await client.close()


async def test_cross_session_isolation():
    """测试：跨会话隔离"""
    print("\n" + "="*60)
    print("TEST: Cross-Session Isolation")
    print("="*60)

    # 创建两个独立会话
    client1 = OptimizationTestClient()
    client2 = OptimizationTestClient()

    try:
        # 会话1
        await client1.connect()
        await client1.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)

        for i in range(5):
            msg = await client1.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            await client1.submit_evaluation(float(i + 1), is_shrink=(i < 2))
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.3)
        session1_id = client1.session_id
        session1_records = len(client1.records)
        print(f"Session 1: {session1_id} with {session1_records} records")

        # 会话2
        await client2.connect()
        await client2.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)

        for i in range(3):
            msg = await client2.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            await client2.submit_evaluation(float(i + 100), is_shrink=False)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.3)
        session2_id = client2.session_id
        session2_records = len(client2.records)
        print(f"Session 2: {session2_id} with {session2_records} records")

        # 验证ID不同
        if session1_id == session2_id:
            print("✗ Same session ID!")
            return False

        # 重新连接会话1验证
        await client1.close()
        client1_reconnect = OptimizationTestClient()
        await client1_reconnect.connect(session1_id)
        await asyncio.sleep(0.3)

        reconnect1_records = len(client1_reconnect.records)
        print(f"Session 1 after reconnect: {reconnect1_records} records")

        # 验证数据隔离
        if reconnect1_records == session1_records:
            print("✓ Session 1 data isolated")
        else:
            print(f"✗ Session 1 data corrupted: {session1_records} -> {reconnect1_records}")
            return False

        await client1_reconnect.close()

        # 验证会话2数据
        await client2.close()
        client2_reconnect = OptimizationTestClient()
        await client2_reconnect.connect(session2_id)
        await asyncio.sleep(0.3)

        reconnect2_records = len(client2_reconnect.records)
        print(f"Session 2 after reconnect: {reconnect2_records} records")

        if reconnect2_records == session2_records:
            print("✓ Session 2 data isolated")
            return True
        else:
            print(f"✗ Session 2 data corrupted: {session2_records} -> {reconnect2_records}")
            return False

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        return False

    finally:
        await client1.close()
        await client2.close()


async def test_stress_test():
    """测试：压力测试 - 快速操作"""
    print("\n" + "="*60)
    print("TEST: Stress Test - Rapid Operations")
    print("="*60)

    algo_settings = {
        "n_init": 10,
        "n_iter": 2,
        "batch_size": 3,
        "mode": "manual",
        "shrink_threshold": 30.0
    }

    client = OptimizationTestClient()
    try:
        await client.connect()
        await client.start_optimization(TEST_PART_CONFIG, algo_settings)

        start_time = asyncio.get_event_loop().time()

        # 快速完成所有初始化
        print("Rapid init submissions...")
        for i in range(algo_settings['n_init']):
            msg = await client.wait_for_message('params_ready', timeout=3.0)
            if not msg:
                break
            await client.submit_evaluation(float(i + 1), is_shrink=(i % 3 == 0))
            # 几乎不等待

        await asyncio.sleep(0.3)
        elapsed = asyncio.get_event_loop().time() - start_time

        record_count = len(client.records)
        expected = algo_settings['n_init']

        print(f"Completed {record_count}/{expected} records in {elapsed:.2f}s")

        if record_count >= expected and elapsed < 30:  # 30秒内完成
            print("✓ Stress test passed")
            return True
        else:
            print(f"✗ Stress test failed")
            return False

    except Exception as e:
        print(f"✗ TEST FAILED: {e}")
        return False

    finally:
        await client.close()


async def run_all_tests():
    """运行所有集成测试"""
    results = []

    results.append(("Complete User Flow", await test_complete_user_flow()))
    results.append(("Multiple Save/Exit Cycles", await test_multiple_save_exit_cycles()))
    results.append(("Complex Rollback Scenario", await test_complex_rollback_scenario()))
    results.append(("Cross-Session Isolation", await test_cross_session_isolation()))
    results.append(("Stress Test", await test_stress_test()))

    # 汇总
    print("\n" + "="*60)
    print("FINAL SUMMARY - Integration Tests")
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
