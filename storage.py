# storage.py
"""状态持久化：读写用户目录下的 state.json。

存储位置（按优先级）：
- Windows: %APPDATA%\\DesktopPet\\state.json
- 其它:    ~/.desktop_pet/state.json

状态字段（version 1）：
- window_x, window_y: 上次退出时窗口左上角的屏幕坐标
- pet_count:          累计被摸次数
"""

import json
import os

APP_DIR_NAME = "DesktopPet"
STATE_FILE_NAME = "state.json"

DEFAULT_STATE = {
    "version": 1,
    "window_x": None,   # None 表示首次运行，用默认位置
    "window_y": None,
    "pet_count": 0,
}


def _state_dir():
    """返回状态目录，不存在时创建。"""
    appdata = os.environ.get("APPDATA")
    if appdata:
        path = os.path.join(appdata, APP_DIR_NAME)
    else:
        path = os.path.join(os.path.expanduser("~"), ".desktop_pet")
    os.makedirs(path, exist_ok=True)
    return path


def state_path():
    """返回状态文件完整路径（调试/手动查看时用）。"""
    return os.path.join(_state_dir(), STATE_FILE_NAME)


def load_state():
    """读取状态；文件不存在或损坏时返回默认值，保证程序能启动。"""
    state = dict(DEFAULT_STATE)
    path = state_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return state

    if not isinstance(data, dict):
        return state

    # 只接受已知字段，忽略未知字段（向前兼容）
    for key in DEFAULT_STATE:
        if key in data:
            state[key] = data[key]

    # 类型校验，防止手动改坏文件导致崩溃
    if not isinstance(state.get("pet_count"), int):
        state["pet_count"] = 0
    for key in ("window_x", "window_y"):
        v = state.get(key)
        if v is not None and not isinstance(v, (int, float)):
            state[key] = None
    return state


def save_state(state):
    """原子写入：先写 .tmp 再 os.replace，避免中途崩溃损坏 JSON。"""
    path = state_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError:
        # 无权限/磁盘满等：静默失败，不影响主程序
        pass