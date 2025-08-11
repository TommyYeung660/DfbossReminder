@echo off
echo 開始構建Android APK...

echo 清理項目...
flutter clean

echo 獲取依賴...
flutter pub get

echo 分析代碼...
flutter analyze

echo 構建APK...
flutter build apk --release

echo 構建完成！
echo APK文件位置: build\app\outputs\flutter-apk\app-release.apk

pause
