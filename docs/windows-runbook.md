# DFBossReminder 遊戲 PC 操作手冊

這份文件是給**遊戲 PC 前的人**看的。開發機（Mac）負責改程式與跑測試，遊戲 PC 負責
跑起來、看畫面、把證據傳回來。

## 這是什麼

一個唯讀的疊加視窗，用**遊戲自己的地圖座標**告訴你附近有那些 boss：

* 你的座標來自 dfprofiler 的帳號 `gpscoords`（就是當初要你記下的 `14008279`
  那組 DF user id），跟 boss 的座標是同一套座標系；
* 半徑可以隨時改（`--radius`）；
* 開白名單模式後，只有你列出的座標出現 boss 才顯示（`--whitelist`）；
* 讀取畫面貼在遊戲客戶區上（`--presentation overlay`），或貼在螢幕上當側邊面板
  （`--presentation panel`），也可以只在主控台印（`--presentation console`）。

它**不會**注入遊戲、不會讀寫遊戲記憶體、不會送出任何鍵盤或滑鼠輸入。唯一的網路動作
是對 `dfprofiler.com` 發 `GET`。

## 一次性設定

1. 複製專案到 `C:\DFTools\DfbossReminder`（或任何路徑，`build-exe.cmd` 會自己找）。
2. 裝好 Python 與 PyInstaller（`py -m pip install pyinstaller`）。
3. 在專案目錄執行：

   ```cmd
   tools\pc\build-exe.cmd
   ```

   成功會印出 `Built C:\Users\...\Desktop\DFBossReminder.exe (… bytes, …)`。
   建置產物直接放在桌面，不要再多一次複製步驟。

