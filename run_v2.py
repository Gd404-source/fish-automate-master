import os
import time
import re
import base64
import cv2
import numpy as np
import pytesseract
import pyautogui
import logging
import logging.handlers
import socket
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
import threading
from datetime import datetime

import ctypes
import win32gui
import win32con
import win32api

# 导入公共工具函数
from utils import (
    get_pc_name,
    get_client_ip,
    get_ip_addresses,
    simulate_keypress as utils_simulate_keypress,
    preprocess_image_multiple_methods,
    ocr_with_multiple_configs,
    extract_amount_from_text,
    validate_amount_format,
    validate_ocr_result
)

# 初始化 Flask 应用并配置 CORS
app = Flask(__name__)
CORS(app)

# 日志目录与配置：同时写入日志文件和控制台，支持日志轮转
if not os.path.exists("logs"):
    os.makedirs("logs")

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 使用RotatingFileHandler实现日志轮转：单个文件最大10MB，保留7个备份文件
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
    # logging.info("收到请求: %s %s, 参数: %s", request.method, request.path, dict(request.args))

@app.after_request
def after_request(response):
    """请求后处理：记录性能数据"""
    if PERFORMANCE_MONITORING and hasattr(request, 'start_time'):
        response_time = time.time() - request.start_time
        endpoint = f"{request.method} {request.path}"
        is_error = response.status_code >= 400
        monitor.record_request(endpoint, response_time, is_error)
    return response

# 系统相关函数已移至utils.py，从那里导入使用

def simulate_keypress(key='f7'):
    """
    模拟按下指定的键盘按键（默认 F7）
    同时在控制台打印和写入日志
    使用utils中的函数，但添加日志功能
    """
    utils_simulate_keypress(key, use_logging=True)

# OCR相关函数已移至utils.py，从那里导入使用

def ocr_extract_amount(image, debug_dir=None, roi_index=None):
    """
    增强版OCR金额提取函数
    使用多种预处理方法和OCR配置，通过投票机制选择最可靠的结果
    
    参数:
        image: 输入图像（BGR格式）
        debug_dir: 调试目录，如果提供则保存所有预处理结果
        roi_index: ROI索引，用于命名调试文件
    
    返回:
        amount: 提取到的金额字符串，如果失败返回None
        best_processed: 最佳预处理后的图像
    """
    logging.info("开始增强OCR处理图像...")
    
    # 1. 使用多种方法预处理图像
    processed_images = preprocess_image_multiple_methods(image, debug_dir, roi_index)
    logging.info(f"生成了 {len(processed_images)} 种预处理图像")
    
    # 2. 对每种预处理图像使用多种OCR配置识别
    all_results = []  # [(method_name, config_name, amount, confidence), ...]
    
    for method_name, proc_img in processed_images:
        ocr_results = ocr_with_multiple_configs(proc_img)
        for config_name, text, confidence in ocr_results:
            amount = extract_amount_from_text(text)
            if amount:
                all_results.append((method_name, config_name, amount, confidence, text))
                logging.info(f"方法 {method_name} + 配置 {config_name}: 识别到金额 {amount} (置信度: {confidence:.1f}, 原始文本: {text})")
    
    if not all_results:
        logging.warning("所有OCR方法都未能识别到金额")
        # 返回第一个预处理图像作为fallback
        return None, processed_images[0][1] if processed_images else image
    
    # 3. 结果验证和选择策略
    # 策略1: 统计每个金额出现的次数（投票机制）
    amount_votes = {}
    for method_name, config_name, amount, confidence, text in all_results:
        if amount not in amount_votes:
            amount_votes[amount] = {
                'count': 0,
                'total_confidence': 0,
                'methods': []
            }
        amount_votes[amount]['count'] += 1
        amount_votes[amount]['total_confidence'] += confidence
        amount_votes[amount]['methods'].append((method_name, config_name))
    
    # 策略2: 选择出现次数最多的金额
    # 如果出现次数相同，选择置信度最高的
    best_amount = None
    best_score = -1
    
    for amount, data in amount_votes.items():
        # 综合评分：出现次数 * 10 + 平均置信度
        avg_confidence = data['total_confidence'] / data['count']
        score = data['count'] * 10 + avg_confidence
        
        if score > best_score:
            best_score = score
            best_amount = amount
    
    # 策略3: 如果最佳金额只出现1次，尝试使用置信度最高的结果
    if best_amount and best_amount in amount_votes and amount_votes[best_amount]['count'] == 1 and len(all_results) > 1:
        # 找到置信度最高的结果
        best_by_confidence = max(all_results, key=lambda x: x[3])
        if best_by_confidence[3] > 60:  # 置信度阈值
            best_amount = best_by_confidence[2]
            logging.info(f"使用高置信度结果: {best_amount} (置信度: {best_by_confidence[3]:.1f})")
    
    # 策略4: 后处理验证 - 检查金额格式是否合理
    if best_amount:
        # 移除前导零（除非是小数）
        if '.' not in best_amount and best_amount.startswith('0') and len(best_amount) > 1:
            best_amount = best_amount.lstrip('0') or '0'
        
        # 验证金额格式和合理性
        best_amount = validate_ocr_result(best_amount, amount_votes, all_results)
        
        # 如果验证失败，尝试使用第二高的结果
        if not best_amount or not validate_amount_format(best_amount):
            logging.warning(f"金额 {best_amount} 验证失败，尝试使用备选结果")
            sorted_amounts = sorted(amount_votes.items(), key=lambda x: x[1]['count'] * 10 + x[1]['total_confidence'] / x[1]['count'], reverse=True)
            for amount, data in sorted_amounts[1:3]:  # 尝试前3个结果
                if validate_amount_format(amount):
                    best_amount = amount
                    logging.info(f"使用备选金额: {best_amount}")
                    break
    
    # 找到对应的最佳预处理图像
    best_processed = None
    for method_name, config_name, amount, confidence, text in all_results:
        if amount == best_amount:
            # 找到对应的预处理图像
            for m_name, proc_img in processed_images:
                if m_name == method_name:
                    best_processed = proc_img
                    break
            if best_processed is not None:
                break
    
    if best_processed is None:
        best_processed = processed_images[0][1] if processed_images else image
    
    if best_amount:
        vote_count = amount_votes[best_amount]['count'] if best_amount in amount_votes else 0
        logging.info(f"最终识别结果: {best_amount} (投票数: {vote_count})")
    else:
        logging.warning("未能识别到任何金额")
    
    return best_amount, best_processed

