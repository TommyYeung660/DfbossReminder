import requests
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import schedule
import time
import logging

from config import (
    SLACK_WEBHOOK_URL, SLACK_CHANNEL, SLACK_USERNAME, SLACK_ICON_EMOJI,
    BOSS_MAP_URL, CHECK_INTERVAL_MINUTES, USER_ID_MAPPING, DEFAULT_USER_ID,
    LOCATION_TRACK_CHANNEL, LOCATION_CHECK_INTERVAL_MINUTES
)

# 設置日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class BossInfo:
    """Boss資訊類別"""
    def __init__(self, game_id: str, name: str, start_time: datetime, end_time: datetime, location: tuple):
        self.game_id = game_id
        self.name = name
        self.start_time = start_time
        self.end_time = end_time
        self.location = location  # (x, y) 座標
        self.duration_minutes = int((end_time - start_time).total_seconds() / 60)
    
    def __str__(self):
        return f"Boss: {self.name}\nLocation: ({self.location[0]}, {self.location[1]})\nStart time: {self.start_time.strftime('%H:%M')}\nEnd time: {self.end_time.strftime('%H:%M')}\nDuration: {self.duration_minutes} minutes"


class SmallBossInfo:
    """Small Boss資訊類別"""
    def __init__(self, game_id: str, name: str, start_time: datetime, end_time: datetime, location: tuple):
        self.game_id = game_id
        self.name = name
        self.start_time = start_time
        self.end_time = end_time
        self.location = location  # (x, y) 座標
        self.duration_minutes = int((end_time - start_time).total_seconds() / 60)
        self.distance_from_bunker = self._calculate_distance_description()
    
    def _calculate_distance_description(self):
        """計算與Secronom Bunker的相對位置描述"""
        bunker_x, bunker_y = 1054, 987
        boss_x, boss_y = int(self.location[0]), int(self.location[1])
        
        dx = boss_x - bunker_x  # 正數為右，負數為左
        dy = boss_y - bunker_y  # 正數為下，負數為上
        
        description_parts = []
        
        if abs(dx) > 0:
            if dx > 0:
                description_parts.append(f"{abs(dx)}右")
            else:
                description_parts.append(f"{abs(dx)}左")
        
        if abs(dy) > 0:
            if dy > 0:
                description_parts.append(f"{abs(dy)}下")
            else:
                description_parts.append(f"{abs(dy)}上")
        
        if not description_parts:
            return "位於Bunker"
        
        return "".join(description_parts)
    
    def __str__(self):
        return f"Small Boss: {self.name}\nLocation: ({self.location[0]}, {self.location[1]})\nDistance from Secronom Bunker: {self.distance_from_bunker}\nStart time: {self.start_time.strftime('%H:%M')}\nEnd time: {self.end_time.strftime('%H:%M')}\nDuration: {self.duration_minutes} minutes"


class PlayerLocation:
    """角色位置類別"""
    def __init__(self, user_id: str, username: str, x: int, y: int):
        self.user_id = user_id
        self.username = username
        self.x = x
        self.y = y
        self.location = (x, y)
    
    def calculate_distance_to(self, target_location: tuple) -> tuple:
        """計算到目標位置的距離，返回(距離, 方向描述)"""
        target_x, target_y = int(target_location[0]), int(target_location[1])
        dx = target_x - self.x
        dy = target_y - self.y
        
        distance = max(abs(dx), abs(dy))
        
        description_parts = []
        if abs(dx) > 0:
            if dx > 0:
                description_parts.append(f"{abs(dx)}右")
            else:
                description_parts.append(f"{abs(dx)}左")
        
        if abs(dy) > 0:
            if dy > 0:
                description_parts.append(f"{abs(dy)}下")
            else:
                description_parts.append(f"{abs(dy)}上")
        
        if not description_parts:
            return distance, "相同位置"
        
        return distance, "".join(description_parts)


