@echo off
echo 開始構建Windows EXE...

echo 清理項目...
flutter clean

echo 獲取依賴...
flutter pub get

echo 分析代碼...
flutter analyze

echo 構建Windows應用...
flutter build windows --release

echo 構建完成！
echo EXE文件位置: build\windows\runner\Release\

pause