4. 先做一次純文字檢查（不開視窗、不進遊戲）：

   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\pc\run-dfboss.ps1 -UserId 14008279 -Once
   ```

   應該會印出你的座標、附近 boss 的清單、以及 `within N blocks`。
   這一步證明了帳號 id、網路、與 boss 地圖解析都正常。

   **注意**：`gpscoords` 是「最後已知位置」。如果你在遊戲裡沒有移動，數字不會變；
   這不是壞掉。

## 設定界面（白名單、字級、顏色）

```powershell
tools\pc\config-gui.cmd
```

或是桌面上的 `DFBossReminderConfig.exe`。它**不需要遊戲在跑**：帳號 id、白名單、
字級、顏色、擺放位置、以及「那些 boss 算 big boss」的清單都在這裡改。按 Save 會寫入
`%USERPROFILE%\.dfbossreminder\settings.json`，overlay 下次啟動時讀取；如果某個值被
工具調整過（例如半徑填 9999 會被夾到 200），視窗會明確列出被改的欄位。

## 每次遊戲前的啟動

先把遊戲開起來，調成**視窗化或無邊框視窗**（獨佔全螢幕沒辦法顯示疊加視窗）。

**遊戲沒開的話 overlay 不會開**，會直接印出原因並以代碼 3 結束。這是刻意的：讀數是
「對運行中的遊戲」的讀數，要貼在它的客戶區上、要用它的玩家座標量距離。只想先看看資料
的話用 `--presentation console` 或 `--once`，那兩個不需要遊戲。

```powershell
# 遊戲內讀數，貼在客戶區左上角，半徑 8 格，每 20 秒更新
powershell -ExecutionPolicy Bypass -File tools\pc\run-dfboss.ps1 -Presentation overlay -Anchor top-left -Radius 8
```

或直接雙擊桌面上的 `DFBossReminder.exe`，它會用你上次存下來的設定（`--user-id`
與其他參數都會被記住，存在 `%USERPROFILE%\.dfbossreminder\settings.json`）。

遊戲中：

* **F8** 切換白名單模式（切換後會立刻存檔）。需要疊加視窗，所以只有
  `overlay` / `panel` 模式有這個鍵。
* 疊加視窗是**點擊穿透**的，不會搶焦點，也不會擋到遊戲操作。

停止：

```powershell
powershell -ExecutionPolicy Bypass -File tools\pc\stop-dfboss.ps1
```

## 白名單怎麼用

```
1055,986            只監看這一格
1055,986:2          監看這一格，以及周圍 2 格內的所有格子
1055,986:2=Bunker   同上，但在畫面上標成 Bunker
```

多筆用 `;` 分隔：

```powershell
powershell -ExecutionPolicy Bypass -File tools\pc\run-dfboss.ps1 -Whitelist "1054,987:3=Bunker;1055,986" -WhitelistMode on
```

白名單模式**不受半徑限制**：白名單上的座標不管你在多遠都會顯示——那正是「盯住一個
點」的意義。白名單打開但清單是空的時，畫面不會顯示任何 boss，並且會說明原因。

## 要傳回來的證據（已經做過一次,這是重跑的方法）

第一次的實機驗證在 2026-09-22 做完了,結果記在
`docs/verified-facts.md` 與 `docs/evidence/`。下面是重跑的方法,以及在非遊戲情境
（換解析度、換顯示縮放、換邊框模式）下要重驗什麼。

**重要**:SSH 進去的 session 是 session 0,看不到也畫不出桌面。所有需要桌面的東西
都要經 `tools/run_on_pc.sh`（它會觸發 `DFB-Interactive` 排程工作,在使用者的互動 session
裡執行）。

### 1. 確認客戶區量測正確

```powershell
# 從 Mac：
tools/run_on_pc.sh 'py -3 tools\pc\probe-window.py --list 8'
```

它會印出螢幕尺寸、**遊戲視窗的客戶區在螢幕上的座標**、以及所有可見視窗的客戶區。
要看的重點:遊戲的 `UnityWndClass` 客戶區是不是 `1280x720`,位置合理,而且
`exclusive_fullscreen` 是 False。

### 2. 記錄 overlay 畫面 + 桌面截圖

```powershell
# 從 Mac（參數：模式 錨點 秒數 "客戶區 L T W H"）
tools/run_on_pc.sh 'call tools\pc\verify-overlay.cmd overlay top-left 24 "242 134 1280 720"'
```

會產生兩個檔在 `tools\pc\evidence\`:

* `overlay.bmp` — overlay **自己畫出來的像素**（分層視窗不一定會出現在螢幕截圖裡,
  所以這是最可信的一張）;
* `…-dfboss-overlay-client.png` — 從桌面拍下來的**客戶區**畫面,用來證明它真的在螢幕上。

`run_on_pc.sh` 的輸出裡要看的是這一行:

```
overlay visible=True at (256,148)-(686,388); font=MS Gothic; anchored to the game client
```

`(256,148)` 應該等於「客戶區左上角 + 內縮 14px」。若不是,就是錨點算錯了。

### 2b. 驗證位置在 minimap 正下方

```powershell
# 從 Mac（anchors: below-minimap 是預設）
tools/run_on_pc.sh 'call tools\pc\verify-overlay.cmd overlay below-minimap 24 "242 134 1280 720"'
```

要看的重點：回報的位置右緣要等於「客戶區左 + 1060 + 215」，上緣要等於
「客戶區上 + 10 + 215 + 4」。那三個數字是量出來的 minimap 矩形（客戶區座標），
不是猜的。`overlay-run.log` 會一起印出來。

### 2b-2. 查哪個切換鍵可用

```powershell
tools/run_on_pc.sh 'py -3 tools\pc\probe-hotkeys.py'
```

白名單切換鍵是全域熱鍵,被別的程式佔用就註冊不到(而且會明確回報)。這台機器上 F8
是空的、只有 F12 被佔用。要換鍵用 `--hotkey F6`,或在設定界面改。

### 2c. 驗證設定界面開得起來

```powershell
tools/run_on_pc.sh 'py -3 tools\pc\probe-config-gui.py'
```

應該看到 `found the settings window: ... visible=True` 與
`PASS: the settings window opens, with no game required`。

### 3. 驗證點擊穿透與不搶焦點

```powershell
# 從 Mac：
tools/run_on_pc.sh 'py -3 tools\pc\probe-clickthrough.py --presentation overlay --anchor top-left --seconds 18'
```

它會自己起一個 overlay,讀回 `WS_EX_TRANSPARENT` / `WS_EX_NOACTIVATE`,在 overlay
正中央做 `WindowFromPoint`,並比較前後的前景視窗。要看到:

```
overlay ex-style: WS_EX_TRANSPARENT=True WS_EX_NOACTIVATE=True
WindowFromPoint at the overlay's centre (...) -> 'ConsoleWindowClass' ...
foreground after: ...            (跟 before 一樣)
PASS: clicks pass through to the window underneath, and focus was not taken
```

`WindowFromPoint` 若回傳 overlay 自己,就代表點擊會被吃掉——這是唯一必須由程式化的
方式抓到的回歸。

### 4. 需要人手確認的

* 在遊戲裡用滑鼠點 overlay 覆蓋的區域,遊戲要照常反應(走到那個點、開箱等)。
* 用鍵盤跟遊戲互動時,遊戲要保有鍵盤焦點。
* 換成無邊框視窗、或改顯示縮放(DPI)之後,重跑第 1、2 步。

### 已知限制

* 獨佔全螢幕無法顯示疊加視窗（會警告，不會硬畫）。
* 客戶區剛好等於整個螢幕時，工具會警告「可能是全螢幕或無邊框」，但仍會畫。
* `gpscoords` 是帳號的最後已知位置，畫面會顯示資料年齡（`updated Ns ago`），
  超過 `stale_seconds` 會變紅字。如果位置看起來很舊，先確認遊戲裡有在移動。
* overlay 的字型會自動挑一個「有中文且等寬」的字型（候選依序
  MingLiU → MS Gothic → SimSun → Microsoft JhengHei → Consolas）。
  2026-09-22 那台機器挑到 **MS Gothic**。要指定就用 `--font "字型名"`;
  若只想用 ASCII 方位（`E3N2`）可用 `--direction-style en`。
* 預設是**完全透明底**（`--opacity 0`）：只畫字，字後面有一層暗色陰影讓它在亮地面上仍
  可讀。想要深色底就把 opacity 調高（例如 `--opacity 0.86`），那時會一併畫框線。
* 視窗高度是**上限**，會跟著內容自動增減，所以底部的中文備註不會被切掉；
  真的超過上限時，最後一行會寫「（還有 N 行未顯示）」。
* 標籤（標題、備註、狀態）預設中文，`--language en` 可切英文；boss 那幾行是固定格式。
* 輸出（含 `-Once` 的記錄檔）固定用 **UTF-8**，所以抓回 Mac 或任何編輯器都讀得懂。
  注意：冷凍的 exe **不理 `PYTHONIOENCODING`**，所以編碼是在程式裡決定的，不是靠環境變數。
