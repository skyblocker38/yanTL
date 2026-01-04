import random
import time


class HumanClock:
    def __init__(self, jitter: float = 0.10):
        """
        jitter=0.10 表示 sleep 基础值上下浮动 ±10%
        """
        self.jitter = jitter

    def sleep(self, base: float):
        if base <= 0:
            return
        factor = 1.0 + random.uniform(-self.jitter, self.jitter)
        time.sleep(max(0, base * factor))