def screenshot_extract_amount(rois, ld_index):
    """
    截屏一次，并对截图按照传入的 ROIs 进行 OCR 提取金额，
    将全屏截图及各 ROI 的处理结果保存并返回。
    截图文件名根据 ld_index 来命名，如 screenshot_ldplayer_1.png
    """
    folder = "screenshots"
    if not os.path.exists(folder):
        os.makedirs(folder)
    
    # 创建调试目录
    debug_dir = os.path.join(folder, f"debug_ldplayer_{ld_index}")
    
    logging.info("开始截屏...")
    screenshot = pyautogui.screenshot()
    # 使用 ld_index 构造截图文件名
    filename = os.path.join(folder, f"screenshot_ldplayer_{ld_index}.png")
    screenshot.save(filename)
    logging.info("已保存截图到 %s", filename)
    
    screenshot_cv = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    
    roi_results = []
    for roi_idx, roi in enumerate(rois):
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
        
        # 保存原始ROI图像用于调试
        os.makedirs(debug_dir, exist_ok=True)
        cv2.imwrite(os.path.join(debug_dir, f"roi_{roi_idx}_original.png"), roi_img)
        
        # 使用增强OCR函数，传入调试目录和索引
        amount, processed_img = ocr_extract_amount(roi_img, debug_dir=debug_dir, roi_index=roi_idx)
        
        # 编码处理后的图像
        _, buffer = cv2.imencode('.png', processed_img)
        roi_base64 = base64.b64encode(buffer).decode('utf-8')
        
        roi_results.append({
            "amount": amount,
            "roi_img": roi_base64
        })
        
        if amount:
            logging.info(f"ROI {roi_idx} 成功识别金额: {amount}")
        else:
            logging.warning(f"ROI {roi_idx} 未能识别到金额")
    
    _, full_buffer = cv2.imencode('.png', screenshot_cv)
    full_b64 = base64.b64encode(full_buffer).decode('utf-8')
    
    result = {
        "full_screenshot": full_b64,
        "roi_results": roi_results
    }
    logging.info("截屏处理完成。")
    return result

def find_ldplayer_windows(title_keyword="O-"):
    """
    查找所有标题中包含 title_keyword 的 LDPlayer 窗口，
    并按窗口标题按字母顺序排序后返回。
    """
    def enum_handler(hwnd, result_list):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title_keyword.lower() in title.lower():
                result_list.append((hwnd, title))
    windows = []
    win32gui.EnumWindows(enum_handler, windows)
    sorted_windows = sorted(windows, key=lambda x: x[1])
    print(sorted_windows)
    return sorted_windows

