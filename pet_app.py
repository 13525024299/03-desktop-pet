# pet_app.py
"""PetApp：窗口、画布、动画循环、交互、气泡、状态持久化。"""

import time
import tkinter as tk

from PIL import ImageTk

from animation import PetAnimation
from cat_draw import (
    CAT_HEIGHT, CAT_WIDTH, EXPRESSIONS,
    TRANSPARENT_COLOR, draw_cat,
)
from dialogue import (
    DialoguePool, current_period, load_dialogue_file,
)
from pet_window import (
    TRANSPARENT_COLOR as WIN_TRANSPARENT_COLOR,
    enable_click_through_with_hit_test,
    get_double_click_time_ms,
    is_left_button_down,
    make_transparent_and_topmost,
)
from storage import load_state, save_state

WINDOW_WIDTH = 340
BUBBLE_AREA_HEIGHT = 120
WINDOW_HEIGHT = CAT_HEIGHT + BUBBLE_AREA_HEIGHT

CAT_BASE_X = (WINDOW_WIDTH - CAT_WIDTH) // 2
CAT_BASE_Y = BUBBLE_AREA_HEIGHT

FPS = 30
FRAME_INTERVAL_MS = int(1000 / FPS)

# 单击确认延迟：不小于系统双击间隔，否则慢速双击会先触发一次单击
CLICK_DELAY_MS = get_double_click_time_ms() + 50

DRAG_THRESHOLD_PX = 5
BUBBLE_DURATION_MS = 3500
SAVE_INTERVAL_SECONDS = 30.0

# 气泡文字排版参数
BUBBLE_FONT_SIZES = (10, 9, 8)       # 从大到小尝试
BUBBLE_PADDING_TOP = 8               # 文字距气泡区顶部
BUBBLE_PADDING_BOTTOM = 8            # 文字底部距猫头至少留这么多
BUBBLE_PADDING_X = 10
BUBBLE_PADDING_Y = 6
BUBBLE_MAX_TEXT_WIDTH = WINDOW_WIDTH - 60


