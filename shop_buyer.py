# -*- coding: utf-8 -*-
"""
游戏店铺 - 自动批量购买工具
功能：自动遍历左侧商品列表 → 拉满购买数量 → 识别总价 → 金额超阈值弹窗确认 → 自动购买
热键：F9 开始/暂停切换，F10 紧急停止
校准：移动鼠标后按空格键确认保存坐标
"""

import tkinter as tk
from tkinter import ttk, messagebox
import pyautogui
import mss
import numpy as np
from PIL import Image, ImageOps
import asyncio
import winocr
import keyboard
import threading
import time
import json
import os
import re
import sys

# ============ DPI 感知（全屏/高DPI适配） ============
import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except:
        pass

# ============ 配置文件 ============
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shop_config.json")

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05


# ============ 底层点击（兼容游戏DirectInput） ============
def raw_click(x, y, delay_before=0.1, delay_after=0.15):
    """用Win32 API底层点击，兼容游戏DirectInput"""
    import time as _t
    # 先移动鼠标
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    _t.sleep(delay_before)
    # 鼠标按下
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTDOWN
    _t.sleep(0.03)
    # 鼠标释放
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # MOUSEEVENTF_LEFTUP
    _t.sleep(delay_after)


# ============ OCR 识别 ============
async def _ocr_async(image: Image.Image) -> str:
    if image.mode != "RGB":
        image = image.convert("RGB")
    result = await winocr.recognize_pil(image)
    return result.text


def recognize_price(region: tuple) -> int:
    """截取屏幕区域识别总价数字，多种预处理提高成功率"""
    try:
        left, top, right, bottom = region
        with mss.mss() as sct:
            monitor = {"left": left, "top": top, "width": right - left, "height": bottom - top}
            sct_img = sct.grab(monitor)
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

        # 放大5倍
        img = img.resize((img.width * 5, img.height * 5), Image.LANCZOS)

        from PIL import ImageOps
        gray = ImageOps.grayscale(img)

        # 更多预处理变体
        variants = [
            gray,
            ImageOps.autocontrast(gray),
            ImageOps.invert(gray),
            ImageOps.invert(ImageOps.autocontrast(gray)),
            gray.point(lambda x: 0 if x < 100 else 255, '1'),
            gray.point(lambda x: 0 if x < 150 else 255, '1'),
            ImageOps.autocontrast(gray).point(lambda x: 0 if x < 128 else 255, '1'),
        ]

        loop = asyncio.new_event_loop()
        best_price = -1

        for variant in variants:
            text = loop.run_until_complete(_ocr_async(variant))
            text_clean = text.replace(",", "").replace("，", "").replace(" ", "").replace("元", "")
            numbers = re.findall(r"\d+", text_clean)
            if numbers:
                numbers.sort(key=len, reverse=True)
                price = int(numbers[0])
                if price > best_price:
                    best_price = price

        loop.close()
        return best_price

    except Exception as e:
        print(f"[OCR错误] {e}")
        return -1


# ============ 屏幕区域拖拽框选器 ============
class ScreenRegionSelector:
    """全屏透明窗口，拖拽鼠标框选屏幕区域"""

    def __init__(self, on_select, title="拖拽框选区域"):
        self.on_select = on_select
        self.start_x = 0
        self.start_y = 0
        self.rect = None

        self.root = tk.Toplevel()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.3)
        self.root.configure(bg="black")
        self.root.config(cursor="cross")

        self.canvas = tk.Canvas(self.root, highlightthickness=0, bg="black")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.root.bind("<ButtonPress-1>", self._on_press)
        self.root.bind("<B1-Motion>", self._on_drag)
        self.root.bind("<ButtonRelease-1>", self._on_release)
        self.root.bind("<Escape>", lambda e: self._cancel())

        sw = self.root.winfo_screenwidth()
        self.canvas.create_text(
            sw // 2, 60,
            text=f"{title}\n按住鼠标左键拖拽框选，Esc 取消",
            fill="white", font=("微软雅黑", 16, "bold"), justify=tk.CENTER,
        )

    def _on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline="#00FF00", width=2
        )

    def _on_drag(self, event):
        if self.rect:
            self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)

    def _on_release(self, event):
        x1, y1 = self.start_x, self.start_y
        x2, y2 = event.x, event.y
        left, top = min(x1, x2), min(y1, y2)
        right, bottom = max(x1, x2), max(y1, y2)
        if right - left < 10 or bottom - top < 10:
            return
        self.root.destroy()
        self.on_select((left, top, right, bottom))

    def _cancel(self):
        self.root.destroy()
        self.on_select(None)


