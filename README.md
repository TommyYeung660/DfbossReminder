# Dead Frontier Boss Reminder

一個用於監控 Dead Frontier 遊戲中 boss 出現狀態並發送 Slack 通知的 Python 程序。

## 功能特點

- 每5分鐘自動檢查 https://www.dfprofiler.com/bossmap
- 監控 I1、I2、I3 插槽的 boss 狀態
- 當發現新的 boss 時發送 Slack 通知
- 自動清理過期的 boss 記錄（3小時後）
- 避免重複通知同一個 boss

## 安裝和設置

### 前置要求

- Python 3.11+
- uv 包管理器

### 安裝步驟

1. 克隆或下載此專案到本地
2. 在專案目錄中運行：
   ```bash
   uv sync
   ```

### 配置

在 `config.py` 文件中已預設了 Slack 配置，如需修改請編輯以下變數：

- `SLACK_WEBHOOK_URL`: Slack Webhook URL
- `SLACK_CHANNEL`: 目標頻道
- `SLACK_USERNAME`: 機器人用戶名
- `SLACK_ICON_EMOJI`: 機器人圖示

## 使用方法

### 測試系統

運行測試腳本以驗證所有功能正常：

```bash
uv run test_boss_monitor.py
```

### 啟動監控程序

```bash
uv run boss_monitor.py
```

程序將會：
1. 立即執行一次檢查
2. 每5分鐘自動檢查 boss 狀態
3. 每30分鐘清理過期的 boss 記錄
4. 持續運行直到手動停止 (Ctrl+C)

## 通知格式

### 單個 Boss
```
Boss: I1, Devil Hound
Start time: 13:00
End time: 16:00
```

### 多個 Boss
```
Boss: I1, Devil Hound
Start time: 13:00
End time: 16:00

Boss: I2, Volatile Leaper
Start time: 14:30
End time: 17:30

Boss: I1, Devil Hound | I2, Volatile Leaper
Start time: 13:00 | 14:30
End time: 16:00 | 17:30
```

## 日誌

程序會在控制台輸出詳細的日誌信息，包括：
- Boss 檢查狀態
- 發現的新 boss
- Slack 通知狀態
- 錯誤信息

## 故障排除

### 常見問題

1. **無法連接到網站**: 檢查網絡連接和防火牆設置
2. **Slack 通知失敗**: 驗證 Webhook URL 和頻道配置
3. **找不到 boss 數據**: 檢查網站結構是否發生變化

### 調試

啟用詳細日誌以獲取更多診斷信息。程序已配置為 INFO 級別的日誌輸出。

## 開發

### 文件結構

- `boss_monitor.py`: 主要的監控程序
- `config.py`: 配置文件
- `test_boss_monitor.py`: 測試腳本
- `pyproject.toml`: uv 專案配置
- `README.md`: 說明文檔

### 依賴套件

- `requests`: HTTP 請求
- `beautifulsoup4`: HTML 解析
- `schedule`: 定時任務調度
