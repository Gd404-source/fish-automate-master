import os
import time
import re
import base64
import cv2
import numpy as np
import pytesseract
import pyautogui
import logging
import socket
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

import ctypes
import win32gui
import win32con
import win32api

# 初始化 Flask 应用并配置 CORS
app = Flask(__name__)
CORS(app)

# 日志目录与配置：同时写入日志文件和控制台，支持日志轮转
if not os.path.exists("logs"):
    os.makedirs("logs")

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 使用RotatingFileHandler实现日志轮转：单个文件最大10MB，保留7个备份文件
import logging.handlers
file_handler = logging.handlers.RotatingFileHandler(
    "logs/app.log",
    maxBytes=10*1024*1024,  # 10MB
    backupCount=7,  # 保留7个备份文件
    encoding="utf-8"
)
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# 性能监控
try:
    from performance_monitor import monitor
    PERFORMANCE_MONITORING = True
except ImportError:
    PERFORMANCE_MONITORING = False
    monitor = None

@app.before_request
def log_request_info():
    """记录请求信息并监控性能"""
    if PERFORMANCE_MONITORING:
        request.start_time = time.time()
    # 减少日志输出，只在DEBUG模式下详细记录

@app.after_request
def after_request(response):
    """请求后处理：记录性能数据"""
    if PERFORMANCE_MONITORING and hasattr(request, 'start_time'):
        response_time = time.time() - request.start_time
        endpoint = f"{request.method} {request.path}"
        is_error = response.status_code >= 400
        monitor.record_request(endpoint, response_time, is_error)
    return response

def simulate_keypress(key='f7'):
    """
    模拟按下指定的键盘按键（默认 F7）
    同时在控制台打印和写入日志
    """
    message = f"Simulating pressing the '{key}' key..."
    print(message)
    logging.info("模拟按键: %s", key)
    pyautogui.press(key)
    message2 = f"Key '{key}' pressed."
    print(message2)
    logging.info("按键 '%s' 执行完毕。", key)

def ocr_extract_text(image):
    """
    对传入图像进行预处理和 OCR, 提取所有文字并去除符号
    返回：
      filtered_text: 过滤掉符号后的纯文本
      processed: 用于 OCR 的预处理灰度图
    """
    logging.info("开始 OCR 处理图像...")
    # 转成灰度
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # 提高对比度
    alpha = 2.0  # 对比度因子
    beta = 0     # 亮度因子
    processed = cv2.convertScaleAbs(gray, alpha=alpha, beta=beta)

    # OCR 配置，使用整页模式（PSM 6）更容易识别多行文本
    custom_config = r'--oem 3 --psm 6'
    raw_text = pytesseract.image_to_string(processed, config=custom_config)

    # 用正则去除所有非中文、非英文、非数字字符
    # 保留：汉字、A–Z、a–z、0–9、下划线、空白
    filtered_text = re.sub(r'[^\u4E00-\u9FFF\w\s]', '', raw_text)

    logging.info("OCR 原始结果: %s", raw_text.strip())
    logging.info("过滤后结果: %s", filtered_text.strip())

    return filtered_text.strip(), processed

def screenshot_extract_amount(rois, ld_index):
    """
    截屏一次，并对截图按照传入的 ROIs 进行 OCR 提取金额，
    将全屏截图及各 ROI 的处理结果保存并返回。
    截图文件名根据 ld_index 来命名，如 screenshot_ldplayer_1.png
    """
    folder = "screenshots"
    if not os.path.exists(folder):
        os.makedirs(folder)
    
    logging.info("开始截屏...")
    screenshot = pyautogui.screenshot()
    # 使用 ld_index 构造截图文件名
    filename = os.path.join(folder, f"screenshot_ldplayer_{ld_index}.png")
    screenshot.save(filename)
    logging.info("已保存截图到 %s", filename)
    
    screenshot_cv = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    
    roi_results = []
    for roi in rois:
        try:
            x1, y1, x2, y2 = map(int, roi)
        except Exception as e:
            logging.error("无效 ROI 格式: %s, 错误: %s", roi, str(e))
            roi_results.append({
                "amount": None,
                "roi_img": None,
                "error": "Invalid ROI format"
            })
            continue
        
        roi_img = screenshot_cv[y1:y2, x1:x2]
        if roi_img.size == 0:
            logging.error("ROI 区域为空: %s", roi)
            roi_results.append({
                "amount": None,
                "roi_img": None,
                "error": "Empty ROI"
            })
            continue
        
        amount, processed_img = ocr_extract_text(roi_img)
        _, buffer = cv2.imencode('.png', processed_img)
        roi_base64 = base64.b64encode(buffer).decode('utf-8')
        roi_results.append({
            "amount": amount,
            "roi_img": roi_base64
        })
    
    _, full_buffer = cv2.imencode('.png', screenshot_cv)
    full_b64 = base64.b64encode(full_buffer).decode('utf-8')
    
    result = {
        "full_screenshot": "full_b64",
        "roi_results": roi_results
    }
    logging.info("截屏处理完成。")
    return result

def get_screenshot():
    """
    获取截图接口：与预览类似，用于其他业务场景（例如后续处理）
    """
    ip = request.args.get('ip', '<PC2_IP>')
    try:
        response = requests.get(f'http://{ip}:5000/capture', timeout=5)
        response.raise_for_status()
        img_array = np.frombuffer(response.content, np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

        if img is None or img.size == 0:
            raise ValueError("无法解码屏幕截图图像。")

        _, buffer = cv2.imencode('.png', img)
        img_base64 = base64.b64encode(buffer).decode('utf-8')
        return jsonify({'image': img_base64})

    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'无法捕获屏幕截图: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'意外错误: {str(e)}'}), 500
    
def loop_get_text():
    
    ld_index = 1
    rois = []
    screenshot_extract_amount(rois, ld_index)


if __name__ == "__main__":
    # 启动自动清理任务
    try:
        from cleanup_utils import setup_periodic_cleanup
        setup_periodic_cleanup(log_dir="logs", screenshot_dir="screenshots", debug_dir="screenshots")
    except ImportError:
        logger.warning("清理工具模块未找到，跳过自动清理功能")
    
    print("Server is available on the following IP addresses:")
    
    # 启用多线程模式，支持并发处理请求
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