# ============ 校准向导（空格键确认） ============
class CalibrationWizard:
    """
    校准向导：移动鼠标到目标位置，按空格键确认记录
    按 Esc 取消校准
    """

    def __init__(self, parent, on_complete):
        self.parent = parent
        self.result = {}
        self.on_complete = on_complete
        self.steps = [
            ("step_a", "第1步：第一个商品", "把鼠标移到左上角第一个商品图标中心\n\n准备好后按空格键确认"),
            ("step_b", "第2步：同行右边商品", "把鼠标移到同一行右边相邻商品中心\n\n准备好后按空格键确认"),
            ("step_c", "第3步：同列下边商品", "把鼠标移到同一列下边相邻商品中心\n\n准备好后按空格键确认"),
            ("step_plus", "第4步：+号按钮", "把鼠标移到增加数量的+号按钮上\n\n准备好后按空格键确认"),
            ("step_price_region", "第5步：总价区域", "框选总价数字显示区域\n拖拽鼠标拉出矩形框\n\n按空格键开始框选"),
            ("step_currency_region", "第6步：货币区域", "框选右上角货币数量显示区域\n用于校验购买是否成功\n\n按空格键开始框选"),
            ("step_buy", "第7步：购买按钮", "把鼠标移到底部购买按钮上\n\n准备好后按空格键确认"),
            ("step_confirm", "第8步：确认弹窗", "把鼠标移到确认购买弹窗的确认按钮\n没有弹窗就移到屏幕左上角\n\n准备好后按空格键确认"),
            ("step_close", "第9步：关闭返回", "把鼠标移到购买后关闭弹窗的按钮\n不需要就移到屏幕左上角\n\n准备好后按空格键确认"),
        ]
        self.step_index = 0
        self.win = None
        self.cancelled = False
        self._build()
        self._bind_keys()

    def _build(self):
        self.win = tk.Toplevel()
        self.win.title("校准向导")
        self.win.attributes("-topmost", True)
        self.win.geometry("400x180")
        self.win.resizable(False, False)

        # 校准窗口放在主窗口内部居中位置
        try:
            parent_x = self.parent.winfo_x()
            parent_y = self.parent.winfo_y()
            parent_w = self.parent.winfo_width()
            parent_h = self.parent.winfo_height()
            win_w = 400
            win_h = 180
            x = parent_x + (parent_w - win_w) // 2
            y = parent_y + (parent_h - win_h) // 2
            self.win.geometry(f"+{x}+{y}")
        except:
            pass

        self.title_label = tk.Label(self.win, text="", font=("微软雅黑", 13, "bold"), fg="#2196F3")
        self.title_label.pack(pady=(15, 5))

        self.label = tk.Label(self.win, text="", font=("微软雅黑", 10), justify=tk.CENTER, wraplength=400)
        self.label.pack(expand=True, pady=10)

        self.hint_label = tk.Label(self.win, text="移动鼠标 → 按空格键确认", font=("微软雅黑", 9), fg="gray")
        self.hint_label.pack(pady=5)

        self._show_step()

    def _bind_keys(self):
        self.win.bind("<space>", self._on_space)
        self.win.bind("<Escape>", self._on_cancel)
        self.win.focus_set()

    def _show_step(self):
        if self.step_index >= len(self.steps):
            self._finish()
            return

        key, title, desc = self.steps[self.step_index]
        self.title_label.config(text=title)
        self.label.config(text=desc)
        self.win.title(f"校准向导 ({self.step_index+1}/{len(self.steps)})")

    def _on_space(self, event=None):
        if self.step_index >= len(self.steps):
            return
        key = self.steps[self.step_index][0]

        # 拖拽框选类步骤
        if key in ("step_price_region", "step_currency_region"):
            self.win.withdraw()
            self.win.after(200, lambda: ScreenRegionSelector(self._on_region_selected))
            return

        # 其他步骤：记录鼠标位置
        x, y = pyautogui.position()
        self.result[key] = (x, y)
        print(f"[校准] {key}: ({x}, {y})")
        self.step_index += 1
        self._show_step()

    def _on_region_selected(self, region):
        self.win.deiconify()
        self.win.focus_set()
        if region is None:
            self._on_cancel()
            return
        # 根据当前步骤决定保存到哪个key
        key = self.steps[self.step_index][0]
        self.result[key] = region
        print(f"[校准] {key}: {region}")
        self.step_index += 1
        self._show_step()

    def _on_cancel(self, event=None):
        self.cancelled = True
        self.win.destroy()

    def _finish(self):
        self.win.destroy()
        if self.cancelled:
            return

        ax, ay = self.result["step_a"]
        bx, by = self.result["step_b"]
        cx, cy = self.result["step_c"]
        self.result["cell_width"] = bx - ax
        self.result["cell_height"] = cy - ay
        self.result["start_x"] = ax
        self.result["start_y"] = ay

        # 总价区域直接从拖拽框选获取
        # price_region 已在 _on_region_selected 中设置

        self.on_complete(self.result)


