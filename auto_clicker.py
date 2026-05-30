"""
自动连点器 - 按F6开启/关闭
"""
import time
import ctypes
import keyboard
import tkinter as tk
from tkinter import ttk
import threading

# DPI aware：避免缩放导致坐标漂移
ctypes.windll.user32.SetProcessDPIAware()
user32 = ctypes.windll.user32

INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    _anonymous_ = ("i",)
    _fields_ = [("type", ctypes.c_ulong), ("i", _I)]


class AutoClicker:
    def __init__(self, click_interval=0.05):
        self.running = False
        self.click_interval = click_interval  # 连点间隔（秒）
        self.click_count = 0  # 点击次数统计
        self.gui_root = None
        self.status_label = None
        self.count_label = None
        self.interval_label = None
        
        print("=" * 50)
        print("     自动连点器")
        print("=" * 50)
        print(f"连点间隔: {click_interval * 1000:.0f}毫秒")
        print("按 F6 键开启/关闭连点")
        print("按 ESC 键退出程序")
        print("=" * 50)

    def update_gui(self):
        """更新GUI显示"""
        if self.gui_root and self.status_label:
            try:
                if self.running:
                    self.status_label.config(text="运行中", foreground="green", font=("Microsoft YaHei", 16, "bold"))
                else:
                    self.status_label.config(text="已暂停", foreground="red", font=("Microsoft YaHei", 16, "bold"))
                
                self.count_label.config(text=f"点击次数: {self.click_count}")
                self.interval_label.config(text=f"间隔: {self.click_interval * 1000:.0f}ms")
            except:
                pass

    def create_gui(self):
        """创建GUI窗口"""
        self.gui_root = tk.Tk()
        self.gui_root.title("自动连点器")
        self.gui_root.geometry("320x240")
        self.gui_root.resizable(False, False)
        
        # 设置窗口图标（可选）
        try:
            self.gui_root.iconbitmap(default="")
        except:
            pass
        
        # 主框架
        main_frame = ttk.Frame(self.gui_root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题
        title_label = tk.Label(
            main_frame, 
            text="🖱️ 自动连点器", 
            font=("Microsoft YaHei", 14, "bold"),
            fg="#333333"
        )
        title_label.pack(pady=(0, 15))
        
        # 状态显示
        status_frame = tk.Frame(main_frame, bg="#f0f0f0", relief=tk.RIDGE, bd=2)
        status_frame.pack(fill=tk.X, pady=10)
        
        tk.Label(status_frame, text="状态:", font=("Microsoft YaHei", 10), bg="#f0f0f0").pack(side=tk.LEFT, padx=10)
        self.status_label = tk.Label(
            status_frame, 
            text="已暂停", 
            font=("Microsoft YaHei", 16, "bold"),
            foreground="red",
            bg="#f0f0f0"
        )
        self.status_label.pack(side=tk.LEFT, padx=10, pady=8)
        
        # 统计信息
        info_frame = tk.Frame(main_frame)
        info_frame.pack(fill=tk.X, pady=10)
        
        self.count_label = tk.Label(
            info_frame, 
            text=f"点击次数: {self.click_count}",
            font=("Microsoft YaHei", 10),
            fg="#555555"
        )
        self.count_label.pack(anchor=tk.W)
        
        self.interval_label = tk.Label(
            info_frame, 
            text=f"间隔: {self.click_interval * 1000:.0f}ms",
            font=("Microsoft YaHei", 10),
            fg="#555555"
        )
        self.interval_label.pack(anchor=tk.W)
        
        # 快捷键提示
        hotkey_frame = tk.Frame(main_frame, bg="#e8f4f8", relief=tk.GROOVE, bd=1)
        hotkey_frame.pack(fill=tk.X, pady=(10, 0))
        
        tk.Label(
            hotkey_frame, 
            text="快捷键:", 
            font=("Microsoft YaHei", 9, "bold"),
            bg="#e8f4f8",
            fg="#0066cc"
        ).pack(anchor=tk.W, padx=8, pady=(5, 2))
        
        tk.Label(
            hotkey_frame, 
            text="F6 - 开启/关闭连点\nESC - 退出程序",
            font=("Microsoft YaHei", 9),
            bg="#e8f4f8",
            fg="#333333",
            justify=tk.LEFT
        ).pack(anchor=tk.W, padx=8, pady=(0, 5))
        
        # 关闭窗口时最小化到托盘（实际上隐藏窗口）
        def on_closing():
            self.gui_root.withdraw()  # 隐藏窗口而不是关闭
        
        self.gui_root.protocol("WM_DELETE_WINDOW", on_closing)
        
        # 双击任务栏图标显示窗口
        self.gui_root.bind("<Map>", lambda e: self.gui_root.deiconify())

    def toggle(self):
        """切换连点状态"""
        self.running = not self.running
        if self.running:
            print("[✓] 连点已开启")
            self.click_count = 0  # 重置计数
        else:
            print("[✗] 连点已关闭")
        self.update_gui()

    def click(self):
        """执行单次鼠标左键点击"""
        # 按下鼠标左键
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, None)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

        # 释放鼠标左键
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, None)
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        
        # 更新计数
        self.click_count += 1
        if self.click_count % 10 == 0:  # 每10次更新一次GUI，减少性能开销
            self.update_gui()

    def run_clicker_loop(self):
        """连点器主循环（在独立线程中运行）"""
        # 注册热键
        keyboard.add_hotkey("f6", self.toggle)

        try:
            print("\n程序已启动，等待指令...")
            while True:
                # 检查ESC键退出
                if keyboard.is_pressed("esc"):
                    print("\n程序已退出")
                    if self.gui_root:
                        self.gui_root.quit()
                    break

                # 如果连点开启，执行点击
                if self.running:
                    self.click()
                    time.sleep(self.click_interval)
                else:
                    time.sleep(0.01)  # 空闲时短暂休眠

        except KeyboardInterrupt:
            print("\n程序已退出")
            if self.gui_root:
                self.gui_root.quit()

    def run(self):
        """主入口 - 启动GUI和连点器线程"""
        # 创建GUI
        self.create_gui()
        
        # 在独立线程中运行连点器逻辑
        clicker_thread = threading.Thread(target=self.run_clicker_loop, daemon=True)
        clicker_thread.start()
        
        # 启动GUI主循环
        self.gui_root.mainloop()


if __name__ == "__main__":
    # 创建自动连点器实例，默认间隔50毫秒
    clicker = AutoClicker(click_interval=0.05)
    clicker.run()
