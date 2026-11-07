# dialogue.py
"""台词加载与随机抽取，支持按时段分组。

文件格式（UTF-8）：
- # 开头为注释，空行忽略
- 第一个 [period] 标记之前的行属于通用台词
- [period] 标记之后的行属于该时段，如 [morning] [day] [evening] [night]
"""

import datetime
import os
import random

# 时段：早 / 昼 / 晚 / 深夜
PERIODS = ("morning", "day", "evening", "night")


def current_period(now=None):
    """返回当前时段名。跨时段自动生效，不需要重启程序。"""
    if now is None:
        now = datetime.datetime.now()
    h = now.hour
    if 5 <= h < 11:
        return "morning"
    if 11 <= h < 18:
        return "day"
    if 18 <= h < 23:
        return "evening"
    return "night"   # 23:00 - 5:00


def _default_path():
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "res", "dialogue.txt",
    )


def load_dialogue_file(path=None):
    """解析台词文件，返回 (general_lines, by_period_dict)。

    文件缺失时返回 (["喵~"], {})，保证程序能启动。
    """
    if path is None:
        path = _default_path()
    general = []
    by_period = {}
    current = None
    try:
        with open(path, encoding="utf-8-sig") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    current = line[1:-1].strip().lower()
                    by_period.setdefault(current, [])
                    continue
                if current is None:
                    general.append(line)
                else:
                    by_period[current].append(line)
    except FileNotFoundError:
        general = ["喵~"]
    return general, by_period


class DialoguePool:
    """按时段抽台词。

    - 有 75% 概率从当前时段专属台词选，其余从通用台词选；
      这样深夜会更常催睡，但不会每句都重复。
    - 时段没有专属台词时，退化为只用通用台词。
    - 尽量避免同一时段连续重复。
    """

    SPECIFIC_WEIGHT = 0.75

    def __init__(self, general, by_period):
        self.general = list(general)
        self.by_period = {k: list(v) for k, v in by_period.items()}
        self._last = {}   # 每个时段记住上一次说的，避免连续重复

    def random_line(self, period=None):
        specific = self.by_period.get(period, []) if period else []
        if specific and random.random() < self.SPECIFIC_WEIGHT:
            pool = specific
        else:
            pool = self.general or specific
        if not pool:
            return ""

        last = self._last.get(period)
        for _ in range(10):
            line = random.choice(pool)
            if line != last:
                self._last[period] = line
                return line
        line = pool[0]
        self._last[period] = line
        return line