# ============ 自动购买引擎 ============
class BuyerEngine:
    def __init__(self, config, log_callback, status_callback):
        self.config = config
        self.log = log_callback
        self.set_status = status_callback
        self.running = False
        self.paused = False
        self.stopped = False
        self.thread = None
        self.auto_approve_all = False  # 全是：后续全部自动通过
        self.auto_reject_all = False   # 全否：后续全部自动跳过

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.running = True
        self.paused = False
        self.stopped = False
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def toggle_pause(self):
        self.paused = not self.paused
        return self.paused

    def stop(self):
        self.stopped = True
        self.running = False
        self.paused = False

    def _wait_if_paused(self):
        while self.paused and not self.stopped:
            time.sleep(0.1)

    def _run(self):
        try:
            cfg = self.config
            start_x = cfg["start_x"]
            start_y = cfg["start_y"]
            cell_w = cfg["cell_width"]
            cell_h = cfg["cell_height"]
            plus_btn = cfg["step_plus"]
            buy_btn = cfg["step_buy"]
            confirm_btn = cfg["step_confirm"]
            close_btn = cfg["step_close"]
            price_region = cfg["price_region"]
            currency_region = cfg.get("step_currency_region")
            max_price = cfg["max_price"]
            cols = cfg["cols"]
            rows = cfg["rows"]
            click_count = cfg["plus_clicks"]

            total = cols * rows
            bought = 0
            total_cost = 0
            plus_clicks_total = 0
            initial_currency = -1

            # 读取初始货币数量
            if currency_region:
                initial_currency = recognize_price(currency_region)
                self.log(f"初始货币数量: {initial_currency}")

            self.log(f"=== 开始批量购买，共 {total} 个商品格子 ===")
            self.set_status(f"运行中 0/{total}")

            for row in range(rows):
                for col in range(cols):
                    if self.stopped:
                        self.log("=== 已紧急停止 ===")
                        return

                    self._wait_if_paused()
                    if self.stopped:
                        return

                    idx = row * cols + col + 1
                    cx = start_x + col * cell_w
                    cy = start_y + row * cell_h

                    self.log(f"[{idx}/{total}] 点击商品 ({cx}, {cy})")
                    raw_click(cx, cy)
                    time.sleep(0.8)

                    self.log(f"  拉满数量：点击+号 {click_count} 次")
                    current_plus = 0
                    for _ in range(click_count):
                        if self.stopped:
                            return
                        raw_click(plus_btn[0], plus_btn[1], delay_before=0.02, delay_after=0.05)
                        plus_clicks_total += 1
                        current_plus += 1
                        self.set_status(f"当前+号: {current_plus}/{click_count} | 总点击: {plus_clicks_total}")
                        self._wait_if_paused()
                        if self.stopped:
                            return
                        time.sleep(0.05)
                    time.sleep(0.5)

                    price = recognize_price(price_region)
                    if price < 0:
                        self.log(f"  [警告] 总价识别失败，跳过")
                        continue

                    self.log(f"  识别总价：{price}")

                    if price > max_price:
                        self.log(f"  [拦截] 总价 {price} > 阈值 {max_price}，等待确认...")

                        # 自动全是
                        if self.auto_approve_all:
                            self.log(f"  自动通过（全是模式）")
                        # 自动全否
                        elif self.auto_reject_all:
                            self.log(f"  自动跳过（全否模式）")
                            raw_click(close_btn[0], close_btn[1])
                            time.sleep(0.5)
                            continue
                        # 弹窗确认
                        else:
                            confirmed = threading.Event()
                            result_box = {}

                            def ask():
                                win = tk.Toplevel()
                                win.title("金额超阈值")
                                win.attributes("-topmost", True)
                                win.geometry("320x220")
                                win.resizable(False, False)

                                tk.Label(win, text=f"本次购买总价：{price}", font=("微软雅黑", 11)).pack(pady=10)
                                tk.Label(win, text=f"阈值上限：{max_price}", font=("微软雅黑", 10), fg="gray").pack()
                                tk.Label(win, text="", font=("微软雅黑", 8)).pack()

                                def on_yes():
                                    result_box["ans"] = "yes"
                                    confirmed.set()
                                    win.destroy()
                                def on_no():
                                    result_box["ans"] = "no"
                                    confirmed.set()
                                    win.destroy()
                                def on_all_yes():
                                    result_box["ans"] = "all_yes"
                                    self.auto_approve_all = True
                                    confirmed.set()
                                    win.destroy()
                                def on_all_no():
                                    result_box["ans"] = "all_no"
                                    self.auto_reject_all = True
                                    confirmed.set()
                                    win.destroy()

                                btn_frame = tk.Frame(win)
                                btn_frame.pack(pady=10)
                                tk.Button(btn_frame, text="是", width=6, command=on_yes).pack(side=tk.LEFT, padx=5)
                                tk.Button(btn_frame, text="否", width=6, command=on_no).pack(side=tk.LEFT, padx=5)
                                tk.Button(btn_frame, text="全是", width=6, command=on_all_yes, bg="#4CAF50", fg="white").pack(side=tk.LEFT, padx=5)
                                tk.Button(btn_frame, text="全否", width=6, command=on_all_no, bg="#f44336", fg="white").pack(side=tk.LEFT, padx=5)

                            self.set_status(f"等待确认 {price}")
                            self.log_callback_main(ask)
                            confirmed.wait()

                            ans = result_box.get("ans", "no")
                            if ans in ("no", "all_no"):
                                self.log(f"  用户取消，跳过")
                                raw_click(close_btn[0], close_btn[1])
                                time.sleep(0.5)
                                continue
                            self.log(f"  用户确认继续")

                    # 记录购买前货币数量
                    currency_before = recognize_price(currency_region) if currency_region else -1

                    self.log(f"  点击购买按钮")
                    raw_click(buy_btn[0], buy_btn[1])
                    time.sleep(1.2)  # 等待弹窗出现

                    # 点击确认弹窗
                    if confirm_btn[0] > 10 or confirm_btn[1] > 10:
                        self.log(f"  点击确认弹窗")
                        raw_click(confirm_btn[0], confirm_btn[1])
                        time.sleep(1.0)

                    # 保底校验：检查货币是否减少
                    success = False
                    if currency_region and currency_before > 0:
                        time.sleep(0.8)
                        currency_after = recognize_price(currency_region)
                        if currency_after > 0 and currency_after < currency_before:
                            spent = currency_before - currency_after
                            self.log(f"  ✓ 购买成功，花费 {spent}")
                            total_cost += spent
                            success = True
                        else:
                            self.log(f"  ✗ 货币未变化，重试第1次...")
                            # 重试1
                            raw_click(buy_btn[0], buy_btn[1])
                            time.sleep(1.0)
                            if confirm_btn[0] > 10 or confirm_btn[1] > 10:
                                raw_click(confirm_btn[0], confirm_btn[1])
                                time.sleep(1.0)
                            time.sleep(0.8)
                            currency_after2 = recognize_price(currency_region)
                            if currency_after2 > 0 and currency_after2 < currency_before:
                                spent = currency_before - currency_after2
                                self.log(f"  ✓ 重试成功，花费 {spent}")
                                total_cost += spent
                                success = True
                            else:
                                self.log(f"  ✗ 重试第1次失败，重试第2次...")
                                # 重试2
                                raw_click(buy_btn[0], buy_btn[1])
                                time.sleep(1.0)
                                if confirm_btn[0] > 10 or confirm_btn[1] > 10:
                                    raw_click(confirm_btn[0], confirm_btn[1])
                                    time.sleep(1.0)
                                time.sleep(0.8)
                                currency_after3 = recognize_price(currency_region)
                                if currency_after3 > 0 and currency_after3 < currency_before:
                                    spent = currency_before - currency_after3
                                    self.log(f"  ✓ 第2次重试成功，花费 {spent}")
                                    total_cost += spent
                                    success = True
                                else:
                                    self.log(f"  ✗ 3次都失败，跳过")
                                    # 检测货币不足
                                    if currency_before < price:
                                        self.log(f"  ⚠️ 货币不足！当前货币 {currency_before}，总价 {price}")
                                        self.log(f"  自动停止批量购买")
                                        self.stopped = True
                                        self.running = False
                                        self.set_status("货币不足，已停止")
                                        return
                    else:
                        # 没有货币区域，默认成功
                        success = True
                        total_cost += price

                    if success:
                        bought += 1
                        remaining = recognize_price(currency_region) if currency_region else -1
                        self.set_status(f"运行中 {bought}/{total} | 花费 {total_cost} | 剩余 {remaining}")
                        self.log(f"  累计花费: {total_cost}")

                    if close_btn[0] > 10 or close_btn[1] > 10:
                        raw_click(close_btn[0], close_btn[1])
                        time.sleep(0.6)

            # 汇总
            self.log(f"=== 全部完成 ===")
            self.log(f"成功购买: {bought} 个")
            self.log(f"累计花费: {total_cost}")
            if initial_currency > 0:
                final_currency = recognize_price(currency_region)
                self.log(f"初始货币: {initial_currency}")
                self.log(f"剩余货币: {final_currency}")
                self.log(f"实际消耗: {initial_currency - final_currency}")
            self.set_status(f"完成 {bought}/{total} | 花费 {total_cost}")

        except Exception as e:
            self.log(f"[运行错误] {e}")
            self.set_status("出错")

    def log_callback_main(self, fn):
        pass