class BossMonitor:
    """Boss監控類別"""
    
    def __init__(self, user_id: str = DEFAULT_USER_ID):
        self.current_big_bosses: Dict[str, BossInfo] = {}
        self.current_small_bosses: Dict[str, SmallBossInfo] = {}
        self.user_id = user_id
    
    def fetch_boss_data(self) -> tuple[List[BossInfo], List[SmallBossInfo]]:
        """
        獲取當前boss資料
        返回: (big_bosses, small_bosses)
        """
        try:
            # 生成當前時間戳作為URL參數
            timestamp = int(time.time() * 1000)
            json_url = f"https://www.dfprofiler.com/bossmap/json/?_={timestamp}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Accept-Language': 'en-US,en;q=0.5',
                'Referer': 'https://www.dfprofiler.com/bossmap',
                'X-Requested-With': 'XMLHttpRequest',
            }
            
            logger.info(f"正在請求JSON數據: {json_url}")
            response = requests.get(json_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            big_bosses = []
            small_bosses = []
            
            # Secronom Bunker 座標
            bunker_x, bunker_y = 1054, 987
            
            # 解析JSON數據
            for game_id, boss_data in data.items():
                # 確保boss_data是字典類型
                if not isinstance(boss_data, dict):
                    continue
                    
                # 檢查是否為boss事件（有location且special_enemy_type不為空）
                if (boss_data.get('locations') and 
                    boss_data.get('special_enemy_type') and 
                    boss_data['special_enemy_type'] != '0'):
                    
                    boss_name = boss_data['special_enemy_type']
                    start_timestamp = int(boss_data['start_time'])
                    end_timestamp = int(boss_data['end_time'])
                    
                    start_time = datetime.fromtimestamp(start_timestamp)
                    end_time = datetime.fromtimestamp(end_timestamp)
                    current_time = datetime.now()
                    
                    # 跳過已經結束的歷史boss
                    if end_time <= current_time:
                        logger.debug(f"跳過已結束的boss: {boss_name} (結束時間: {end_time.strftime('%H:%M')})")
                        continue
                    
                    # 計算持續時間（分鐘）
                    duration_minutes = (end_timestamp - start_timestamp) / 60
                    
                    # 檢查是否為Big Boss（時間條件）
                    if 61 <= duration_minutes <= 240:
                        # Big Boss: 使用第一個位置作為代表
                        location = boss_data['locations'][0]
                        boss_info = BossInfo(game_id, boss_name, start_time, end_time, tuple(location))
                        big_bosses.append(boss_info)
                        logger.info(f"找到Big Boss: {boss_name} (遊戲ID: {game_id}, 持續: {duration_minutes:.1f}分鐘)")
                    else:
                        # 檢查是否有任何位置在Bunker 3格範圍內（Small Boss）
                        nearby_locations = []
                        
                        for location in boss_data['locations']:
                            boss_x, boss_y = int(location[0]), int(location[1])
                            distance = max(abs(boss_x - bunker_x), abs(boss_y - bunker_y))
                            
                            if distance <= 3:
                                nearby_locations.append(location)
                        
                        # 為每個在範圍內的位置創建一個Small Boss條目
                        if nearby_locations:
                            for i, location in enumerate(nearby_locations):
                                # 為多個位置的同一boss添加位置索引
                                boss_display_name = boss_name if len(nearby_locations) == 1 else f"{boss_name} #{i+1}"
                                small_boss_info = SmallBossInfo(f"{game_id}_{i}", boss_display_name, start_time, end_time, tuple(location))
                                small_bosses.append(small_boss_info)
                                logger.info(f"找到Small Boss: {boss_display_name} (遊戲ID: {game_id}, 位置: {location}, 距離Bunker: {small_boss_info.distance_from_bunker})")
                        else:
                            logger.debug(f"跳過boss: {boss_name} (持續: {duration_minutes:.1f}分鐘, 不在Bunker 3格範圍內)")
            
            if not big_bosses and not small_bosses:
                logger.info("沒有找到符合條件的boss")
            else:
                logger.info(f"找到 {len(big_bosses)} 個Big Boss, {len(small_bosses)} 個Small Boss")
            
            return big_bosses, small_bosses
            
        except requests.exceptions.RequestException as e:
            logger.error(f"網絡請求錯誤: {e}")
            return [], []
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析錯誤: {e}")
            return [], []
        except Exception as e:
            logger.error(f"獲取boss數據時發生錯誤: {e}")
            return [], []
    
    def fetch_player_location(self) -> Optional[PlayerLocation]:
        """獲取角色位置"""
        try:
            timestamp = int(time.time() * 1000)
            profile_url = f"https://www.dfprofiler.com/profile/json/{self.user_id}?_={timestamp}"
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Accept-Language': 'en-US,en;q=0.5',
                'Referer': 'https://www.dfprofiler.com/bossmap',
                'X-Requested-With': 'XMLHttpRequest',
            }
            
            logger.info(f"正在獲取角色位置: {profile_url}")
            response = requests.get(profile_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if 'gpscoords' in data and len(data['gpscoords']) >= 2:
                x = int(data['gpscoords'][0])
                y = int(data['gpscoords'][1])
                username = data.get('override', {}).get('account_name', 'Unknown')
                
                player = PlayerLocation(self.user_id, username, x, y)
                logger.info(f"獲取到角色位置: {username} 在 ({x}, {y})")
                return player
            else:
                logger.warning("角色位置數據格式錯誤")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"獲取角色位置時網絡錯誤: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"解析角色位置JSON時錯誤: {e}")
            return None
        except Exception as e:
            logger.error(f"獲取角色位置時發生錯誤: {e}")
            return None
    
    def send_slack_notification(self, message: str, channel: str = SLACK_CHANNEL) -> bool:
        """發送Slack通知"""
        try:
            payload = {
                "channel": channel,
                "username": SLACK_USERNAME,
                "icon_emoji": SLACK_ICON_EMOJI,
                "text": message
            }
            
            response = requests.post(
                SLACK_WEBHOOK_URL,
                json=payload,
                timeout=30
            )
            response.raise_for_status()
            
            logger.info("Slack通知發送成功")
            return True
            
        except requests.RequestException as e:
            logger.error(f"Slack通知發送失敗: {e}")
            return False
    
    def format_boss_message(self, big_bosses: List[BossInfo], small_bosses: List[SmallBossInfo]) -> str:
        """格式化boss訊息（先按boss名稱，再按距離Bunker排序）"""
        messages = []
        bunker_x, bunker_y = 1054, 987
        
        # 處理 Big Boss - 1格內的優先排最上
        if big_bosses:
            messages.append("=== BIG BOSS ===")
            # 計算每個Big Boss到Bunker的距離並排序
            big_boss_with_data = []
            for boss in big_bosses:
                boss_x, boss_y = int(boss.location[0]), int(boss.location[1])
                distance = max(abs(boss_x - bunker_x), abs(boss_y - bunker_y))
                big_boss_with_data.append((boss.name, distance, boss))
            
            # 排序：1格內的優先（distance <= 1），其餘按名稱再按距離
            big_boss_with_data.sort(key=lambda x: (0 if x[1] <= 1 else 1, x[0], x[1]))
            
            for name, distance, boss in big_boss_with_data:
                # 1格內的boss加醒目emoji
                if distance <= 1:
                    boss_str = str(boss)
                    # 為1格內的boss添加醒目emoji
                    boss_lines = boss_str.split('\n')
                    boss_lines[0] = f"🚨 {boss_lines[0]} 🚨"
                    messages.append('\n'.join(boss_lines))
                else:
                    messages.append(str(boss))
        
        # 處理 Small Boss - 1格內的優先排最上
        if small_bosses:
            if big_bosses:  # 如果有Big Boss，添加分隔線
                messages.append("")
            messages.append("=== SMALL BOSS ===")
            
            # 計算每個Small Boss到Bunker的距離並排序
            small_boss_with_data = []
            for boss in small_bosses:
                boss_x, boss_y = int(boss.location[0]), int(boss.location[1])
                distance = max(abs(boss_x - bunker_x), abs(boss_y - bunker_y))
                small_boss_with_data.append((boss.name, distance, boss))
            
            # 排序：1格內的優先（distance <= 1），其餘按名稱再按距離
            small_boss_with_data.sort(key=lambda x: (0 if x[1] <= 1 else 1, x[0], x[1]))
            
            for name, distance, boss in small_boss_with_data:
                # 1格內的boss加醒目emoji
                if distance <= 1:
                    boss_str = str(boss)
                    # 為1格內的boss添加醒目emoji
                    boss_lines = boss_str.split('\n')
                    boss_lines[0] = f"🚨 {boss_lines[0]} 🚨"
                    messages.append('\n'.join(boss_lines))
                else:
                    messages.append(str(boss))
        
        return "\n\n".join(messages) if messages else ""
    
    def format_location_tracking_message(self, player: PlayerLocation, big_bosses: List[BossInfo], nearby_bosses: List) -> str:
        """格式化位置追蹤訊息（按距離角色排序）"""
        messages = []
        messages.append(f"📍 **角色位置追蹤** - {player.username}")
        messages.append(f"當前位置: ({player.x}, {player.y})")
        messages.append("")
        
        # 角色3格範圍內的所有boss - 1格內的優先排最上
        if nearby_bosses:
            messages.append("🎯 **角色3格範圍內的Boss**")
            
            # 計算每個nearby boss到角色的距離並排序
            nearby_with_data = []
            for boss in nearby_bosses:
                distance, direction = player.calculate_distance_to(boss['location'])
                nearby_with_data.append((boss['name'], distance, boss, direction))
            
            # 排序：1格內的優先（distance <= 1），其餘按名稱再按距離
            nearby_with_data.sort(key=lambda x: (0 if x[1] <= 1 else 1, x[0], x[1]))
            
            for name, distance, boss, direction in nearby_with_data:
                start_time = boss['start_time'].strftime('%H:%M')
                end_time = boss['end_time'].strftime('%H:%M')
                
                # 1格內的boss加醒目emoji
                if distance <= 1:
                    messages.append(f"🚨 • {boss['name']} 在 ({boss['location'][0]}, {boss['location'][1]}) - 距離: {distance}格 ({direction}) 🚨")
                    messages.append(f"🚨   時間: {start_time} - {end_time} 🚨")
                else:
                    messages.append(f"• {boss['name']} 在 ({boss['location'][0]}, {boss['location'][1]}) - 距離: {distance}格 ({direction})")
                    messages.append(f"  時間: {start_time} - {end_time}")
            messages.append("")
        
        # Big Boss距離 - 1格內的優先排最上
        if big_bosses:
            messages.append("🔴 **BIG BOSS 距離**")
            
            # 計算每個Big Boss到角色的距離並排序
            big_boss_with_data = []
            for boss in big_bosses:
                distance, direction = player.calculate_distance_to(boss.location)
                big_boss_with_data.append((boss.name, distance, boss, direction))
            
            # 排序：1格內的優先（distance <= 1），其餘按名稱再按距離
            big_boss_with_data.sort(key=lambda x: (0 if x[1] <= 1 else 1, x[0], x[1]))
            
            for name, distance, boss, direction in big_boss_with_data:
                # 1格內的boss加醒目emoji
                if distance <= 1:
                    messages.append(f"🚨 • {boss.name} 在 ({boss.location[0]}, {boss.location[1]}) - 距離: {distance}格 ({direction}) 🚨")
                else:
                    messages.append(f"• {boss.name} 在 ({boss.location[0]}, {boss.location[1]}) - 距離: {distance}格 ({direction})")
            messages.append("")
        
        # Bunker距離
        bunker_distance, bunker_direction = player.calculate_distance_to((1054, 987))
        messages.append(f"🏠 **Secronom Bunker** - 距離: {bunker_distance}格 ({bunker_direction})")
        
        if not nearby_bosses and not big_bosses:
            messages.append("\n⚠️ 目前沒有符合條件的Boss")
        
        return "\n".join(messages)
    
    def fetch_nearby_bosses(self, player_location: tuple) -> List:
        """獲取角色3格範圍內的所有boss"""
        try:
            # 生成當前時間戳作為URL參數
            timestamp = int(time.time() * 1000)
            json_url = f"https://www.dfprofiler.com/bossmap/json/?_={timestamp}"

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Accept-Language': 'en-US,en;q=0.5',
                'Referer': 'https://www.dfprofiler.com/bossmap',
                'X-Requested-With': 'XMLHttpRequest',
            }

            response = requests.get(json_url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            nearby_bosses = []
            player_x, player_y = int(player_location[0]), int(player_location[1])

            # 解析JSON數據，找出角色3格範圍內的所有boss
            for game_id, boss_data in data.items():
                if not isinstance(boss_data, dict):
                    continue

                # 檢查是否為boss事件
                if (boss_data.get('locations') and 
                    boss_data.get('special_enemy_type') and 
                    boss_data['special_enemy_type'] != '0'):

                    boss_name = boss_data['special_enemy_type']
                    start_timestamp = int(boss_data['start_time'])
                    end_timestamp = int(boss_data['end_time'])

                    start_time = datetime.fromtimestamp(start_timestamp)
                    end_time = datetime.fromtimestamp(end_timestamp)
                    current_time = datetime.now()

                    # 跳過已經結束的歷史boss
                    if end_time <= current_time:
                        continue

                    # 檢查所有位置，找出在角色3格範圍內的
                    nearby_locations = []
                    for location in boss_data['locations']:
                        boss_x, boss_y = int(location[0]), int(location[1])
                        distance = max(abs(boss_x - player_x), abs(boss_y - player_y))
                        
                        if distance <= 3:
                            nearby_locations.append(location)

                    # 為每個在範圍內的位置創建boss條目
                    if nearby_locations:
                        for i, location in enumerate(nearby_locations):
                            boss_display_name = boss_name if len(nearby_locations) == 1 else f"{boss_name} #{i+1}"
                            boss_info = {
                                'game_id': f"{game_id}_{i}",
                                'name': boss_display_name,
                                'location': tuple(location),
                                'start_time': start_time,
                                'end_time': end_time
                            }
                            nearby_bosses.append(boss_info)
                            logger.info(f"找到角色3格內boss: {boss_display_name} 在 {location}")

            return nearby_bosses

        except Exception as e:
            logger.error(f"獲取角色附近boss數據時發生錯誤: {e}")
            return []

    def location_tracking_cycle(self):
        """執行一次位置追蹤檢查"""
        logger.info("開始位置追蹤檢查...")
        
        # 獲取角色位置
        player = self.fetch_player_location()
        if not player:
            logger.error("無法獲取角色位置，跳過本次追蹤")
            return
        
        # 獲取角色3格範圍內的所有boss
        nearby_bosses = self.fetch_nearby_bosses(player.location)
        
        # 獲取所有Big Boss（用於距離計算）
        big_bosses, _ = self.fetch_boss_data()
        
        # 生成並發送訊息
        message = self.format_location_tracking_message(player, big_bosses, nearby_bosses)
        self.send_slack_notification(message, LOCATION_TRACK_CHANNEL)
        logger.info(f"已發送位置追蹤訊息到 {LOCATION_TRACK_CHANNEL}")
    
    def check_and_notify(self):
        """檢查boss並發送通知"""
        logger.info("開始檢查boss狀態...")
        
        # 獲取當前boss資料
        big_boss_data, small_boss_data = self.fetch_boss_data()
        
        if not big_boss_data and not small_boss_data:
            logger.info("沒有找到boss")
            return
        
        # 檢查是否有新的Big Boss
        new_big_bosses = []
        for boss_info in big_boss_data:
            boss_key = f"big_{boss_info.game_id}_{boss_info.start_time.timestamp()}"
            
            if boss_key not in self.current_big_bosses:
                self.current_big_bosses[boss_key] = boss_info
                new_big_bosses.append(boss_info)
                logger.info(f"檢測到新Big Boss: {boss_info.name} (遊戲ID: {boss_info.game_id}, 位置: {boss_info.location})")
        
        # 檢查是否有新的Small Boss
        new_small_bosses = []
        for boss_info in small_boss_data:
            boss_key = f"small_{boss_info.game_id}_{boss_info.start_time.timestamp()}"
            
            if boss_key not in self.current_small_bosses:
                self.current_small_bosses[boss_key] = boss_info
                new_small_bosses.append(boss_info)
                logger.info(f"檢測到新Small Boss: {boss_info.name} (遊戲ID: {boss_info.game_id}, 距離Bunker: {boss_info.distance_from_bunker})")
        
        # 發送通知（如果有任何新的boss）
        if new_big_bosses or new_small_bosses:
            message = self.format_boss_message(new_big_bosses, new_small_bosses)
            if message:
                self.send_slack_notification(message)
                logger.info(f"已發送通知: {len(new_big_bosses)} 個Big Boss, {len(new_small_bosses)} 個Small Boss")
        else:
            logger.info("沒有新boss出現")
    
    def cleanup_expired_bosses(self):
        """清理過期的boss"""
        current_time = datetime.now()
        expired_big_boss_keys = []
        expired_small_boss_keys = []
        
        # 清理過期的Big Boss
        for boss_key, boss_info in self.current_big_bosses.items():
            if current_time >= boss_info.end_time:
                expired_big_boss_keys.append(boss_key)
        
        for boss_key in expired_big_boss_keys:
            removed_boss = self.current_big_bosses.pop(boss_key)
            logger.info(f"清理過期Big Boss: {removed_boss.name} (遊戲ID: {removed_boss.game_id})")
        
        # 清理過期的Small Boss
        for boss_key, boss_info in self.current_small_bosses.items():
            if current_time >= boss_info.end_time:
                expired_small_boss_keys.append(boss_key)
        
        for boss_key in expired_small_boss_keys:
            removed_boss = self.current_small_bosses.pop(boss_key)
            logger.info(f"清理過期Small Boss: {removed_boss.name} (遊戲ID: {removed_boss.game_id})")
        
        total_expired = len(expired_big_boss_keys) + len(expired_small_boss_keys)
        if total_expired > 0:
            logger.info(f"清理了 {len(expired_big_boss_keys)} 個Big Boss, {len(expired_small_boss_keys)} 個Small Boss")
        else:
            logger.info("沒有過期的boss需要清理")
    
    def run_boss_detection(self):
        """運行Boss檢測模式"""
        logger.info("Boss檢測模式啟動")
        
        # 設置定時任務
        schedule.clear()  # 清除之前的任務
        schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(self.check_and_notify)
        schedule.every(30).minutes.do(self.cleanup_expired_bosses)  # 每30分鐘清理一次過期boss
        
        # 立即執行一次檢查
        self.check_and_notify()
        
        # 主循環
        while True:
            try:
                schedule.run_pending()
                time.sleep(1)
            except KeyboardInterrupt:
                logger.info("收到停止信號，程序退出")
                break
    
    def run_location_tracking(self):
        """運行實時追蹤模式"""
        logger.info("實時追蹤模式啟動")
        
        # 設置定時任務
        schedule.clear()  # 清除之前的任務
        schedule.every(LOCATION_CHECK_INTERVAL_MINUTES).minutes.do(self.location_tracking_cycle)
        
        # 立即執行一次追蹤
        self.location_tracking_cycle()
        
        # 主循環
        while True:
            try:
                schedule.run_pending()
                time.sleep(1)
            except KeyboardInterrupt:
                logger.info("收到停止信號，程序退出")
                break


def show_menu():
    """顯示主菜單"""
    print("\n" + "="*50)
    print("         Dead Frontier Boss 監控系統")
    print("="*50)
    print("請選擇模式:")
    print("1. Boss 偵測 (每5分鐘檢查，Small Boss範圍: Bunker 3格內)")
    print("2. 實時追蹤 (每分鐘檢查角色與Boss距離)")
    print("3. 退出")
    print("="*50)


def select_user():
    """選擇用戶"""
    print("\n可用用戶:")
    users = list(USER_ID_MAPPING.keys())
    for i, user in enumerate(users, 1):
        print(f"{i}. {user}")
    
    while True:
        try:
            choice = input(f"\n請選擇用戶 (1-{len(users)}, 直接按Enter使用默認tommy660): ").strip()
            if not choice:
                return DEFAULT_USER_ID
            
            choice_num = int(choice)
            if 1 <= choice_num <= len(users):
                selected_user = users[choice_num - 1]
                user_id = USER_ID_MAPPING[selected_user]
                print(f"已選擇用戶: {selected_user} (ID: {user_id})")
                return user_id
            else:
                print("無效選擇，請重新輸入")
        except ValueError:
            print("請輸入有效數字")


def main():
    """主程序"""
    while True:
        show_menu()
        choice = input("請輸入選擇 (1-3): ").strip()
        
        if choice == "1":
            user_id = select_user()
            monitor = BossMonitor(user_id)
            monitor.run_boss_detection()
        elif choice == "2":
            user_id = select_user()
            monitor = BossMonitor(user_id)
            monitor.run_location_tracking()
        elif choice == "3":
            print("退出程序...")
            break
        else:
            print("無效選擇，請重新輸入")


if __name__ == "__main__":
    main()
