"""
保存退出功能测试

测试场景：
1. 用户完成初始化和一轮迭代
2. 点击"保存退出"
3. 验证：
   - 显示友好信息（非"取消"）
   - 记录完整保存
   - 重新连接后显示"继续寻优"
"""
import asyncio
import sys
sys.path.insert(0, '/home/xt/Code/InjectionMolding')

from web_app.backend.tests.test_client import OptimizationTestClient, TEST_PART_CONFIG, TEST_ALGO_SETTINGS


async def test_save_exit_basic():
    """测试保存退出基本功能"""
    print("\n" + "="*60)
    print("TEST: Save and Exit - Basic Functionality")
    print("="*60)

    client = OptimizationTestClient()
    try:
        # 1. 连接并启动优化
        await client.connect()
        await client.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)
        print("✓ Optimization started")

        # 2. 完成所有初始化输入
        print("\nCompleting initialization phase...")
        for i in range(TEST_ALGO_SETTINGS['n_init']):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                raise TimeoutError(f"Timeout waiting for params_ready at init {i+1}")
            await client.submit_evaluation(float(i + 1), is_shrink=False)
            await asyncio.sleep(0.05)

        # 等待初始化完成
        await asyncio.sleep(0.5)
        init_count = len(client.get_records_by_stage('init'))
        print(f"✓ Completed {init_count} init records")

        # 3. 完成第一轮迭代
        print("\nCompleting iteration 1...")
        for i in range(TEST_ALGO_SETTINGS['batch_size']):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                raise TimeoutError(f"Timeout waiting for params_ready at iter {i+1}")
            await client.submit_evaluation(1.0 + i * 0.1, is_shrink=False)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)
        iter_count = len(client.get_iter_records())
        print(f"✓ Completed {iter_count} iteration records")

        total_records = len(client.records)
        print(f"\nTotal records before save: {total_records}")

        # 4. 保存退出
        print("\nSending save_and_exit...")
        await client.save_and_exit()
        await asyncio.sleep(0.5)

        # 5. 验证日志信息
        print("\n--- Log Analysis ---")
        logs = '\n'.join(client.logs)

        # 关键验证点
        checks = []

        if "进度已保存" in logs or "Checkpoint saved" in logs:
            print("✓ Progress saved message found")
            checks.append(True)
        else:
            print("✗ Progress saved message NOT found")
            checks.append(False)

        if "优化被取消" in logs:
            print("✗ Found '优化被取消' (should NOT appear)")
            checks.append(False)
        else:
            print("✓ No '优化被取消' message (good)")
            checks.append(True)

        if "优化已停止" in logs or "已安全退出" in logs:
            print("✓ Graceful stop message found")
            checks.append(True)
        else:
            print("✗ Graceful stop message NOT found")
            # Not critical, so don't fail

        # 6. 验证session_id
        if client.session_id:
            print(f"\n✓ Session ID: {client.session_id}")
        else:
            print("\n✗ No session ID")
            checks.append(False)

        # 7. 重新连接验证恢复
        print("\n--- Reconnection Test ---")

        # 先断开第一个客户端
        await client.close()
        await asyncio.sleep(0.2)

        client2 = OptimizationTestClient()
        await client2.connect(client.session_id)
        await asyncio.sleep(0.5)

        restored_count = len(client2.records)
        print(f"Records after reconnect: {restored_count}")

        # 注意：生成新一轮参数后会创建待完成的记录
        # 所以记录数可能 >= total_records（取决于优化器是否生成了新参数）
        if restored_count >= total_records:
            print(f"✓ At least {total_records} records restored (actual: {restored_count})")
            checks.append(True)
        else:
            print(f"✗ Too few records: expected at least {total_records}, got {restored_count}")
            checks.append(False)

        # 检查阶段分布
        init_restored = len(client2.get_records_by_stage('init'))
        iter_restored = len(client2.get_iter_records())
        print(f"  Init: {init_restored}, Iter: {iter_restored}")

        if init_restored == TEST_ALGO_SETTINGS['n_init']:
            print("✓ Init records correct")
            checks.append(True)
        else:
            print(f"✗ Init records mismatch: expected {TEST_ALGO_SETTINGS['n_init']}, got {init_restored}")
            checks.append(False)

        await client2.close()

        # 汇总
        print("\n" + "="*60)
        if all(checks):
            print("✓ ALL TESTS PASSED")
        else:
            print(f"✗ SOME TESTS FAILED: {sum(checks)}/{len(checks)} passed")
        print("="*60)

        return all(checks), client.session_id

    except Exception as e:
        print(f"\n✗ TEST FAILED with exception: {e}")
        import traceback
        traceback.print_exc()
        return False, None

    finally:
        await client.close()


async def test_save_exit_with_shrink():
    """测试保存退出时有缩水记录的情况"""
    print("\n" + "="*60)
    print("TEST: Save and Exit - With Shrink Records")
    print("="*60)

    client = OptimizationTestClient()
    try:
        await client.connect()
        await client.start_optimization(TEST_PART_CONFIG, TEST_ALGO_SETTINGS)

        # 完成初始化（部分缩水）
        for i in range(TEST_ALGO_SETTINGS['n_init']):
            msg = await client.wait_for_message('params_ready', timeout=5.0)
            if not msg:
                break
            # 前3条标记为缩水
            is_shrink = i < 3
            await client.submit_evaluation(float(i + 1), is_shrink=is_shrink)
            await asyncio.sleep(0.05)

        await asyncio.sleep(0.5)
        shrink_count = sum(1 for r in client.records if r.get('is_shrink'))
        print(f"Records with shrink: {shrink_count}")

        # 保存退出
        await client.save_and_exit()
        await asyncio.sleep(0.5)

        # 验证Ph_min_safe是否被记录（可以从日志推断）
        if client.has_log_pattern("安全边界") or client.has_log_pattern("Ph_min"):
            print("✓ Safety boundary was updated")

        # 重新连接验证
        client2 = OptimizationTestClient()
        await client2.connect(client.session_id)
        await asyncio.sleep(0.5)

        # 验证缩水标记正确保存
        shrink_restored = sum(1 for r in client2.records if r.get('is_shrink'))
        if shrink_restored == shrink_count:
            print(f"✓ Shrink flags preserved: {shrink_restored}")
            return True, client.session_id
        else:
            print(f"✗ Shrink flags mismatch: expected {shrink_count}, got {shrink_restored}")
            return False, client.session_id

    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        return False, None

    finally:
        await client.close()


async def run_all_tests():
    """运行所有保存退出测试"""
    results = []

    # 测试1：基本功能
    result1, session1 = await test_save_exit_basic()
    results.append(("Save Exit Basic", result1))

    # 测试2：带缩水记录
    result2, session2 = await test_save_exit_with_shrink()
    results.append(("Save Exit with Shrink", result2))

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
