"""
公共工具函数模块
用于消除代码重复，提供共享功能
"""
import os
import socket
import logging
import cv2
import numpy as np
import pytesseract
import re
import pyautogui

# ==================== 系统相关函数 ====================

def get_pc_name():
    """获取当前计算机的名称"""
    return socket.gethostname()

def get_ip_addresses():
    """获取本机所有 IP 地址"""
    host_name = socket.gethostname()
    try:
        host_ips = socket.gethostbyname_ex(host_name)[2]
    except socket.error:
        host_ips = ['127.0.0.1']
    return host_ips

def get_client_ip():
    """
    从本机所有 IP 中选择一个符合 192.168.0.x 或 192.168.1.x 且不是 192.168.0.254 的 IP
    """
    ips = get_ip_addresses()
    for ip in ips:
        if (ip.startswith("192.168.0.") or ip.startswith("192.168.1.")) and ip != "192.168.0.254":
            return ip
    return None

def simulate_keypress(key='f7', use_logging=False):
    """
    模拟按下指定的键盘按键（默认 F7）
    参数:
        key: 按键名称
        use_logging: 是否使用日志记录
    """
    message = f"Simulating pressing the '{key}' key..."
    print(message)
    if use_logging:
        logging.info("模拟按键: %s", key)
    pyautogui.press(key)
    message2 = f"Key '{key}' pressed."
    print(message2)
    if use_logging:
        logging.info("按键 '%s' 执行完毕。", key)

# ==================== OCR相关函数 ====================

def preprocess_image_multiple_methods(image, debug_dir=None, roi_index=None):
    """
    使用多种方法预处理图像，返回多个预处理后的图像
    返回: 预处理后的图像列表 [(method_name, processed_image), ...]
    """
    processed_images = []
    
    # 转换为灰度图
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()
    
    # 方法1: 基础对比度增强
    enhanced1 = cv2.convertScaleAbs(gray, alpha=2.0, beta=0)
    processed_images.append(("enhanced_2.0", enhanced1))
    
    # 方法2: 更强的对比度增强
    enhanced2 = cv2.convertScaleAbs(gray, alpha=3.0, beta=0)
    processed_images.append(("enhanced_3.0", enhanced2))
    
    # 方法3: 自适应阈值二值化
    adaptive_thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        cv2.THRESH_BINARY, 11, 2
    )
    processed_images.append(("adaptive_thresh", adaptive_thresh))
    
    # 方法4: Otsu自动阈值二值化
    _, otsu_thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    processed_images.append(("otsu_thresh", otsu_thresh))
    
    # 方法5: 高斯模糊 + 阈值
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, blurred_thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    processed_images.append(("blurred_otsu", blurred_thresh))
    
    # 方法6: 形态学操作 - 开运算（去除小噪点）
    kernel = np.ones((2, 2), np.uint8)
    morph_open = cv2.morphologyEx(otsu_thresh, cv2.MORPH_OPEN, kernel)
    processed_images.append(("morph_open", morph_open))
    
    # 方法7: 形态学操作 - 闭运算（连接断开的字符）
    morph_close = cv2.morphologyEx(otsu_thresh, cv2.MORPH_CLOSE, kernel)
    processed_images.append(("morph_close", morph_close))
    
    # 方法8: 去噪 + 对比度增强
    denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    denoised_enhanced = cv2.convertScaleAbs(denoised, alpha=2.5, beta=0)
    processed_images.append(("denoised_enhanced", denoised_enhanced))
    
    # 方法9: 反转颜色（适用于深色背景）
    inverted = cv2.bitwise_not(enhanced1)
    processed_images.append(("inverted", inverted))
    
    # 方法10: 反转 + 自适应阈值
    inverted_adaptive = cv2.adaptiveThreshold(
        cv2.bitwise_not(gray), 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )
    processed_images.append(("inverted_adaptive", inverted_adaptive))
    
    # 方法11: 放大图像（提高分辨率）
    scale_factor = 2
    enlarged = cv2.resize(gray, None, fx=scale_factor, fy=scale_factor, interpolation=cv2.INTER_CUBIC)
    enlarged_enhanced = cv2.convertScaleAbs(enlarged, alpha=2.0, beta=0)
    processed_images.append(("enlarged_enhanced", enlarged_enhanced))
    
    # 方法12: 锐化处理
    kernel_sharpen = np.array([[-1, -1, -1],
                               [-1,  9, -1],
                               [-1, -1, -1]])
    sharpened = cv2.filter2D(enhanced1, -1, kernel_sharpen)
    processed_images.append(("sharpened", sharpened))
    
    # 保存调试图像
    if debug_dir and roi_index is not None:
        os.makedirs(debug_dir, exist_ok=True)
        for method_name, proc_img in processed_images:
            debug_path = os.path.join(debug_dir, f"roi_{roi_index}_{method_name}.png")
            cv2.imwrite(debug_path, proc_img)
    
    return processed_images