def activate_window(hwnd):
    """
    还原并激活指定窗口：
      1. 使用 AllowSetForegroundWindow 允许所有进程设置前台窗口；
      2. 尝试将目标窗口置前；
      3. 如果失败，模拟一次用户输入后重新尝试。
    """
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    ctypes.windll.user32.AllowSetForegroundWindow(-1)
    
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception as e:
        print("第一次 SetForegroundWindow 错误:", e)
        win32api.keybd_event(0, 0, 0, 0)
        win32api.keybd_event(0, 0, win32con.KEYEVENTF_KEYUP, 0)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception as e2:
            print("第二次 SetForegroundWindow 错误:", e2)
    time.sleep(0.5)

def press_f11():
    """
    使用 keybd_event 模拟 F11 按键操作。
    """
    win32api.keybd_event(0x7A, 0, 0, 0)  # F11 key down
    time.sleep(0.1)
    win32api.keybd_event(0x7A, 0, win32con.KEYEVENTF_KEYUP, 0)  # F11 key up

# 定义路由

@app.route('/run', methods=['POST'])
def run_script():
    """
    从请求中获取按键参数，并触发按键模拟
    返回确认信息，确保主服务器知道指令已接收并执行
    """
    data = request.get_json() or {}
    key = data.get("key", "f7")
    
    try:
        # 验证按键参数
        if not key or not isinstance(key, str):
            return jsonify({
                "status": "error",
                "message": "Invalid key parameter",
                "timestamp": time.time()
            }), 400
        
        # 执行按键
        simulate_keypress(key)
        
        # 返回确认信息
        return jsonify({
            "status": "success",
            "message": f"Key '{key}' pressed successfully",
            "timestamp": time.time(),
            "pc_name": get_pc_name(),
            "ip": get_client_ip()
        }), 200
    except Exception as e:
        logging.error(f"执行按键失败: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e),
            "timestamp": time.time(),
            "pc_name": get_pc_name()
        }), 500

@app.route('/test', methods=['GET'])
def test_connection():
    """
    用于测试连接的接口，只返回连接成功的响应
    """
    return "Connected", 200

@app.route('/health', methods=['GET'])
def health_check():
    """
    健康检查端点，返回系统状态
    """
    health_status = {
        'status': 'healthy',
        'timestamp': time.time(),
        'pc_name': get_pc_name(),
        'ip': get_client_ip()
    }
    
    if PERFORMANCE_MONITORING:
        health_status['performance'] = monitor.get_stats()
        health_status['system'] = monitor.get_system_info()
    
    return jsonify(health_status), 200

