import sys
import json
import time
import os
import csv
import re
import datetime
import tempfile
import shutil
from datetime import datetime
from PIL import Image, EpsImagePlugin
from PIL.ExifTags import TAGS
import pandas as pd
import cv2
from pathlib import Path
import google.generativeai as genai
import ffmpeg
import subprocess
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                           QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox, QProgressBar,
                           QFileDialog, QGridLayout, QMessageBox)
from PyQt5.QtCore import Qt, QThreadPool, QRunnable, pyqtSignal, QObject
from PyQt5.QtGui import QIcon, QFont
from threading import Lock

# Define available Gemini models
GEMINI_MODELS = [
    "gemini-2.0-flash", "gemini-2.5-pro-exp-03-25", "gemini-2.0-pro",
    "gemini-2.0-flash-lite", "gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.5-flash-8b"
]

# Category mapping for Adobe Stock
CATEGORY_MAP = {
    "Animals": "1",
    "Architecture": "2",
    "Backgrounds/Textures": "3",
    "Beauty/Fashion": "4",
    "Business": "5",
    "Food & Drink": "6",
    "Healthcare/Medical": "7",
    "Holidays": "8",
    "Industrial": "9",
    "Interiors": "10",
    "Miscellaneous": "11",
    "Nature": "12",
    "Objects": "13",
    "Parks/Outdoor": "14",
    "People": "15",
    "Religion": "16",
    "Science": "17",
    "Signs/Symbols": "18",
    "Sports/Recreation": "19",
    "Technology": "20",
    "The Arts": "21",
    "Transportation": "22",
    "Travel": "23",
    "Vectors": "24"
}

