import copy
import copy
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import yaml

from core.hotkeys import RunControl, install_hotkeys
from core.input_win32 import InputController
from core.timing import HumanClock
from core.window import WindowBinder
from features.macro_combat import BotContext
import features.recover_autofarm as recover_autofarm


SCENE_OPTIONS = {
    "雪原": "xueyuan",
    "黄龙": "huanglong",
    "摩崖洞": "moya",
    "高昌迷宫": "gaochang",
    "清源山洞": "qingyuan",
}


DEFAULT_TITLE_PREFIX = "《新天龙八部》"
DEFAULT_TITLE_SUFFIX = "(原始一区:江湖梦)"


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _load_profile() -> dict:
    path = os.path.join(_base_dir(), "config", "profiles.yaml")
    with open(path, "r", encoding="utf-8") as f:
        profiles = yaml.safe_load(f) or {}
    if "recover_default" not in profiles:
        raise RuntimeError("config/profiles.yaml missing recover_default")
    return copy.deepcopy(profiles["recover_default"])


class QueueWriter:
    def __init__(self, out_queue: queue.Queue):
        self.out_queue = out_queue

    def write(self, text: str):
        if text:
            self.out_queue.put(text)

    def flush(self):
        pass


class RecoverAutofarmApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("死亡恢复+挂机")
        self.root.geometry("760x560")
        self.profile = _load_profile()
        self.control = None
        self.worker = None
        self.log_queue = queue.Queue()
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        sys.stdout = QueueWriter(self.log_queue)
        sys.stderr = QueueWriter(self.log_queue)

        self.vars = {}
        self._build_ui()
        self._poll_log()

    def _add_entry(self, parent, row: int, label: str, key: str, value, width: int = 24):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=8, pady=5)
        var = tk.StringVar(value=str(value))
        entry = ttk.Entry(parent, textvariable=var, width=width)
        entry.grid(row=row, column=1, sticky="w", padx=8, pady=5)
        self.vars[key] = var
        return entry

    def _build_ui(self):
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill="both", expand=True)

        title = ttk.Label(frame, text="死亡恢复+挂机配置", font=("Microsoft YaHei UI", 14, "bold"))
        title.pack(anchor="w", pady=(0, 10))

        form = ttk.LabelFrame(frame, text="运行参数", padding=10)
        form.pack(fill="x")

        self._add_entry(form, 0, "游戏版本", "game_version", "0.08.2313")
        self._add_entry(form, 1, "服务器", "server_name", "原始一区:江湖梦")

        ttk.Label(form, text="目标地图").grid(row=2, column=0, sticky="e", padx=8, pady=5)
        scene_name = next((k for k, v in SCENE_OPTIONS.items() if v == self.profile.get("scene")), "摩崖洞")
        scene_var = tk.StringVar(value=scene_name)
        scene_box = ttk.Combobox(form, textvariable=scene_var, values=list(SCENE_OPTIONS.keys()), state="readonly", width=21)
        scene_box.grid(row=2, column=1, sticky="w", padx=8, pady=5)
        self.vars["scene_name"] = scene_var

        target = self.profile.get("target", {})
        self._add_entry(form, 3, "目标 X", "target_x", target.get("x", 0))
        self._add_entry(form, 4, "目标 Y", "target_y", target.get("y", 0))
        self._add_entry(form, 5, "全程死亡检测(秒)", "death_guard_interval", self.profile.get("death_guard_interval", 0.5))
        self._add_entry(form, 6, "离开地府等待(秒)", "leave_underworld_wait", self.profile.get("leave_underworld_wait", 10))
        self._add_entry(form, 7, "召宠等待(秒)", "summon_wait", self.profile.get("summon_wait", 5))

        button_row = ttk.Frame(frame)
        button_row.pack(fill="x", pady=10)
        self.start_button = ttk.Button(button_row, text="启动", command=self.start)
        self.start_button.pack(side="left", padx=(0, 8))
        ttk.Button(button_row, text="暂停/继续(F8)", command=self.toggle).pack(side="left", padx=(0, 8))
        ttk.Button(button_row, text="停止(F9)", command=self.stop).pack(side="left")

        log_frame = ttk.LabelFrame(frame, text="运行日志", padding=8)
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(log_frame, height=18, wrap="word")
        self.log_text.pack(fill="both", expand=True)

        hint = ttk.Label(frame, text="启动后仍可使用 F8/Pause 暂停继续，F9 停止。")
        hint.pack(anchor="w", pady=(8, 0))

    def _make_config(self) -> tuple[str, dict]:
        cfg = copy.deepcopy(self.profile)
        version = self.vars["game_version"].get().strip()
        server = self.vars["server_name"].get().strip()
        title = f"{DEFAULT_TITLE_PREFIX} {version} ({server})"

        scene_name = self.vars["scene_name"].get()
        cfg["scene"] = SCENE_OPTIONS[scene_name]
        cfg["target"] = {
            "x": int(self.vars["target_x"].get()),
            "y": int(self.vars["target_y"].get()),
        }
        for key in (
            "death_guard_interval",
            "leave_underworld_wait",
            "summon_wait",
        ):
            cfg[key] = float(self.vars[key].get())
        return title, cfg

    def start(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("提示", "程序已经在运行。")
            return

        try:
            title, cfg = self._make_config()
        except Exception as exc:
            messagebox.showerror("参数错误", str(exc))
            return

        os.chdir(_base_dir())
        self.control = RunControl()
        self.control.running = True
        try:
            install_hotkeys(self.control, start_pause_key="F8", stop_key="F9", alt_pause_key="pause")
        except Exception as exc:
            print(f"[WARN] hotkey install failed: {exc}")

        ctx = BotContext(
            binder=WindowBinder(title),
            input=InputController(),
            clock=HumanClock(jitter=float(cfg.get("jitter", 0.10))),
            control=self.control,
            config=cfg,
        )
        self.worker = threading.Thread(target=recover_autofarm.run, args=(ctx,), daemon=True)
        self.worker.start()
        self.start_button.configure(state="disabled")
        print(f"[*] Started recover_autofarm for {title}")

    def toggle(self):
        if self.control:
            self.control.toggle()

    def stop(self):
        if self.control:
            self.control.request_stop()
        self.start_button.configure(state="normal")

    def _poll_log(self):
        while True:
            try:
                text = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.insert("end", text)
            self.log_text.see("end")
        self.root.after(100, self._poll_log)

    def close(self):
        self.stop()
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr
        self.root.destroy()


def main():
    root = tk.Tk()
    app = RecoverAutofarmApp(root)
    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()


if __name__ == "__main__":
    main()