def ocr_with_multiple_configs(image):
    """
    使用多种OCR配置识别图像，返回所有识别结果
    返回: [(config_name, text, confidence), ...]
    """
    results = []
    
    # 多种PSM模式配置
    psm_configs = [
        ("psm_7", r'--oem 3 --psm 7'),  # 单行文本
        ("psm_8", r'--oem 3 --psm 8'),  # 单个单词
        ("psm_6", r'--oem 3 --psm 6'),  # 单块文本
        ("psm_13", r'--oem 3 --psm 13'),  # 原始行，无特定块
        ("psm_11", r'--oem 3 --psm 11'),  # 稀疏文本
    ]
    
    for config_name, config_str in psm_configs:
        try:
            # 获取文本和置信度
            data = pytesseract.image_to_data(image, config=config_str, output_type=pytesseract.Output.DICT)
            text = pytesseract.image_to_string(image, config=config_str).strip()
            
            # 计算平均置信度
            confidences = [int(conf) for conf in data['conf'] if int(conf) > 0]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0
            
            results.append((config_name, text, avg_confidence))
        except Exception as e:
            logging.warning(f"OCR配置 {config_name} 失败: {str(e)}")
            continue
    
    return results

def extract_amount_from_text(text):
    """
    从文本中提取金额数字，支持多种格式
    返回: 提取到的金额字符串，如果没有则返回None
    """
    if not text:
        return None
    
    # 移除常见干扰字符
    cleaned = re.sub(r'[^\d.,\s]', '', text)
    
    # 尝试多种正则表达式模式
    patterns = [
        r'\d+\.?\d*',  # 基本数字（可能带小数点）
        r'\d{1,3}(?:,\d{3})*(?:\.\d{2})?',  # 带千位分隔符的数字
        r'\d+\.\d{2}',  # 两位小数的金额
        r'\d+',  # 纯整数
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, cleaned)
        if matches:
            # 选择最长的匹配（通常更完整）
            amount = max(matches, key=len)
            # 清理金额字符串
            amount = amount.replace(',', '').strip()
            if amount:
                return amount
    
    return None

def validate_amount_format(amount):
    """
    验证金额格式是否合理
    返回: True如果格式合理，False否则
    """
    if not amount:
        return False
    
    # 检查长度（通常金额不会超过15位数字）
    digits_only = amount.replace('.', '').replace(',', '')
    if len(digits_only) > 15 or len(digits_only) == 0:
        return False
    
    # 检查格式（应该是数字，可能包含一个小数点）
    if amount.count('.') > 1:
        return False
    
    # 尝试转换为浮点数验证
    try:
        float(amount.replace(',', ''))
        return True
    except ValueError:
        return False

def validate_ocr_result(amount, amount_votes, all_results):
    """
    验证OCR结果，使用置信度和投票机制
    返回: 验证后的金额，如果验证失败返回None
    """
    if not amount:
        return None
    
    # 检查置信度
    if amount in amount_votes:
        avg_confidence = amount_votes[amount]['total_confidence'] / amount_votes[amount]['count']
        # 如果平均置信度低于50，认为不可靠
        if avg_confidence < 50:
            logging.warning(f"金额 {amount} 置信度过低: {avg_confidence:.1f}")
            return None
    
    # 检查格式
    if not validate_amount_format(amount):
        return None
    
    return amount

