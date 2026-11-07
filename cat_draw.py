# cat_draw.py
"""读取 res/pet.png 并将其处理为可用的桌面宠物图像。

设计要点：
1. 严格二值化抠图：因为 Windows 的 -transparentcolor 机制不支持半透明，
   任何向洋红混合的像素都会显示为粉色描边。所以我们将纯背景设为纯洋红，
   实体边缘直接保留原色，绝不混色。
2. 缓存机制：图片在程序启动首次调用时读取并处理，之后直接返回缓存。
3. 接口与之前完全一致。
"""

import os
from PIL import Image, ImageDraw

# ---- 透明色键（必须与 pet_window.py 保持一致） ----
TRANSPARENT_COLOR = (255, 0, 255)      # 洋红
TRANSPARENT_COLOR_HEX = "#ff00ff"

# ---- 最终输出的画布尺寸 ----
CAT_WIDTH = 200
CAT_HEIGHT = 200

# ---- 表情常量 ----
EXPR_NORMAL = "normal"
EXPR_BLINK = "blink"
EXPR_HAPPY = "happy"
EXPR_SLEEP = "sleep"
EXPRESSIONS = (EXPR_NORMAL, EXPR_BLINK, EXPR_HAPPY, EXPR_SLEEP)

# ---- 抠图阈值 ----
# 只要 RGB 中最小的值大于等于此阈值，就当作背景直接扣成洋红。
# 角色边缘原色直接保留，稍硬也没关系。
BG_THRESH = 225  

# 全局缓存
_cached_image = None


def _generate_fallback_image():
    """如果找不到 res/pet.png，生成一个简单的黄色圆作为兜底。"""
    img = Image.new("RGB", (CAT_WIDTH, CAT_HEIGHT), TRANSPARENT_COLOR)
    draw = ImageDraw.Draw(img)
    draw.ellipse([20, 20, CAT_WIDTH - 20, CAT_HEIGHT - 20], fill=(255, 220, 100))
    return img


def _load_and_process_image():
    """加载图像，等比缩放，并将白底二值化替换为洋红键色。"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    image_path = os.path.join(base_dir, "res", "pet.png")

    if not os.path.exists(image_path):
        print(f"[Warning] 找不到 {image_path}，使用默认黄色圆点替代。")
        return _generate_fallback_image()

    try:
        # 1. 打开并转为 RGBA
        img = Image.open(image_path).convert("RGBA")

        # 2. 缩小以加快遍历速度
        img.thumbnail((400, 400), Image.LANCZOS)

        # 3. 等比例缩放至最大 CAT_WIDTH x CAT_HEIGHT
        ratio = min(CAT_WIDTH / img.width, CAT_HEIGHT / img.height)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)

        # 4. 创建最终输出画布（底色全铺洋红）
        out_img = Image.new("RGB", (CAT_WIDTH, CAT_HEIGHT), TRANSPARENT_COLOR)
        out_px = out_img.load()

        px = img.load()
        offset_x = (CAT_WIDTH - new_size[0]) // 2
        offset_y = (CAT_HEIGHT - new_size[1]) // 2

        # 5. 逐像素严格二值化抠图
        for y in range(new_size[1]):
            for x in range(new_size[0]):
                r, g, b, a = px[x, y]

                # 如果原图有透明通道，且已经非常透明，直接给背景
                if a < 128:
                    continue
                
                # 计算该像素的亮度下限
                m = min(r, g, b)

                # 如果非常接近白色，当做背景，保留底部的洋红
                if m >= BG_THRESH:
                    continue
                else:
                    # 否则保留原色，绝不混合洋红
                    out_px[x + offset_x, y + offset_y] = (r, g, b)

        return out_img

    except Exception as e:
        print(f"[Error] 读取图片失败: {e}，使用默认黄色圆点替代。")
        return _generate_fallback_image()


def draw_cat(expression=EXPR_NORMAL):
    """获取指定表情的图像。图像在首次调用时处理并缓存。"""
    global _cached_image
    if _cached_image is None:
        _cached_image = _load_and_process_image()
    return _cached_image


def render_all_expressions():
    """预渲染所有表情（全部返回同一张处理好的缓存图像）。"""
    img = draw_cat()
    return {expr: img for expr in EXPRESSIONS}