def _create_rounded_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class PetApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("桌面猫")

        make_transparent_and_topmost(self.root)

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        # ---- 加载状态：位置 + 摸猫计数 ----
        state = load_state()
        self.pet_count = int(state.get("pet_count", 0))
        saved_x = state.get("window_x")
        saved_y = state.get("window_y")

        # ---- 动画状态机（初始位置来自存档） ----
        self.animation = PetAnimation(
            screen_w, screen_h, WINDOW_WIDTH, WINDOW_HEIGHT,
            initial_x=saved_x, initial_y=saved_y,
        )

        init_x = int(round(self.animation.window_x))
        init_y = int(round(self.animation.window_y))
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{init_x}+{init_y}")
        self._last_win_x = init_x
        self._last_win_y = init_y

        # ---- 画布 ----
        self.canvas = tk.Canvas(
            self.root, width=WINDOW_WIDTH, height=WINDOW_HEIGHT,
            bg=WIN_TRANSPARENT_COLOR, highlightthickness=0,
        )
        self.canvas.pack()

        # ---- 预渲染四种表情 ----
        self.expression_pil = {}
        self.expression_images = {}
        for expr in EXPRESSIONS:
            pil_img = draw_cat(expr)
            self.expression_pil[expr] = pil_img
            self.expression_images[expr] = ImageTk.PhotoImage(pil_img)

        self.current_expression = EXPRESSIONS[0]
        self.current_body_y_offset = 0.0
        self.image_item = self.canvas.create_image(
            CAT_BASE_X, CAT_BASE_Y, anchor=tk.NW,
            image=self.expression_images[self.current_expression],
        )

        # ---- 台词 ----
        general, by_period = load_dialogue_file()
        self.dialogue = DialoguePool(general, by_period)

        # ---- 气泡 ----
        self._bubble_items = []
        self._bubble_after_id = None

        # ---- 鼠标 ----
        self._press_x = None
        self._press_y = None
        self._dragging = False
        self._pending_click_id = None

        # ---- 事件 ----
        self.canvas.bind("<Button-1>", self._on_button1)
        self.canvas.bind("<Double-Button-1>", self._on_double_button1)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_button_release)
        self.canvas.bind("<Button-3>", self._on_right_click)

        enable_click_through_with_hit_test(self.root, self._is_opaque)

        # ---- 动画循环 ----
        self._running = True
        self._last_time = time.perf_counter()
        self._save_accum = 0.0
        self.root.after(FRAME_INTERVAL_MS, self._tick)

    # ---------- 状态持久化 ----------
    def _snapshot_state(self):
        return {
            "version": 1,
            "window_x": int(round(self.animation.window_x)),
            "window_y": int(round(self.animation.window_y)),
            "pet_count": self.pet_count,
        }

    def _save_state(self):
        save_state(self._snapshot_state())

    def _bump_pet_count(self):
        self.pet_count += 1

    # ---------- 点击穿透判定 ----------
    def _is_opaque(self, x, y):
        """窗口内坐标 (x, y) 是否落在可点击区域。

        这个函数由 C 窗口过程回调，内部任何异常都不会正常传播，
        只会被 ctypes 静默吞掉并返回垃圾值给 Windows。所以这里整体
        try/except：异常时返回 False（按穿透处理），保证 WM_NCHITTEST
        永远拿到一个合法值。
        """
        try:
            if not self._running:
                return False
            # 拖拽时整个窗口都响应，否则呼吸偏移会让鼠标落到透明像素，
            # WM_NCHITTEST 返回穿透，拖拽中途丢失鼠标事件。
            if self.animation.mode == "dragging":
                return True
            img_x = x - CAT_BASE_X
            img_y = y - CAT_BASE_Y - self.current_body_y_offset
            pil_img = self.expression_pil.get(self.current_expression)
            if pil_img is None:
                return False
            if (img_x < 0 or img_y < 0
                    or img_x >= pil_img.width or img_y >= pil_img.height):
                return False
            return pil_img.getpixel((img_x, img_y))[:3] != TRANSPARENT_COLOR
        except Exception:
            # 初始化未完成、对象已销毁、图像数据异常等：一律按穿透处理
            return False

    # ---------- 鼠标 ----------
    def _cancel_pending_click(self):
        if self._pending_click_id is not None:
            try:
                self.root.after_cancel(self._pending_click_id)
            except tk.TclError:
                pass
            self._pending_click_id = None

    def _on_button1(self, event):
        self._press_x = event.x_root
        self._press_y = event.y_root
        self._dragging = False
        self._cancel_pending_click()
        self._pending_click_id = self.root.after(
            CLICK_DELAY_MS, self._do_single_click
        )

    def _on_double_button1(self, event):
        self._cancel_pending_click()
        self._bump_pet_count()
        self.animation.on_double_click()

    def _on_motion(self, event):
        if self._press_x is None:
            return
        dx = event.x_root - self._press_x
        dy = event.y_root - self._press_y
        if not self._dragging and (
            abs(dx) > DRAG_THRESHOLD_PX or abs(dy) > DRAG_THRESHOLD_PX
        ):
            self._dragging = True
            self._cancel_pending_click()   # 拖拽不算单击
            self.animation.on_drag_start(self._press_x, self._press_y)
        if self._dragging:
            self.animation.on_drag_move(event.x_root, event.y_root)
            self._apply_window_position()

    def _on_button_release(self, event):
        if self._dragging:
            self.animation.on_drag_end()
            self._dragging = False
        self._press_x = None
        self._press_y = None

    def _do_single_click(self):
        self._pending_click_id = None
        was_sleeping = self.animation.mode == "sleep"
        self._bump_pet_count()
        self.animation.on_click()
        if not was_sleeping:
            self._show_random_line()

    def _on_right_click(self, event):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(
            label=f"已摸 {self.pet_count} 次",
            state="disabled",
        )
        menu.add_separator()
        menu.add_command(label="说句话", command=self._menu_say)
        menu.add_command(label="散步", command=self._menu_walk)
        menu.add_command(label="睡觉", command=self._menu_sleep)
        menu.add_separator()
        menu.add_command(label="退出", command=self._quit)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                menu.grab_release()
                menu.destroy()
            except tk.TclError:
                pass

    # ---------- 菜单动作 ----------
    def _menu_say(self):
        self.animation.say_something()
        self._show_random_line()

    def _menu_walk(self):
        self.animation.start_walking()

    def _menu_sleep(self):
        if self.animation.mode == "sleep":
            self.animation.wake_up()
        else:
            self.animation.sleep()

    def _quit(self):
        self._running = False
        self._save_state()          # 退出前保存位置和计数
        self._cancel_pending_click()
        if self._bubble_after_id is not None:
            try:
                self.root.after_cancel(self._bubble_after_id)
            except tk.TclError:
                pass
            self._bubble_after_id = None
        self.root.destroy()

    # ---------- 气泡 ----------
    def _show_random_line(self):
        period = current_period()
        self._show_bubble(self.dialogue.random_line(period))

    def _fit_bubble_text(self, cx, text):
        """在气泡区内放下文字。

        策略：按 BUBBLE_FONT_SIZES 从大到小尝试，找到第一个底部不越过
        气泡区的字号；都放不下就用最小字号从尾部截断，加省略号。
        返回创建好的 text item id，完全放不下返回 None。
        """
        max_bottom = BUBBLE_AREA_HEIGHT - BUBBLE_PADDING_BOTTOM

        def try_create(content, size):
            tid = self.canvas.create_text(
                cx, BUBBLE_PADDING_TOP,
                text=content,
                font=("Microsoft YaHei", size),
                width=BUBBLE_MAX_TEXT_WIDTH,
                fill="#333333",
                justify="center",
                anchor="n",          # 从顶部往下排，便于用 bbox 底部判断
            )
            bb = self.canvas.bbox(tid)
            if bb is not None and bb[3] <= max_bottom:
                return tid
            self.canvas.delete(tid)
            return None

        for size in BUBBLE_FONT_SIZES:
            tid = try_create(text, size)
            if tid is not None:
                return tid

        # 最小字号仍超：从尾部截断，加省略号
        smallest = BUBBLE_FONT_SIZES[-1]
        content = text
        while len(content) > 1:
            content = content[:-1]
            tid = try_create(content + "…", smallest)
            if tid is not None:
                return tid
        return None

    def _show_bubble(self, text):
        self._hide_bubble()
        if not text:
            return

        cx = WINDOW_WIDTH // 2
        text_id = self._fit_bubble_text(cx, text)
        if text_id is None:
            return

        bbox = self.canvas.bbox(text_id)
        if bbox is None:
            return

        x1 = bbox[0] - BUBBLE_PADDING_X
        y1 = bbox[1] - BUBBLE_PADDING_Y
        x2 = bbox[2] + BUBBLE_PADDING_X
        y2 = bbox[3] + BUBBLE_PADDING_Y

        rect_id = _create_rounded_rect(
            self.canvas, x1, y1, x2, y2, 8,
            fill="#FFFFFF", outline="#AAAAAA", width=1,
        )
        self.canvas.tag_lower(rect_id, text_id)

        # 小尾巴指向猫头
        tri_id = self.canvas.create_polygon(
            cx - 7, y2 - 1, cx + 7, y2 - 1, cx, y2 + 9,
            fill="#FFFFFF", outline="",
        )
        self.canvas.tag_raise(tri_id, rect_id)

        self._bubble_items = [rect_id, text_id, tri_id]
        self._bubble_after_id = self.root.after(
            BUBBLE_DURATION_MS, self._hide_bubble
        )

    def _hide_bubble(self):
        if self._bubble_after_id is not None:
            try:
                self.root.after_cancel(self._bubble_after_id)
            except tk.TclError:
                pass
            self._bubble_after_id = None
        for item in self._bubble_items:
            self.canvas.delete(item)
        self._bubble_items = []

    # ---------- 窗口位置 ----------
    def _apply_window_position(self):
        x = int(round(self.animation.window_x))
        y = int(round(self.animation.window_y))
        if x != self._last_win_x or y != self._last_win_y:
            self.root.geometry(f"+{x}+{y}")
            self._last_win_x = x
            self._last_win_y = y

    # ---------- 循环 ----------
    def _tick(self):
        if not self._running:
            return
        now = time.perf_counter()
        dt = now - self._last_time
        self._last_time = now
        if dt > 0.1:
            dt = 0.1

        # 兜底：拖拽中 ButtonRelease 事件可能丢失（窗口失焦、被其它窗口
        # 抢走鼠标事件、Alt+Tab 等），状态机会卡在 dragging，整个窗口
        # 永久不穿透。这里定时查询物理左键，已松开就强制结束拖拽。
        if self.animation.mode == "dragging" and not is_left_button_down():
            self._dragging = False
            self._press_x = None
            self._press_y = None
            self.animation.on_drag_end()

        frame = self.animation.update(dt)

        self.current_body_y_offset = frame.body_y_offset
        if frame.expression != self.current_expression:
            self.current_expression = frame.expression
            self.canvas.itemconfig(
                self.image_item,
                image=self.expression_images[frame.expression],
            )
        self.canvas.coords(
            self.image_item, CAT_BASE_X, CAT_BASE_Y + frame.body_y_offset,
        )
        self._apply_window_position()

        self._save_accum += dt
        if self._save_accum >= SAVE_INTERVAL_SECONDS:
            self._save_accum = 0.0
            self._save_state()

        self.root.after(FRAME_INTERVAL_MS, self._tick)

    def run(self):
        self.root.mainloop()