@app.route('/run_extract_amount', methods=['POST'])
def run_extract_amount():
    """
    接收到 /run_extract_amount 请求后：
      1. 根据请求中的 ROIs 参数进行截屏及 OCR 处理，
      2. 对每个 LDPlayer 窗口进行激活、F11 最大化、截屏，
         并将截图结果返回给前端。
    """
    data = request.get_json() or {}
    rois = data.get("rois", [])
    
    # 验证ROIs参数
    if not rois or not isinstance(rois, list):
        return jsonify({
            "status": "error",
            "message": "Invalid rois parameter"
        }), 400
    
    try:
        ldplayer_windows = find_ldplayer_windows("O-")
        
        if not ldplayer_windows:
            return jsonify({
                "status": "error",
                "message": "No LDPlayer windows found"
            }), 404

        screenshots_data = []  # 用于保存每个 LDPlayer 的截图结果

        for idx, (hwnd, title) in enumerate(ldplayer_windows, start=1):
            try:
                activate_window(hwnd)
                time.sleep(1)
                press_f11()
                # 调用时传入当前窗口的序号，用以命名截图
                roi_results = screenshot_extract_amount(rois, idx)
                time.sleep(1)
                press_f11()  # 取消最大化状态

                screenshots_data.append({
                    "iteration": idx,
                    "full_screenshot": "",
                    "window_title": title,
                    "roi_results": roi_results
                })
            except Exception as e:
                logging.error(f"处理窗口 {idx} ({title}) 时出错: {str(e)}", exc_info=True)
                screenshots_data.append({
                    "iteration": idx,
                    "full_screenshot": "",
                    "window_title": title,
                    "error": str(e),
                    "roi_results": []
                })

        return jsonify({"status": "ok", "screenshots": screenshots_data})
    except Exception as e:
        logging.error(f"/run_extract_amount 处理失败: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/capture', methods=['GET'])
def capture():
    """
    单次截屏接口：直接捕获当前屏幕，并返回 base64 编码的 PNG 图像，
    供前端预览截图使用。
    """
    try:
        screenshot = pyautogui.screenshot()
        screenshot_cv = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        _, buffer = cv2.imencode('.png', screenshot_cv)
        img_base64 = base64.b64encode(buffer).decode('utf-8')
        return jsonify({'image': img_base64})
    except Exception as e:
        logging.error("/capture 截屏失败: %s", str(e), exc_info=True)
        return jsonify({'error': f'截屏失败: {str(e)}'}), 500

# 创建全局Session用于连接池复用，减少连接开销
heartbeat_session = requests.Session()
heartbeat_session.headers.update({
    'Connection': 'keep-alive',
    'Keep-Alive': 'timeout=30, max=100'
})

def periodic_send_ip():
    """
    智能心跳机制：错峰发送 + 连接池复用 + 动态间隔调整
    1. 根据IP地址计算偏移时间，避免所有客户端同时发送
    2. 使用连接池复用TCP连接，减少连接建立时间
    3. 根据服务器响应时间动态调整心跳间隔
    """
    # 计算错峰偏移：根据IP地址最后一段计算0-4秒的偏移
    client_ip = get_client_ip()
    if client_ip:
        try:
            ip_last_octet = int(client_ip.split('.')[-1])
            offset = (ip_last_octet % 5)  # 0-4秒的偏移
        except:
            offset = 0
    else:
        offset = 0
    
    # 心跳间隔参数
    base_interval = 3  # 基础间隔3秒
    min_interval = 1   # 最小间隔1秒
    max_interval = 10  # 最大间隔10秒
    current_interval = base_interval + offset  # 初始间隔 = 基础间隔 + 偏移
    
    consecutive_success = 0
    consecutive_failures = 0
    
    while True:
        client_ip = get_client_ip()
        pc_name = get_pc_name()
        
        if client_ip:
            try:
                start_time = time.time()
                
                # 注册IP（使用连接池）
                url = "http://192.168.0.254:5000/api/ips"
                payload = {"ip": client_ip, "pc_name": pc_name}
                response = heartbeat_session.post(url, json=payload, timeout=2)
                
                elapsed = time.time() - start_time
                
                if response.status_code == 200:
                    # 发送心跳（使用连接池）
                    try:
                        heartbeat_url = "http://192.168.0.254:5000/api/heartbeat"
                        heartbeat_payload = {"ip": client_ip, "pc_name": pc_name}
                        heartbeat_session.post(heartbeat_url, json=heartbeat_payload, timeout=1)
                    except:
                        pass  # 心跳失败不影响主流程
                    
                    consecutive_success += 1
                    consecutive_failures = 0
                    
                    # 智能调整间隔：根据响应时间动态调整
                    if elapsed < 0.1 and consecutive_success > 5:
                        # 响应快且连续成功，可以缩短间隔（但不超过最小间隔）
                        current_interval = max(min_interval, current_interval - 0.2)
                    elif elapsed > 0.5:
                        # 响应慢，延长间隔
                        current_interval = min(max_interval, current_interval + 0.5)
                    else:
                        # 正常响应，保持当前间隔
                        pass
                    
                    # 只在成功时打印，减少输出
                    if consecutive_success % 10 == 0:  # 每10次成功打印一次
                        print("成功发送IP和PC名称:{} - {} at {}".format(
                            client_ip, pc_name, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
                else:
                    consecutive_failures += 1
                    consecutive_success = 0
                    current_interval = min(max_interval, base_interval + offset + consecutive_failures)
                    print("\033[91m错误:发送IP到主机失败,状态码:{}\033[0m".format(response.status_code))
                    
            except Exception as e:
                consecutive_failures += 1
                consecutive_success = 0
                current_interval = min(max_interval, base_interval + offset + consecutive_failures * 0.5)
                print("\033[91m错误:发送IP到主机失败:{} at {}.\033[0m".format(
                    e, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        else:
            consecutive_failures += 1
            consecutive_success = 0
            current_interval = min(max_interval, base_interval + offset + consecutive_failures * 0.5)
            print("\033[91m错误:未找到符合条件的本机 IP at {}.\033[0m".format(
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        
        # 使用动态调整的间隔
        time.sleep(current_interval)


if __name__ == "__main__":
    # 导入清理工具
    try:
        from cleanup_utils import start_cleanup_thread
        # 启动自动清理任务（每6小时清理一次）
        start_cleanup_thread(interval_hours=6)
    except ImportError:
        print("警告: 清理工具模块未找到，跳过自动清理功能")
    
    # 尝试自动发送本机 IP 到主机服务器
    # 启动后台线程定时发送 IP 和 PC 名称
    threading.Thread(target=periodic_send_ip, daemon=True).start()
    
    print("Starting Flask server. Switch to the target application if needed.")
    
    ips = get_ip_addresses()
    print("Server is available on the following IP addresses:")
    for ip in ips:
        print(f" - {ip}:5000")
    
    # 启用多线程模式，支持并发处理心跳和指令请求
    app.run(host="0.0.0.0", port=5000, threaded=True)