# ============ 主窗口 ============
class MainApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("游戏道具店铺自动购买工具")
        self.root.geometry("680x860")
        self.root.minsize(530, 740)
        self.root.resizable(True, True)

        self.config = self._load_config()
        self.engine = None
        self.topmost = tk.BooleanVar(value=True)  # 默认置顶
        self._build_ui()
        self._bind_hotkeys()
        self._apply_topmost()

        if self.config:
            self._show_config_info()

    def _load_config(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return {}

    def _save_config(self):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)

    def _apply_topmost(self):
        self.root.attributes("-topmost", self.topmost.get())

    def _toggle_topmost(self):
        self.topmost.set(not self.topmost.get())
        self._apply_topmost()
        self._update_pin_btn()

    def _update_pin_btn(self):
        if self.topmost.get():
            self.btn_pin.config(text="📌 Ctrl+T", fg="#E91E63")
        else:
            self.btn_pin.config(text="📌 Ctrl+T", fg="gray")

    def _build_ui(self):
        # 标题栏行
        header = tk.Frame(self.root)
        header.pack(fill=tk.X, padx=15, pady=(10, 0))

        title = tk.Label(header, text="自动批量购买", font=("微软雅黑", 14, "bold"))
        title.pack(side=tk.LEFT)

        # 标题提示
        tip = tk.Label(self.root, text="提示：请确保所有点击位置在最前端、无遮挡",
                       font=("微软雅黑", 8), fg="#ff9800")
        tip.pack(anchor=tk.W, padx=15, pady=(0, 5))

        # 置顶按钮（标题栏样式，右上角）
        self.btn_pin = tk.Button(header, text="📌 Ctrl+T", font=("微软雅黑", 9),
                                 bd=0, relief=tk.FLAT, cursor="hand2",
                                 command=self._toggle_topmost)
        self.btn_pin.pack(side=tk.RIGHT, padx=(5, 0))
        self._update_pin_btn()

        # 设置区
        frame_set = ttk.LabelFrame(self.root, text="运行设置")
        frame_set.pack(fill=tk.X, padx=15, pady=5)

        # 当前配置名称
        self.config_name_label = tk.Label(frame_set, text="当前配置：默认", font=("微软雅黑", 9), fg="#2196F3")
        self.config_name_label.pack(anchor=tk.W, padx=10, pady=(2, 0))

        row1 = tk.Frame(frame_set)
        row1.pack(fill=tk.X, padx=10, pady=3)
        tk.Label(row1, text="金额阈值:", font=("微软雅黑", 10)).pack(side=tk.LEFT)
        self.entry_maxprice = tk.Entry(row1, width=10, font=("微软雅黑", 10))
        self.entry_maxprice.pack(side=tk.LEFT, padx=5)
        self.entry_maxprice.insert(0, str(self.config.get("max_price", 10000)))

        row2 = tk.Frame(frame_set)
        row2.pack(fill=tk.X, padx=10, pady=3)
        tk.Label(row2, text="列数:", font=("微软雅黑", 10)).pack(side=tk.LEFT)
        self.entry_cols = tk.Entry(row2, width=4, font=("微软雅黑", 10))
        self.entry_cols.pack(side=tk.LEFT, padx=3)
        self.entry_cols.insert(0, str(self.config.get("cols", 4)))
        tk.Label(row2, text="行数:", font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=(15, 0))
        self.entry_rows = tk.Entry(row2, width=4, font=("微软雅黑", 10))
        self.entry_rows.pack(side=tk.LEFT, padx=3)
        self.entry_rows.insert(0, str(self.config.get("rows", 4)))

        row2b = tk.Frame(frame_set)
        row2b.pack(fill=tk.X, padx=10, pady=3)
        tk.Label(row2b, text="点+号次数:", font=("微软雅黑", 10)).pack(side=tk.LEFT)
        self.entry_plus = tk.Entry(row2b, width=5, font=("微软雅黑", 10))
        self.entry_plus.pack(side=tk.LEFT, padx=3)
        self.entry_plus.insert(0, str(self.config.get("plus_clicks", 15)))

        # 点击计数器
        row3 = tk.Frame(frame_set)
        row3.pack(fill=tk.X, padx=10, pady=3)
        tk.Label(row3, text="商品种类:", font=("微软雅黑", 10)).pack(side=tk.LEFT)
        self.counter_label = tk.Label(row3, text="0", font=("微软雅黑", 12, "bold"), fg="#4CAF50")
        self.counter_label.pack(side=tk.LEFT, padx=3)
        tk.Label(row3, text="/", font=("微软雅黑", 10)).pack(side=tk.LEFT)
        self.counter_total_label = tk.Label(row3, text="0", font=("微软雅黑", 10), fg="gray")
        self.counter_total_label.pack(side=tk.LEFT, padx=3)

        row3b = tk.Frame(frame_set)
        row3b.pack(fill=tk.X, padx=10, pady=3)
        tk.Label(row3b, text="当前+号:", font=("微软雅黑", 10)).pack(side=tk.LEFT)
        self.plus_current_label = tk.Label(row3b, text="0", font=("微软雅黑", 12, "bold"), fg="#FF9800")
        self.plus_current_label.pack(side=tk.LEFT, padx=3)
        tk.Label(row3b, text="/", font=("微软雅黑", 10)).pack(side=tk.LEFT)
        self.plus_max_label = tk.Label(row3b, text="15", font=("微软雅黑", 10), fg="gray")
        self.plus_max_label.pack(side=tk.LEFT, padx=3)
        tk.Label(row3b, text="  总点击:", font=("微软雅黑", 10)).pack(side=tk.LEFT, padx=(15, 0))
        self.plus_total_label = tk.Label(row3b, text="0", font=("微软雅黑", 12, "bold"), fg="#9C27B0")
        self.plus_total_label.pack(side=tk.LEFT, padx=3)
        # 初始化上限显示
        self.plus_max_label.config(text=self.entry_plus.get())

        # 按钮区（双排显示）
        frame_btn = tk.Frame(self.root)
        frame_btn.pack(fill=tk.X, padx=15, pady=5)

        # 第一排：校准相关
        frame_btn1 = tk.Frame(frame_btn)
        frame_btn1.pack(fill=tk.X, pady=2)
        self.btn_calib = tk.Button(frame_btn1, text="校准坐标", font=("微软雅黑", 10),
                                   width=8, command=self._start_calibration)
        self.btn_calib.pack(side=tk.LEFT, padx=3)
        self.btn_reset = tk.Button(frame_btn1, text="重新校准", font=("微软雅黑", 10),
                                   width=8, command=self._reset_calibration)
        self.btn_reset.pack(side=tk.LEFT, padx=3)
        self.btn_save_preset = tk.Button(frame_btn1, text="保存配置", font=("微软雅黑", 10),
                                          width=8, command=self._save_preset)
        self.btn_save_preset.pack(side=tk.LEFT, padx=3)
        self.btn_load_preset = tk.Button(frame_btn1, text="加载配置", font=("微软雅黑", 10),
                                          width=8, command=self._load_preset)
        self.btn_load_preset.pack(side=tk.LEFT, padx=3)

        # 第二排：运行控制
        frame_btn2 = tk.Frame(frame_btn)
        frame_btn2.pack(fill=tk.X, pady=2)
        self.btn_toggle = tk.Button(frame_btn2, text="开始运行 (F9)", font=("微软雅黑", 10),
                                    width=12, bg="#4CAF50", fg="white", command=self._toggle_run)
        self.btn_toggle.pack(side=tk.LEFT, padx=3)
        self.btn_stop = tk.Button(frame_btn2, text="停止 (F10)", font=("微软雅黑", 10),
                                  width=8, bg="#f44336", fg="white", command=self._stop)
        self.btn_stop.pack(side=tk.LEFT, padx=3)

        # 状态
        self.status_label = tk.Label(self.root, text="状态：就绪", font=("微软雅黑", 10, "bold"), fg="gray")
        self.status_label.pack(pady=3)

        # 操作指引（可折叠）
        self.help_visible = tk.BooleanVar(value=False)
        frame_help = ttk.LabelFrame(self.root, text="操作指引（点击折叠/展开）")
        frame_help.pack(fill=tk.X, padx=15, pady=(0, 5))

        self.btn_toggle_help = tk.Button(frame_help, text="▼ 展开", font=("微软雅黑", 9),
                                         bd=0, relief=tk.FLAT, command=self._toggle_help)
        self.btn_toggle_help.pack(anchor=tk.W, padx=5)

        self.help_content = tk.Frame(frame_help)
        # 默认收起，不显示内容
        help_text = (
            "【首次使用】点「校准坐标」→ 按9步提示完成校准 → 按F9开始\n"
            "【F9】开始/暂停/继续（暂停后切窗口操作，回来再按F9继续）\n"
            "【F10】停止本次运行（结束批量任务，不退出程序）\n"
            "【Ctrl+T】切换窗口置顶，点右上角📌也可以\n"
            "【校准确认】鼠标移到目标位置 → 按空格键确认\n"
            "【框选区域】按空格后，按住鼠标拖拽拉出矩形框\n"
            "【保存配置】校准完点「保存配置」，下次直接加载"
        )
        tk.Label(self.help_content, text=help_text, font=("微软雅黑", 9), justify=tk.LEFT, fg="#555").pack(anchor=tk.W)
        # 默认收起，不显示内容
        self.help_content.pack_forget()

        # 底部先pack：退出按钮 + 免责声明（确保始终可见）
        frame_exit = tk.Frame(self.root)
        frame_exit.pack(fill=tk.X, padx=15, pady=(0, 3), side=tk.BOTTOM)
        self.btn_quit = tk.Button(frame_exit, text="退出程序", font=("微软雅黑", 9),
                                  width=10, bg="#f44336", fg="white", command=self._quit)
        self.btn_quit.pack(side=tk.RIGHT)

        disclaimer = tk.Label(self.root, text="免责声明：本工具仅模拟鼠标点击操作，不修改任何游戏数据 | 禁止盈利倒卖，风险自负",
                              font=("微软雅黑", 8), fg="gray", justify=tk.CENTER)
        disclaimer.pack(side=tk.BOTTOM, pady=(2, 0))

        # 日志区（最后pack，expand占剩余空间）
        frame_log = ttk.LabelFrame(self.root, text="运行日志")
        frame_log.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)

        self.log_text = tk.Text(frame_log, font=("Consolas", 9), wrap=tk.WORD, state=tk.DISABLED, height=8)
        scrollbar = ttk.Scrollbar(frame_log, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _show_config_info(self):
        self._log(f"[配置] 已加载上次校准数据")
        self._log(f"[配置] 商品格子: 宽{self.config.get('cell_width','?')} 高{self.config.get('cell_height','?')}")

    def _log(self, msg):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _set_status(self, s):
        self.status_label.config(text=f"状态：{s}")
        # 更新商品种类计数器
        if "运行中" in s or "完成" in s:
            parts = s.split()
            if len(parts) >= 2 and "/" in parts[1]:
                current, total = parts[1].split("/")
                self.counter_label.config(text=current)
                self.counter_total_label.config(text=total)
        # 更新+号计数器
        if "当前+号:" in s:
            # 格式：当前+号: 5/15 | 总点击: 20
            parts = s.split("|")
            for p in parts:
                p = p.strip()
                if p.startswith("当前+号:"):
                    cur, mx = p.split(":")[1].strip().split("/")
                    self.plus_current_label.config(text=cur)
                    self.plus_max_label.config(text=mx)
                elif p.startswith("总点击:"):
                    total = p.split(":")[1].strip()
                    self.plus_total_label.config(text=total)

    def _toggle_help(self):
        if self.help_visible.get():
            self.help_content.pack_forget()
            self.btn_toggle_help.config(text="▼ 展开")
            self.help_visible.set(False)
        else:
            self.help_content.pack(fill=tk.X, padx=10, pady=(0, 5))
            self.btn_toggle_help.config(text="▲ 收起")
            self.help_visible.set(True)

    def _reset_calibration(self):
        """清空配置，重新校准"""
        if messagebox.askyesno("确认", "确定要清空所有校准数据并重新开始吗？"):
            self.config = {}
            self._save_config()
            self._log("=== 已重置校准数据 ===")
            self._start_calibration()

    def _save_preset(self):
        """保存当前配置为预设"""
        from tkinter import simpledialog
        name = simpledialog.askstring("保存配置", "请输入配置名称：", parent=self.root)
        if not name:
            return
        presets_path = os.path.join(os.path.dirname(CONFIG_PATH), "shop_presets.json")
        presets = {}
        if os.path.exists(presets_path):
            try:
                with open(presets_path, "r", encoding="utf-8") as f:
                    presets = json.load(f)
            except:
                pass
        presets[name] = self.config.copy()
        with open(presets_path, "w", encoding="utf-8") as f:
            json.dump(presets, f, ensure_ascii=False, indent=2)
        self._log(f"=== 配置「{name}」已保存 ===")
        messagebox.showinfo("保存成功", f"配置「{name}」已保存！")

    def _load_preset(self):
        """加载预设配置"""
        presets_path = os.path.join(os.path.dirname(CONFIG_PATH), "shop_presets.json")
        if not os.path.exists(presets_path):
            messagebox.showinfo("提示", "还没有保存过任何配置")
            return
        try:
            with open(presets_path, "r", encoding="utf-8") as f:
                presets = json.load(f)
        except:
            messagebox.showinfo("提示", "配置文件读取失败")
            return
        if not presets:
            messagebox.showinfo("提示", "还没有保存过任何配置")
            return
        # 弹出选择窗口
        win = tk.Toplevel(self.root)
        win.title("选择配置")
        win.attributes("-topmost", True)
        win.geometry("320x350")
        # 窗口放在主窗口内侧居中
        try:
            px = self.root.winfo_x()
            py = self.root.winfo_y()
            pw = self.root.winfo_width()
            ph = self.root.winfo_height()
            win_x = px + (pw - 320) // 2
            win_y = py + (ph - 350) // 2
            win.geometry(f"+{win_x}+{win_y}")
        except:
            pass
        tk.Label(win, text="选择要加载的配置（双击直接加载）：", font=("微软雅黑", 10)).pack(pady=10)
        listbox = tk.Listbox(win, font=("微软雅黑", 10), width=25, height=10)
        listbox.pack(pady=5)
        for name in presets.keys():
            listbox.insert(tk.END, name)

        def on_select():
            sel = listbox.curselection()
            if sel:
                name = listbox.get(sel[0])
                self.config = presets[name].copy()
                self._save_config()
                self.config_name_label.config(text=f"当前配置：{name}")
                self._log(f"✅ 已加载配置「{name}」")
                self._log(f"   格子: ({self.config.get('start_x','?')}, {self.config.get('start_y','?')})")
                messagebox.showinfo("加载成功", f"配置「{name}」已加载！\n按F9开始运行。", parent=win)
                win.destroy()

        # 双击列表项直接加载
        listbox.bind("<Double-Button-1>", lambda e: on_select())

        btn_frame = tk.Frame(win)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="加载", command=on_select, font=("微软雅黑", 10),
                  width=8, bg="#4CAF50", fg="white").pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="取消", command=win.destroy, font=("微软雅黑", 10),
                  width=8).pack(side=tk.LEFT, padx=5)

    def _start_calibration(self):
        self._log("=== 开始校准向导 ===")
        wizard = CalibrationWizard(self.root, self._on_calib_done)

    def _on_calib_done(self, result):
        self.config.update(result)
        # 映射 key：step_price_region -> price_region
        if "step_price_region" in result:
            self.config["price_region"] = result["step_price_region"]
        self.config["cols"] = int(self.entry_cols.get())
        self.config["rows"] = int(self.entry_rows.get())
        self.config["max_price"] = int(self.entry_maxprice.get())
        self.config["plus_clicks"] = int(self.entry_plus.get())
        self._save_config()
        self._log("=== 校准完成，配置已保存 ===")
        self._log(f"  格子起始: ({result['start_x']}, {result['start_y']})")
        self._log(f"  格子宽高: {result['cell_width']} x {result['cell_height']}")
        messagebox.showinfo("校准完成", "坐标校准已完成并保存！\n现在可以按 F9 开始运行。")

    def _read_settings(self):
        self.config["max_price"] = int(self.entry_maxprice.get())
        self.config["cols"] = int(self.entry_cols.get())
        self.config["rows"] = int(self.entry_rows.get())
        self.config["plus_clicks"] = int(self.entry_plus.get())
        self._save_config()

    def _toggle_run(self):
        """F9 一键切换：未运行→开始；运行中→暂停/继续"""
        if not self.engine or not self.engine.running:
            # 启动
            if not self.config.get("start_x"):
                messagebox.showwarning("提示", "请先点击「校准坐标」完成校准！")
                return
            self._read_settings()
            self._log("=== 启动自动购买引擎 ===")
            self.engine = BuyerEngine(self.config, log_callback=self._log, status_callback=self._set_status)
            self.engine.log_callback_main = lambda fn: self.root.after(0, fn)
            self.engine.start()
            self.btn_toggle.config(text="暂停 (F9)", bg="#FF9800")
            self._set_status("运行中")
        else:
            # 暂停/继续切换
            paused = self.engine.toggle_pause()
            if paused:
                self.btn_toggle.config(text="继续 (F9)", bg="#4CAF50")
                self._set_status("已暂停")
            else:
                self.btn_toggle.config(text="暂停 (F9)", bg="#FF9800")
                self._set_status("运行中")

    def _stop(self):
        if self.engine:
            self.engine.stop()
            self.engine = None
        self.btn_toggle.config(text="开始运行 (F9)", bg="#4CAF50")
        self._set_status("已停止")

    def _quit(self):
        if self.engine:
            self.engine.stop()
        self.root.destroy()

    def _bind_hotkeys(self):
        keyboard.add_hotkey("f9", self._toggle_run)
        keyboard.add_hotkey("f10", self._stop)
        keyboard.add_hotkey("ctrl+t", self._toggle_topmost)

    def run(self):
        # 窗口大小变化时只自动折叠，不自动展开
        def on_resize(event):
            if event.widget == self.root:
                h = self.root.winfo_height()
                if h < 650 and self.help_visible.get():
                    self._toggle_help()
        self.root.bind("<Configure>", on_resize)
        self.root.mainloop()


if __name__ == "__main__":
    app = MainApp()
    app.run()