class WorkerSignals(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    progress = pyqtSignal(int)
    done = pyqtSignal(int)

class FileProcessor(QRunnable):
    def __init__(self, index, total, filename, input_path, output_path, api_key, model,
                 max_title, max_keywords, custom_keywords, delay, lock, csv_path, stop_flag_func):
        super().__init__()
        self.index = index
        self.total = total
        self.filename = filename
        self.input_path = input_path
        self.output_path = output_path
        self.api_key = api_key
        self.model = model
        self.max_title = max_title
        self.max_keywords = max_keywords
        self.custom_keywords = custom_keywords
        self.delay = delay
        self.lock = lock
        self.csv_path = csv_path
        self.stop_flag_func = stop_flag_func
        self.signals = WorkerSignals()

    def extract(self, label, result):
        pattern = rf"{label}\s*(.*)"
        match = re.search(pattern, result)
        return match.group(1).strip() if match else ""

    def describe_image(self, image_path):
        try:
            genai.configure(api_key=self.api_key)
            g_model = genai.GenerativeModel(self.model)

            with open(image_path, "rb") as f:
                image_data = f.read()

            prompt_parts = [
                f"""Describe this image with the following format:
Title: Describe the image in clear, detailed terms, focusing on the main subject, setting, and defining features. Avoid general themes or vague labels. Avoid assumptions or inferred meanings—only describe visible, tangible elements. Do not start with 'This image contains...'. Keep the response informative but concise, Stay under {self.max_title} characters.
Keywords: A comma-separated list of {self.max_keywords} relevant single-word keywords. Avoid copyrighted words."""
            ]
            if self.custom_keywords:
                prompt_parts.append(f"Ensure these keywords are included in the list: {self.custom_keywords}.")
            
            prompt_parts.append(f"""Category: The most relevant category from the following list: {', '.join(CATEGORY_MAP.keys())}.
Do not include anything except the exact formatted result.""")

            prompt = "\n".join(prompt_parts)

            response = g_model.generate_content([
                {"inline_data": {"mime_type": "image/png", "data": image_data}},
                prompt
            ])
            result = response.text.strip()
            return self.extract("Title:", result), self.extract("Keywords:", result), self.extract("Category:", result)
        except Exception as e:
            print(f"[GEMINI ERROR] {e}")
            return "", "", ""

    def run(self):
        if self.stop_flag_func():
            self.signals.done.emit(0)
            return

        image_path = os.path.join(self.input_path, self.filename)
        ext = os.path.splitext(image_path)[1].lower()
        temp_dir = os.path.join(self.output_path, "__temp")
        os.makedirs(temp_dir, exist_ok=True)

        original_image_path = image_path

        try:
            if ext in [".mp4", ".mov"]:
                cap = cv2.VideoCapture(image_path)
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                middle_frame = frame_count // 2
                cap.set(cv2.CAP_PROP_POS_FRAMES, middle_frame)
                success, frame = cap.read()
                cap.release()
                if success:
                    tmp_img = os.path.join(temp_dir, f"thumb_{self.index}.jpg")
                    Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).save(tmp_img)
                    image_path = tmp_img
                else:
                    print(f"[VIDEO ERROR] Could not read frame from {self.filename}")
                    error_folder = os.path.join(self.output_path, "Error")
                    os.makedirs(error_folder, exist_ok=True)
                    shutil.move(original_image_path, os.path.join(error_folder, self.filename))
                    self.signals.done.emit(1)
                    return

            elif ext == ".eps":
                gs_local = os.path.join(os.path.dirname(sys.argv[0]), "gswin64c.exe")
                os.environ["GHOSTSCRIPT_PATH"] = gs_local
                EpsImagePlugin.gs_windows_binary = gs_local
                png_path = os.path.join(temp_dir, f"eps_{self.index}.png")
                try:
                    Image.open(image_path).save(png_path, "PNG")
                    image_path = png_path
                except Exception as e:
                    print(f"[EPS ERROR] {self.filename}: {e}")
                    error_folder = os.path.join(self.output_path, "Error")
                    os.makedirs(error_folder, exist_ok=True)
                    shutil.move(original_image_path, os.path.join(error_folder, self.filename))
                    self.signals.done.emit(1)
                    return

            if ext in [".jpg", ".jpeg", ".png"]:
                img = Image.open(image_path).convert("RGB")
                img.thumbnail((1024, 1024))
                resized_path = os.path.join(temp_dir, f"resize_{self.index}.jpg")
                img.save(resized_path, "JPEG", quality=85)
                image_path = resized_path

            title, keyword_text, category_text = self.describe_image(image_path)

            if not title or not keyword_text or not category_text:
                print(f"[ERROR] Empty metadata for {self.filename}, moving to Error folder.")
                error_folder = os.path.join(self.output_path, "Error")
                os.makedirs(error_folder, exist_ok=True)
                shutil.move(original_image_path, os.path.join(error_folder, self.filename))
                self.signals.done.emit(1)
                return

            keywords = [k.strip() for k in re.split(r"[\s,;]+", keyword_text) if len(k.strip().split()) == 1]
            
            if self.custom_keywords:
                custom_kw_list = [k.strip() for k in re.split(r"[\s,;]+", self.custom_keywords) if k.strip()]
                combined_keywords = []
                seen_keywords = set()
                for kw in custom_kw_list:
                    if kw.lower() not in seen_keywords:
                        combined_keywords.append(kw)
                        seen_keywords.add(kw.lower())
                for kw in keywords:
                    if kw.lower() not in seen_keywords:
                        combined_keywords.append(kw)
                        seen_keywords.add(kw.lower())
                keywords = combined_keywords
            
            keywords = sorted(set(keywords), key=lambda x: keyword_text.lower().find(x.lower()))[:self.max_keywords]
            keywords = ", ".join(keywords)

            category_id = ""
            for cat, cid in CATEGORY_MAP.items():
                if cat.lower() in category_text.lower():
                    category_id = cid
                    break

            date_prefix = datetime.now().strftime("%Y%m%d")
            safe_title = re.sub(r'[^\w\s]', '', title)
            safe_title = "_".join(safe_title.split())[:self.max_title] or "untitled"
            new_filename = f"{date_prefix}_{safe_title}{os.path.splitext(self.filename)[1]}"

            counter = 1
            while os.path.exists(os.path.join(self.output_path, new_filename)):
                new_filename = f"{date_prefix}_{safe_title}_{counter}{os.path.splitext(self.filename)[1]}"
                counter += 1

            final_path = os.path.join(self.output_path, new_filename)

            shutil.move(original_image_path, final_path)

            with self.lock:
                with open(self.csv_path, mode="a", newline="", encoding="utf-8") as file:
                    writer = csv.writer(file)
                    if file.tell() == 0:
                        writer.writerow(["Filename", "Title", "Keywords", "Category", "Releases"])
                    clean_title = re.sub(r'[^\w\s]', '', title)
                    writer.writerow([new_filename, clean_title, keywords, category_id, ""])

        except Exception as e:
            print(f"[ERROR] Failed to process {self.filename}: {e}")
            error_folder = os.path.join(self.output_path, "Error")
            os.makedirs(error_folder, exist_ok=True)
            if os.path.exists(original_image_path):
                shutil.move(original_image_path, os.path.join(error_folder, self.filename))
        finally:
            if os.path.exists(image_path) and image_path.startswith(temp_dir):
                os.remove(image_path)
            
            self.signals.done.emit(1)

            if self.delay > 0:
                time.sleep(self.delay)

class MetadataApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.thread_pool = QThreadPool()
        self.processors = []
        self.drag_position = None
        self.csv_lock = Lock()
        self.stop_flag = False
        self.initUI()
        self.load_config()

    def initUI(self):
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setFixedSize(800, 600)
        
        # Main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Add title bar
        title_bar = TitleBar(self)
        layout.addWidget(title_bar)
        
        # API Key section
        api_layout = QHBoxLayout()
        api_label = QLabel("API Key:")
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setPlaceholderText("Enter your Gemini API key")
        
        # Toggle button with icon
        self.toggle_visibility = QPushButton()
        self.toggle_visibility.setFixedWidth(40)
        self.toggle_visibility.setCheckable(True)
        self.toggle_visibility.setStyleSheet("""
            QPushButton {
                border: none;
                background-color: #1F4040;
                border-radius: 4px;
                padding: 5px;
            }
            QPushButton:checked {
                background-color: #2F5050;
            }
        """)
        self.toggle_visibility.setText("👁️")
        self.toggle_visibility.clicked.connect(self.toggle_api_key_visibility)
        
        save_config = QPushButton("Save Config")
        save_config.clicked.connect(self.save_config)
        
        api_layout.addWidget(api_label)
        api_layout.addWidget(self.api_key_input)
        api_layout.addWidget(self.toggle_visibility)
        api_layout.addWidget(save_config)
        layout.addLayout(api_layout)
        
        # Model selection
        model_layout = QHBoxLayout()
        model_label = QLabel("Model:")
        self.model_combo = QComboBox()
        for model in GEMINI_MODELS:
            self.model_combo.addItem(model)
        model_layout.addWidget(model_label)
        model_layout.addWidget(self.model_combo)
        layout.addLayout(model_layout)
        
        # Custom Keywords
        custom_keywords_layout = QHBoxLayout()
        custom_keywords_label = QLabel("Custom Keywords:")
        self.custom_keywords_input = QLineEdit()
        self.custom_keywords_input.setPlaceholderText("Enter custom keywords separated by comma")
        custom_keywords_layout.addWidget(custom_keywords_label)
        custom_keywords_layout.addWidget(self.custom_keywords_input)
        layout.addLayout(custom_keywords_layout)
        
        # Input/Output paths
        for path_type in ["Input", "Output"]:
            path_layout = QHBoxLayout()
            path_label = QLabel(f"{path_type}:")
            path_input = QLineEdit()
            browse_btn = QPushButton("Browse")
            
            if path_type == "Input":
                self.input_path_input = path_input
                browse_btn.clicked.connect(self.browse_input)
            else:
                self.output_path_input = path_input
                browse_btn.clicked.connect(self.browse_output)
            
            path_layout.addWidget(path_label)
            path_layout.addWidget(path_input)
            path_layout.addWidget(browse_btn)
            layout.addLayout(path_layout)
        
        # Processing parameters
        params_grid = QGridLayout()
        
        # Max Title Length
        self.title_length_spin = QSpinBox()
        self.title_length_spin.setRange(1, 999)
        self.title_length_spin.setValue(120)
        params_grid.addWidget(QLabel("Max Title Length:"), 0, 0)
        params_grid.addWidget(self.title_length_spin, 0, 1)
        
        # Max Keywords
        self.max_keywords_spin = QSpinBox()
        self.max_keywords_spin.setRange(1, 999)
        self.max_keywords_spin.setValue(49)
        params_grid.addWidget(QLabel("Max Keywords:"), 0, 2)
        params_grid.addWidget(self.max_keywords_spin, 0, 3)
        
        # Workers
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 10)
        self.workers_spin.setValue(1)
        params_grid.addWidget(QLabel("Workers:"), 1, 0)
        params_grid.addWidget(self.workers_spin, 1, 1)
        
        # Delay
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(1, 60)
        self.delay_spin.setValue(6)
        params_grid.addWidget(QLabel("Delay (s):"), 1, 2)
        params_grid.addWidget(self.delay_spin, 1, 3)
        
        layout.addLayout(params_grid)
        
        # Progress section
        self.progress_label = QLabel("Processing: 0/0")
        self.progress_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.progress_label)
        
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)
        
        # Start/Stop buttons
        button_layout = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")
        
        self.start_button.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        
        self.stop_button.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)
        
        self.start_button.clicked.connect(self.start_processing)
        self.stop_button.clicked.connect(self.stop_processing)
        self.stop_button.setEnabled(False)
        
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        layout.addLayout(button_layout)
        
        # Support section
        help_label = QLabel("Terbantu sama toolsnya?")
        help_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(help_label)
        
        coffee_button = QPushButton("☕ Buy Me A Coffee")
        coffee_button.setStyleSheet("""
            QPushButton {
                background-color: #2F4F4F;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px;
            }
        """)
        coffee_button.clicked.connect(self.open_coffee)
        layout.addWidget(coffee_button)
        
        # Disclaimer
        disclaimer = QLabel("⚠️ APLIKASI GRATIS! Tidak Untuk Diperjual Belikan (Kalo lu beli berarti lu ditipu wkwkw) ⚠️")
        disclaimer.setStyleSheet("color: yellow;")
        disclaimer.setAlignment(Qt.AlignCenter)
        layout.addWidget(disclaimer)
        
        # Apply global style
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1A3333;
            }
            QLabel {
                color: #FF8C69;
            }
            QLineEdit, QComboBox, QSpinBox {
                background-color: #1F4040;
                color: white;
                border: 1px solid #2F5050;
                border-radius: 4px;
                padding: 5px;
            }
            QProgressBar {
                border: 1px solid #2F5050;
                border-radius: 4px;
                text-align: center;
                background-color: #1F4040;
            }
            QProgressBar::chunk {
                background-color: #3498db;
            }
        """)
        
        # Center window
        self.center()

    def center(self):
        screen = QApplication.desktop().screenGeometry()
        size = self.geometry()
        self.move(
            (screen.width() - size.width()) // 2,
            (screen.height() - size.height()) // 2
        )

    def toggle_api_key_visibility(self):
        if self.api_key_input.echoMode() == QLineEdit.Password:
            self.api_key_input.setEchoMode(QLineEdit.Normal)
            self.toggle_visibility.setText("🔒")
        else:
            self.api_key_input.setEchoMode(QLineEdit.Password)
            self.toggle_visibility.setText("👁️")

    def browse_input(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Input Folder")
        if folder:
            self.input_path_input.setText(folder)

    def browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.output_path_input.setText(folder)

    def save_config(self):
        config = {
            'api_key': self.api_key_input.text(),
            'model': self.model_combo.currentText(),
            'input_path': self.input_path_input.text(),
            'output_path': self.output_path_input.text(),
            'max_title_length': self.title_length_spin.value(),
            'max_keywords': self.max_keywords_spin.value(),
            'workers': self.workers_spin.value(),
            'delay': self.delay_spin.value(),
            'custom_keywords': self.custom_keywords_input.text()
        }
        try:
            with open('config.json', 'w') as f:
                json.dump(config, f)
            QMessageBox.information(self, "Success", "Configuration saved successfully!")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save configuration: {str(e)}")

    def load_config(self):
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
                self.api_key_input.setText(config.get('api_key', ''))
                index = self.model_combo.findText(config.get('model', ''))
                if index >= 0:
                    self.model_combo.setCurrentIndex(index)
                self.input_path_input.setText(config.get('input_path', ''))
                self.output_path_input.setText(config.get('output_path', ''))
                self.title_length_spin.setValue(config.get('max_title_length', 120))
                self.max_keywords_spin.setValue(config.get('max_keywords', 49))
                self.workers_spin.setValue(config.get('workers', 1))
                self.delay_spin.setValue(config.get('delay', 6))
                self.custom_keywords_input.setText(config.get('custom_keywords', ''))
        except FileNotFoundError:
            pass
        except Exception as e:
            QMessageBox.warning(self, "Warning", f"Error loading configuration: {str(e)}")

    def start_processing(self):
        if not self.input_path_input.text() or not self.output_path_input.text():
            QMessageBox.warning(self, "Warning", "Please select both input and output folders!")
            return

        if not self.api_key_input.text():
            QMessageBox.warning(self, "Warning", "Please enter your Gemini API key!")
            return

        if not os.path.exists(self.input_path_input.text()):
            QMessageBox.warning(self, "Warning", "Input folder does not exist!")
            return

        if not os.path.exists(self.output_path_input.text()):
            try:
                os.makedirs(self.output_path_input.text())
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Could not create output folder: {str(e)}")
                return

        try:
            genai.configure(api_key=self.api_key_input.text())
            model = genai.GenerativeModel(self.model_combo.currentText())
            test_response = model.generate_content("Test connection")
            if not test_response or not test_response.text:
                raise Exception("Could not connect to Gemini API")
        except Exception as e:
            QMessageBox.critical(self, "API Error", f"Could not initialize Gemini API: {str(e)}\nPlease check your API key and internet connection.")
            return

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.stop_flag = False

        # Get list of media files
        media_files = []
        for root, _, files in os.walk(self.input_path_input.text()):
            for file in files:
                if file.lower().endswith(tuple(['.jpg', '.jpeg', '.png', '.eps', '.mov', '.mp4'])):
                    media_files.append(os.path.join(root, file))

        if not media_files:
            QMessageBox.warning(self, "Warning", "No supported media files found in the input folder!")
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            return

        total_files = len(media_files)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(total_files)
        self.progress_label.setText(f"Processing: 0/{total_files}")

        csv_path = os.path.join(self.output_path_input.text(), 'metadata_export.csv')

        for i, media_file in enumerate(media_files):
            if self.stop_flag:
                break

            processor = FileProcessor(
                i + 1, total_files,
                os.path.basename(media_file),
                os.path.dirname(media_file),
                self.output_path_input.text(),
                self.api_key_input.text(),
                self.model_combo.currentText(),
                self.title_length_spin.value(),
                self.max_keywords_spin.value(),
                self.custom_keywords_input.text(),
                self.delay_spin.value(),
                self.csv_lock,
                csv_path,
                lambda: self.stop_flag
            )

            processor.signals.done.connect(self.update_progress)
            self.thread_pool.start(processor)

    def update_progress(self, progress):
        current = self.progress_bar.value() + progress
        self.progress_bar.setValue(current)
        total = self.progress_bar.maximum()
        self.progress_label.setText(f"Processing: {current}/{total}")

        if current >= total:
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            QMessageBox.information(self, "Complete", "Processing completed successfully!")

    def stop_processing(self):
        self.stop_flag = True
        self.stop_button.setEnabled(False)
        QMessageBox.information(self, "Stopping", "Processing will stop after current tasks complete...")

    def open_coffee(self):
        # Implement coffee link here
        pass

class TitleBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        
        title_label = QLabel("KYUGen V1")
        title_label.setStyleSheet("color: #FF8C69; font-size: 16px; font-weight: bold;")
        
        minimize_btn = QPushButton("—")
        close_btn = QPushButton("✕")
        
        control_style = """
            QPushButton {
                color: white;
                border: none;
                padding: 4px 8px;
                background: transparent;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.1);
            }
        """
        minimize_btn.setStyleSheet(control_style)
        close_btn.setStyleSheet(control_style)
        
        minimize_btn.clicked.connect(self.parent.showMinimized)
        close_btn.clicked.connect(self.parent.close)
        
        layout.addWidget(title_label)
        layout.addStretch()
        layout.addWidget(minimize_btn)
        layout.addWidget(close_btn)
        
        self.setLayout(layout)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.parent.drag_position = event.globalPos() - self.parent.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self.parent.move(event.globalPos() - self.parent.drag_position)
            event.accept()

def main():
    app = QApplication(sys.argv)
    window = MetadataApp()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main() 