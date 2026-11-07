# animation.py
"""动画状态机。

只维护“表情 + 身体偏移 + 窗口位置”，不碰 tkinter / Pillow / WinAPI。
"""

import math
import random
from dataclasses import dataclass

from cat_draw import EXPR_NORMAL, EXPR_BLINK, EXPR_HAPPY, EXPR_SLEEP


@dataclass
class FrameState:
    expression: str
    body_y_offset: float
    window_x: float
    window_y: float


class PetAnimation:
    BREATH_PERIOD = 3.0
    BREATH_AMPLITUDE = 3.0

    BLINK_DURATION = 0.15
    BLINK_INTERVAL_MIN = 2.0
    BLINK_INTERVAL_MAX = 5.0

    HAPPY_DURATION = 1.0
    JUMP_DURATION = 0.4
    JUMP_HEIGHT = 25.0

    WALK_SPEED = 80.0
    WALK_DURATION_MIN = 3.0
    WALK_DURATION_MAX = 6.0

    GRAVITY = 2000.0
    FALL_MAX_SPEED = 1500.0

    TASKBAR_MARGIN = 80

    def __init__(self, screen_w, screen_h, window_w, window_h,
                 initial_x=None, initial_y=None):
        """initial_x / initial_y：上次保存的窗口位置；None 表示首次运行。

        恢复位置时钳制到当前屏幕内，纵向上限与 _clamp_window() 保持一致
        （ground_y），避免换显示器/改分辨率后窗口停在任务栏区域。
        """
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.window_w = window_w
        self.window_h = window_h

        self.min_x = 0
        self.max_x = screen_w - window_w
        self.min_y = 0
        self.ground_y = screen_h - self.TASKBAR_MARGIN - window_h

        if initial_x is not None and initial_y is not None:
            self.window_x = max(self.min_x, min(float(initial_x), self.max_x))
            # 与拖拽钳制一致：不允许停在 ground_y 以下
            self.window_y = max(self.min_y, min(float(initial_y), self.ground_y))
        else:
            self.window_x = (screen_w - window_w) / 2
            self.window_y = self.ground_y

        self.mode = "normal"

        self.happy_remaining = 0.0
        self.blink_remaining = 0.0
        self.blink_timer = random.uniform(self.BLINK_INTERVAL_MIN,
                                          self.BLINK_INTERVAL_MAX)
        self.jump_elapsed = None
        self._time = 0.0

        self.walk_direction = 1
        self.walk_remaining = 0.0

        self.fall_vy = 0.0

        self._drag_offset_x = 0.0
        self._drag_offset_y = 0.0

    # ---------- 外部动作 ----------
    def on_click(self):
        if self.mode == "sleep":
            self.wake_up()
            return
        if self.mode == "walking":
            self.mode = "normal"
        self.happy_remaining = self.HAPPY_DURATION
        self.jump_elapsed = 0.0

    def on_double_click(self):
        if self.mode == "sleep":
            self.wake_up()
        else:
            self.sleep()

    def sleep(self):
        if self.mode == "falling":
            return
        self.mode = "sleep"
        self.happy_remaining = 0.0
        self.blink_remaining = 0.0
        self.jump_elapsed = None

    def wake_up(self):
        if self.mode == "sleep":
            self.mode = "normal"

    def say_something(self):
        if self.mode == "sleep":
            self.wake_up()
        self.happy_remaining = self.HAPPY_DURATION

    def start_walking(self):
        if self.mode in ("falling", "dragging"):
            return
        if self.mode == "sleep":
            self.wake_up()
        self.mode = "walking"
        self.walk_direction = random.choice([-1, 1])
        self.walk_remaining = random.uniform(self.WALK_DURATION_MIN,
                                             self.WALK_DURATION_MAX)

    # ---------- 拖拽 ----------
    def on_drag_start(self, mouse_x, mouse_y):
        self.mode = "dragging"
        self._drag_offset_x = mouse_x - self.window_x
        self._drag_offset_y = mouse_y - self.window_y

    def on_drag_move(self, mouse_x, mouse_y):
        if self.mode != "dragging":
            return
        self.window_x = mouse_x - self._drag_offset_x
        self.window_y = mouse_y - self._drag_offset_y
        self._clamp_window()

    def on_drag_end(self):
        if self.mode != "dragging":
            return
        self.mode = "falling"
        self.fall_vy = 0.0

    # ---------- 内部 ----------
    def _clamp_window(self):
        self.window_x = max(self.min_x, min(self.window_x, self.max_x))
        self.window_y = max(self.min_y, min(self.window_y, self.ground_y))

    def update(self, dt):
        self._time += dt

        if self.happy_remaining > 0:
            self.happy_remaining = max(0.0, self.happy_remaining - dt)

        if self.blink_remaining > 0:
            self.blink_remaining = max(0.0, self.blink_remaining - dt)
        elif self.mode == "normal" and self.happy_remaining <= 0:
            self.blink_timer -= dt
            if self.blink_timer <= 0:
                self.blink_remaining = self.BLINK_DURATION
                self.blink_timer = random.uniform(self.BLINK_INTERVAL_MIN,
                                                  self.BLINK_INTERVAL_MAX)

        jump_offset = 0.0
        if self.jump_elapsed is not None:
            self.jump_elapsed += dt
            t = self.jump_elapsed / self.JUMP_DURATION
            if t >= 1.0:
                self.jump_elapsed = None
            else:
                jump_offset = -self.JUMP_HEIGHT * 4 * t * (1 - t)

        if self.mode == "sleep":
            breath = math.sin(2 * math.pi * self._time
                              / (self.BREATH_PERIOD * 1.5)) \
                     * (self.BREATH_AMPLITUDE * 0.6)
        else:
            breath = math.sin(2 * math.pi * self._time / self.BREATH_PERIOD) \
                     * self.BREATH_AMPLITUDE

        if self.mode == "walking":
            self.window_x += self.walk_direction * self.WALK_SPEED * dt
            if self.window_x <= self.min_x:
                self.window_x = self.min_x
                self.walk_direction = 1
            elif self.window_x >= self.max_x:
                self.window_x = self.max_x
                self.walk_direction = -1
            self.walk_remaining -= dt
            if self.walk_remaining <= 0:
                self.mode = "normal"

        elif self.mode == "falling":
            self.fall_vy = min(self.fall_vy + self.GRAVITY * dt,
                               self.FALL_MAX_SPEED)
            self.window_y += self.fall_vy * dt
            if self.window_y >= self.ground_y:
                self.window_y = self.ground_y
                self.fall_vy = 0.0
                self.mode = "normal"

        if self.happy_remaining > 0:
            expression = EXPR_HAPPY
        elif self.blink_remaining > 0:
            expression = EXPR_BLINK
        elif self.mode == "sleep":
            expression = EXPR_SLEEP
        else:
            expression = EXPR_NORMAL

        return FrameState(
            expression=expression,
            body_y_offset=breath + jump_offset,
            window_x=self.window_x,
            window_y=self.window_y,
        )