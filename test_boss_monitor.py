#!/usr/bin/env python3
"""
測試Boss監控系統
"""

import sys
from datetime import datetime
from boss_monitor import BossMonitor, BossInfo, SmallBossInfo


def test_fetch_boss_data():
    """測試獲取boss資料功能"""
    print("=== 測試獲取boss資料 ===")
    monitor = BossMonitor()
    
    try:
        big_boss_data, small_boss_data = monitor.fetch_boss_data()
        
        print(f"成功獲取 {len(big_boss_data)} 個Big Boss, {len(small_boss_data)} 個Small Boss:")
        
        if big_boss_data:
            print("\nBig Boss:")
            for boss_info in big_boss_data:
                print(f"  - 遊戲ID: {boss_info.game_id}, Boss: {boss_info.name}")
                print(f"    位置: ({boss_info.location[0]}, {boss_info.location[1]})")
                print(f"    持續: {boss_info.duration_minutes} 分鐘")
        
        if small_boss_data:
            print("\nSmall Boss:")
            for boss_info in small_boss_data:
                print(f"  - 遊戲ID: {boss_info.game_id}, Boss: {boss_info.name}")
                print(f"    位置: ({boss_info.location[0]}, {boss_info.location[1]})")
                print(f"    距離Bunker: {boss_info.distance_from_bunker}")
                print(f"    持續: {boss_info.duration_minutes} 分鐘")
        
        if not big_boss_data and not small_boss_data:
            print("沒有找到符合條件的boss")
        
        return True
    except Exception as e:
        print(f"測試失敗: {e}")
        return False


def test_message_formatting():
    """測試訊息格式化功能"""
    print("\n=== 測試訊息格式化 ===")
    monitor = BossMonitor()
    current_time = datetime.now()
    
    # 測試Big Boss
    end_time = current_time.replace(hour=current_time.hour + 2)
    big_boss1 = BossInfo("5", "Devil Hound", current_time, end_time, (1053, 990))
    
    # 測試Small Boss (距離Bunker 2格內)
    small_boss1 = SmallBossInfo("6", "Small Enemy", current_time, end_time, (1056, 985))  # 2右2上
    small_boss2 = SmallBossInfo("7", "Another Small", current_time, end_time, (1052, 989))  # 2左2下
    
    # 測試訊息格式化
    message = monitor.format_boss_message([big_boss1], [small_boss1, small_boss2])
    print("混合Boss訊息:")
    print(message)
    
    # 測試只有Small Boss
    message2 = monitor.format_boss_message([], [small_boss1])
    print("\n只有Small Boss訊息:")
    print(message2)
    
    return True


def test_slack_notification():
    """測試Slack通知功能（可選）"""
    print("\n=== 測試Slack通知 ===")
    answer = input("是否要測試Slack通知功能？(y/n): ").lower().strip()
    
    if answer == 'y':
        monitor = BossMonitor()
        test_message = "測試訊息 - Boss監控系統運行正常"
        
        success = monitor.send_slack_notification(test_message)
        if success:
            print("Slack通知測試成功！")
        else:
            print("Slack通知測試失敗，請檢查配置")
        return success
    else:
        print("跳過Slack通知測試")
        return True


def main():
    """主測試函數"""
    print("Boss監控系統測試開始")
    print("=" * 50)
    
    tests = [
        ("網頁爬蟲", test_fetch_boss_data),
        ("訊息格式化", test_message_formatting),
        ("Slack通知", test_slack_notification),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"{test_name}測試發生錯誤: {e}")
            results.append((test_name, False))
    
    print("\n" + "=" * 50)
    print("測試結果總結:")
    for test_name, passed in results:
        status = "✓ 通過" if passed else "✗ 失敗"
        print(f"  {test_name}: {status}")
    
    all_passed = all(result for _, result in results)
    if all_passed:
        print("\n🎉 所有測試通過！系統準備就緒。")
        print("\n要啟動Boss監控程序，請運行:")
        print("  uv run boss_monitor.py")
    else:
        print("\n⚠️  部分測試失敗，請檢查配置和網絡連接。")


if __name__ == "__main__":
    main()
