# pet_window.py
"""窗口设置：无边框、置顶、背景透明、点击穿透。

所有 ctypes / WinAPI 调用集中在本文件，其余文件保持纯 tkinter + Pillow。
"""

import ctypes
from ctypes import wintypes

TRANSPARENT_COLOR = "#ff00ff"

WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WM_NCHITTEST = 0x0084
HTTRANSPARENT = -1
GWL_EXSTYLE = -20
GWLP_WNDPROC = -4

VK_LBUTTON = 0x01


def get_double_click_time_ms():
    """返回系统双击间隔（毫秒）。

    单击确认延迟必须不小于这个值，否则“手慢的双击”会先触发一次单击。
    非 Windows 或调用失败时回退 500（Windows 默认值）。
    """
    try:
        return int(ctypes.windll.user32.GetDoubleClickTime())
    except Exception:
        return 500


def is_left_button_down():
    """查询鼠标左键当前是否物理按下。

    用于兜底：拖拽过程中 ButtonRelease 事件可能丢失（窗口失焦、被其它
    窗口抢事件、Alt+Tab 等），导致状态机卡在 dragging。定时查询物理
    按键状态可以纠正这种状态。

    调用失败时返回 True（保守：认为还按着，不强制中断拖拽）。
    """
    try:
        return bool(ctypes.windll.user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
    except Exception:
        return True


def _make_winapi():
    user32 = ctypes.windll.user32

    if hasattr(user32, "SetWindowLongPtrW"):
        set_long = user32.SetWindowLongPtrW
        get_long = user32.GetWindowLongPtrW
    else:
        set_long = user32.SetWindowLongW
        get_long = user32.GetWindowLongW

    # 窗口过程指针：64 位下必须用 c_void_p 接收，否则会被截断
    set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    set_long.restype = ctypes.c_void_p
    get_long.argtypes = [wintypes.HWND, ctypes.c_int]
    get_long.restype = ctypes.c_void_p

    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long

    # CallWindowProcW 返回 LRESULT（LONG_PTR），64 位下用 c_ssize_t
    user32.CallWindowProcW.argtypes = [
        ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
        wintypes.WPARAM, wintypes.LPARAM,
    ]
    user32.CallWindowProcW.restype = ctypes.c_ssize_t

    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.ScreenToClient.restype = wintypes.BOOL

    return user32, set_long, get_long


_user32 = None
_set_long = None
_get_long = None


def _ensure_user32():
    global _user32, _set_long, _get_long
    if _user32 is None:
        _user32, _set_long, _get_long = _make_winapi()
    return _user32, _set_long, _get_long


def _get_hwnd(root):
    user32, _, _ = _ensure_user32()
    return user32.GetParent(root.winfo_id())


def make_transparent_and_topmost(root):
    root.overrideredirect(True)
    root.wm_attributes("-topmost", True)
    root.wm_attributes("-transparentcolor", TRANSPARENT_COLOR)


def enable_click_through_with_hit_test(root, is_opaque_callback):
    """透明区域鼠标穿透，非透明区域（猫身）可点击。

    is_opaque_callback(x, y) -> bool：窗口内坐标是否落在可点击区域。
    回调内部的异常由回调自己兜底（见 pet_app._is_opaque），
    这里保证任何情况下都给 Windows 一个合法返回值。
    """
    user32, set_long, get_long = _ensure_user32()
    hwnd = _get_hwnd(root)

    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(
        hwnd, GWL_EXSTYLE, ex_style | WS_EX_LAYERED | WS_EX_TRANSPARENT
    )

    # 先读旧过程，再写新过程，不经过 NULL，避免消息派发空窗
    old_wndproc = get_long(hwnd, GWLP_WNDPROC)

    WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t,
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    )

    @WNDPROC
    def new_wndproc(hwnd_, msg, wparam, lparam):
        if msg == WM_NCHITTEST:
            screen_x = ctypes.c_short(lparam & 0xFFFF).value
            screen_y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            pt = wintypes.POINT(screen_x, screen_y)
            user32.ScreenToClient(hwnd_, ctypes.byref(pt))
            if not is_opaque_callback(pt.x, pt.y):
                return HTTRANSPARENT
        return user32.CallWindowProcW(old_wndproc, hwnd_, msg, wparam, lparam)

    set_long(hwnd, GWLP_WNDPROC, ctypes.cast(new_wndproc, ctypes.c_void_p))

    root._new_wndproc = new_wndproc
    root._old_wndproc = old_wndproc