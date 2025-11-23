#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""检查所有依赖是否已安装"""

import sys

# 需要检查的包
required_packages = {
    'flask': 'Flask',
    'flask_cors': 'flask-cors',
    'cv2': 'opencv-python',
    'numpy': 'numpy',
    'pytesseract': 'pytesseract',
    'pyautogui': 'PyAutoGUI',
    'requests': 'requests',
    'aiohttp': 'aiohttp',
    'websocket': 'websocket-client',
    'PIL': 'Pillow',
    'psutil': 'psutil',  # 性能监控需要
}

# Windows特定
try:
    import win32gui
    win32_available = True
except ImportError:
    win32_available = False

print("=" * 50)
print("检查Python依赖包...")
print("=" * 50)

missing_packages = []
installed_packages = []

for module_name, package_name in required_packages.items():
    try:
        __import__(module_name)
        print(f"✅ {package_name:20s} - 已安装")
        installed_packages.append(package_name)
    except ImportError:
        print(f"❌ {package_name:20s} - 未安装")
        missing_packages.append(package_name)

print("\n" + "=" * 50)
print("Windows系统包检查...")
print("=" * 50)

if sys.platform == 'win32':
    if win32_available:
        print("✅ pywin32 - 已安装")
    else:
        print("❌ pywin32 - 未安装")
        missing_packages.append('pywin32')
else:
    print("ℹ️  非Windows系统，跳过pywin32检查")

print("\n" + "=" * 50)
print("检查Tesseract OCR...")
print("=" * 50)

try:
    import pytesseract
    # 尝试获取Tesseract版本
    try:
        version = pytesseract.get_tesseract_version()
        print(f"✅ Tesseract OCR - 已安装 (版本: {version})")
    except Exception as e:
        print(f"⚠️  Tesseract OCR - Python包已安装，但Tesseract程序可能未正确配置")
        print(f"   错误: {str(e)}")
        print(f"   请确保Tesseract已安装并添加到系统PATH")
except ImportError:
    print("❌ Tesseract OCR - Python包未安装")

print("\n" + "=" * 50)
print("总结")
print("=" * 50)

if missing_packages:
    print(f"\n❌ 缺少 {len(missing_packages)} 个包:")
    for pkg in missing_packages:
        print(f"   - {pkg}")
    print(f"\n请运行以下命令安装:")
    print(f"   pip install {' '.join(missing_packages)}")
    sys.exit(1)
else:
    print(f"\n✅ 所有依赖包已安装！({len(installed_packages)} 个包)")
    print("\n可以开始使用系统了！")
    sys.exit(0)

