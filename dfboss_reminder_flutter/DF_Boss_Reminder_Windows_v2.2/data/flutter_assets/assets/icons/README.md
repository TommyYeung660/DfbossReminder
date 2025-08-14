# App Icon 設置指引

## 所需的圖片文件

在這個資料夾中，你需要放置以下圖片文件：

### 1. 主要 App 圖示
- **檔案名稱**: `app_icon.png`
- **建議尺寸**: 1024x1024 像素
- **格式**: PNG，支援透明背景
- **用途**: 用作應用程式的主要圖示

### 2. 適應性圖示（Android 8.0+ 支援）
- **前景圖片**: `adaptive_foreground.png`
  - 尺寸: 1024x1024 像素
  - 格式: PNG，建議有透明背景
  - 用途: 圖示的主要內容，會顯示在各種背景形狀上

- **背景圖片**: `adaptive_background.png`
  - 尺寸: 1024x1024 像素
  - 格式: PNG
  - 用途: 圖示的背景，可以是純色或簡單圖案

## 設計建議

### 圖示設計原則
1. **簡潔明瞭**: 圖示應該在小尺寸下也能清晰辨識
2. **品牌一致**: 使用應用程式的主要顏色和風格
3. **適應性**: 確保在不同背景和形狀下都能良好顯示

### 顏色建議
根據你的應用主題（綠色主題），建議使用：
- 主色: #2E7D32 或 #4CAF50
- 輔助色: 白色或淺色作為對比

## 使用步驟

1. 將準備好的圖片文件放在此資料夾中
2. 確保檔案名稱正確：
   - `app_icon.png`
   - `adaptive_foreground.png`
   - `adaptive_background.png`
3. 在專案根目錄執行命令：
   ```bash
   flutter pub get
   flutter pub run flutter_launcher_icons:main
   ```
4. 重新建置應用程式：
   ```bash
   flutter build apk
   ```

## 圖片生成工具建議

如果你需要設計圖示，可以使用以下工具：
- **線上工具**: Canva, Figma, Adobe Express
- **桌面軟體**: Adobe Illustrator, GIMP, Inkscape
- **專門的圖示生成器**: Android Asset Studio

## 快速開始

如果你有一個正方形的 logo 圖片，可以：
1. 將它重新命名為 `app_icon.png`
2. 複製三份，分別命名為上述的三個檔案
3. 然後執行生成命令

這樣可以快速開始，之後再針對適應性圖示進行優化。
