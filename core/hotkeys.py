import keyboard


class RunControl:
    def __init__(self):
        self.running = False
        self.stop = False

    def toggle(self):
        self.running = not self.running
        print("[RUN]" if self.running else "[PAUSE]")

    def request_stop(self):
        self.stop = True
        print("[STOP] 退出请求已发送")


def install_hotkeys(ctrl: RunControl, start_pause_key="F8", stop_key="F9"):
    keyboard.add_hotkey(start_pause_key, ctrl.toggle)
    keyboard.add_hotkey(stop_key, ctrl.request_stop)