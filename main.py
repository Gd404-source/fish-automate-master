from flask import Flask, render_template, request, jsonify
import requests
import cv2
import pytesseract
import numpy as np
import base64
import json
import os
import re
import time
import logging

# 导入公共工具函数
from utils import (
    preprocess_image_multiple_methods,
    ocr_with_multiple_configs,
    extract_amount_from_text
)

app = Flask(__name__)

# 配置 Tesseract（请确保系统中已安装 Tesseract OCR，并调整路径）
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

@app.route('/preview_screenshot', methods=['GET'])
def preview_screenshot():
    """
    预览截图接口：从指定 IP(或 PC2)获取屏幕截图,并返回 base64 编码的 PNG 图像
    前端调用该接口用于预览截图以及验证 ROI 位置设置
    """
    ip = request.args.get('ip', '<PC2_IP>')
    try:
        # 调用 PC2 上的 capture 接口获取截图（返回 JSON 数据）
        response = requests.get(f'http://{ip}:5000/capture', timeout=5)
        response.raise_for_status()
        data = response.json()
        img_base64 = data.get('image', '')
        if not img_base64:
            raise ValueError("没有获取到截图数据。")

        # 将 base64 解码为二进制数据，再转换为 OpenCV 格式
        img_data = base64.b64decode(img_base64)
        img_array = np.frombuffer(img_data, np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

        if img is None or img.size == 0:
            raise ValueError("无法解码屏幕截图图像。")

        # 如有需要，可对图像做处理（例如缩放）
        # 重新编码为 PNG 并转换为 base64 后返回前端
        _, buffer = cv2.imencode('.png', img)
        img_base64 = base64.b64encode(buffer).decode('utf-8')
        return jsonify({'image': img_base64})

    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'无法捕获屏幕截图: {str(e)}'}), 500
    except Exception as e:
        return jsonify({'error': f'意外错误: {str(e)}'}), 500


@app.route('/get_screenshot', methods=['GET'])
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

# OCR相关函数已移至utils.py，从那里导入使用

def ocr_extract_amount_enhanced(image, debug_dir=None, roi_index=None):
    """增强版OCR金额提取函数"""
    logging.info("开始增强OCR处理图像...")
    processed_images = preprocess_image_multiple_methods(image, debug_dir, roi_index)
    all_results = []
    
    for method_name, proc_img in processed_images:
        ocr_results = ocr_with_multiple_configs(proc_img)
        for config_name, text, confidence in ocr_results:
            amount = extract_amount_from_text(text)
            if amount:
                all_results.append((method_name, config_name, amount, confidence, text))
                logging.info(f"方法 {method_name} + 配置 {config_name}: 识别到金额 {amount} (置信度: {confidence:.1f})")
    
    if not all_results:
        logging.warning("所有OCR方法都未能识别到金额")
        return None, processed_images[0][1] if processed_images else image
    
    # 投票机制选择最佳结果
    amount_votes = {}
    for method_name, config_name, amount, confidence, text in all_results:
        if amount not in amount_votes:
            amount_votes[amount] = {'count': 0, 'total_confidence': 0}
        amount_votes[amount]['count'] += 1
        amount_votes[amount]['total_confidence'] += confidence
    
    best_amount = None
    best_score = -1
    for amount, data in amount_votes.items():
        avg_confidence = data['total_confidence'] / data['count']
        score = data['count'] * 10 + avg_confidence
        if score > best_score:
            best_score = score
            best_amount = amount
    
    # 找到对应的最佳预处理图像
    best_processed = None
    for method_name, config_name, amount, confidence, text in all_results:
        if amount == best_amount:
            for m_name, proc_img in processed_images:
                if m_name == method_name:
                    best_processed = proc_img
                    break
            if best_processed is not None:
                break
    
    if best_processed is None:
        best_processed = processed_images[0][1] if processed_images else image
    
    logging.info(f"最终识别结果: {best_amount}")
    return best_amount, best_processed

@app.route('/get_balances', methods=['GET'])
def get_balances():
    """
    根据前端传入的 ROI 坐标，获取截图后对每个 ROI 进行 OCR 识别，
    提取金额数字，并将处理后的 ROI 图像（base64 编码）和识别到的余额返回给前端
    """
    ip = request.args.get('ip', '<PC2_IP>')
    try:
        response = requests.get(f'http://{ip}:5000/capture', timeout=5)
        response.raise_for_status()
        img_array = np.frombuffer(response.content, np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)

        if img is None or img.size == 0:
            raise ValueError("无法解码屏幕截图图像。")

        rois_json = request.args.get('rois', '[]')
        rois = json.loads(rois_json) if rois_json else []
        print(f"Received rois from frontend: {rois}")

        balances = []
        roi_imgs = []
        debug_dir = 'debug'
        
        for i, roi in enumerate(rois):
            x1, y1, x2, y2 = map(int, roi)
            print(f"Processing ROI {i}: ({x1}, {y1}, {x2}, {y2})")
            if x1 < 0 or y1 < 0 or x2 > img.shape[1] or y2 > img.shape[0] or x1 >= x2 or y1 >= y2:
                print(f"Skipping invalid ROI {i}: {roi}")
                continue
            roi_img = img[y1:y2, x1:x2]
            if roi_img.size == 0:
                print(f"ROI image is empty: {roi}")
                continue

            # 使用增强OCR函数
            amount, processed_img = ocr_extract_amount_enhanced(roi_img, debug_dir=debug_dir, roi_index=i)
            
            if amount:
                print(f"ROI {i} 检测到的余额: {amount}")
                balances.append(amount)
            else:
                print(f"ROI {i} 中未检测到金额")

            # 将处理后的图像编码为 base64 传回前端显示
            _, roi_buffer = cv2.imencode('.png', processed_img)
            roi_base64 = base64.b64encode(roi_buffer).decode('utf-8')
            roi_imgs.append(roi_base64)

        if not balances:
            print("未检测到余额。请检查 ROI 坐标、图像质量或 OCR 输出。")

        with open('processing.txt', 'w', encoding='utf-8') as f:
            for balance in balances:
                f.write(f"{balance}\n")

        response_data = {
            'balances': balances,
            'roi_imgs': roi_imgs,
            'timestamp': int(time.time() * 1000)  # 当前时间戳（毫秒）
        }
        return jsonify(response_data)

    except requests.exceptions.RequestException as e:
        return jsonify({'error': f'无法捕获屏幕截图: {str(e)}'}), 500
    except ValueError as e:
        return jsonify({'error': str(e)}), 500
    except Exception as e:
        return jsonify({'error': f'意外错误: {str(e)}'}), 500

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    # 启用多线程模式，提高性能
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)
