#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2026 Pluto Yang
# SPDX-License-Identifier: GPL-3.0-or-later
"""六边形网格俄罗斯方块 (Hex Tetris) —— 六边形棋盘 / 斜线消行

网格结构:
    - 格子是"平顶(flat-top)"六边形，按轴向坐标 (q, r) 排列，列是竖直直线。
    - 整个棋盘本身也是一个六边形: |q| <= 7, |r| <= 11, |s| <= 11  (s = -q - r)。
      六条边依次是 16, 8, 8, 16, 8, 8 格 —— 即 8x8x16x8x8x16，
      左右两条竖边（q = ±7 两列）各 16 格。共 289 格。
      最高的一列（q = 0）有 23 格，所以棋盘纵高 23 个行距、横宽 23 个半宽。
    - 消行: 与底边平行的斜线, 且分左右两半 (左 8 列 / 右 8 列), 每行最多 8 格。
          左半 (q = -7..0): r = 常数
          右半 (q =  0..7): s = -q-r = 常数
      只有长度正好 8 格的整行填满才消除; 靠近顶点、不足 8 格的斜线不消除。
      消行后同一列中上方的方块整体下落 (下落格数 = 该列中被消去的格子数)。
      竖直列不消。

移动/下落:
    - 重力: 同一列里行 +1，axial Δ(0, +1)，始终垂直、每次 1 格。
    - 左右: 到相邻列必然是斜下 —— 左 = (-1, +1)，右 = (+1, 0)。

窗口可自由缩放，棋盘会自动缩放以完整放进窗口。

运行:  .venv/bin/python hex_tetris.py
"""

import array
import json
import locale
import math
import os
import random

import pygame

try:                     # 只用于探测字形覆盖，画字仍然走 pygame.font
    from pygame import freetype as _freetype
except ImportError:
    _freetype = None

# ------------------------------------------------------------------ 棋盘拓扑
# 棋盘六边形的三条"半轴"：|q|<=Q_MAX, |r|<=R_MAX, |s|<=S_MAX
Q_MAX, R_MAX, S_MAX = 7, 11, 11
BOARD_ROWS = 2 * R_MAX + 1          # 最高一列的格数 = 23
BOARD_SPAN = 3 * Q_MAX + 2          # 棋盘宽/高都等于 BOARD_SPAN * S = 23*S

FPS = 60

# 最高分记录：Top 5，保存在脚本同目录，游戏结束可输入名字
HIGHSCORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "highscores.json")
HIGHSCORE_LIMIT = 5
HIGHSCORE_NAME_LIMIT = 10

# ------------------------------------------------------------------ 界面语言
# 按系统 locale 选择中文/英文；可用环境变量 HEX_TETRIS_LANG=zh|en 覆盖。
STRINGS = {
    "zh": {
        "caption": "Hex Tetris - 六边形俄罗斯方块",
        "subtitle": "六边形棋盘 · 斜线消行",
        "score": "得分",
        "best": "最高分",
        "lines": "消行",
        "level": "等级",
        "help": [
            "←/→  A/D   斜下移动",
            "↑ / X      顺时针旋转",
            "Z          逆时针旋转",
            "↓ / S      加速下降",
            "空格       硬降",
            "Alt+Enter  全屏切换",
            "M          音效开关",
            "P 暂停   R 重开   Esc 退出",
        ],
        "no_records": "暂无记录",
        "paused": "已暂停",
        "resume": "按 P 继续",
        "game_over": "游戏结束",
        "score_line": "得分 %d",
        "new_record": "新纪录！输入名字（最多 %d 字符）",
        "name_keys": "Enter 确认 · Backspace 删除",
        "rank": "第 %d 名 · 最高分 %d",
        "best_only": "最高分 %d",
        "restart": "按 R 重开 · Esc 退出",
        "anon": "无名玩家",
    },
    "en": {
        "caption": "Hex Tetris",
        "subtitle": "Hex board · diagonal clears",
        "score": "SCORE",
        "best": "BEST",
        "lines": "LINES",
        "level": "LEVEL",
        "help": [
            "←/→  A/D   Move",
            "↑ / X      Rotate CW",
            "Z          Rotate CCW",
            "↓ / S      Soft drop",
            "Space      Hard drop",
            "Alt+Enter  Fullscreen",
            "M          Mute",
            "P Pause  R Restart  Esc Quit",
        ],
        "no_records": "No records yet",
        "paused": "PAUSED",
        "resume": "Press P to resume",
        "game_over": "GAME OVER",
        "score_line": "Score %d",
        "new_record": "New record! Enter your name (max %d chars)",
        "name_keys": "Enter confirm · Backspace delete",
        "rank": "Rank %d · Best %d",
        "best_only": "Best %d",
        "restart": "Press R to restart · Esc to quit",
        "anon": "Anonymous",
    },
}


def detect_lang():
    """HEX_TETRIS_LANG / LC_ALL / LC_MESSAGES / LANG 依次生效，非 zh 视为英文。"""
    for var in ("HEX_TETRIS_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(var, "").lower()
        if value.startswith(("zh", "en")):
            return "zh" if value.startswith("zh") else "en"
    try:
        value = (locale.getlocale()[0] or "").lower()
    except (TypeError, ValueError):
        value = ""
    return "zh" if value.startswith("zh") else "en"


# TEXT / DEFAULT_PLAYER_NAME 在字体探测之后确定（见文件下方的 _build_text），
# 因为选不到中文字体时要退回英文界面。

# 十种独立方块（轴向坐标），每种 4 格。六边形网格上四格连通块共 10 种
# （旋转去重、镜像另算，穷举见 find_pieces.py）：
#   I 直线 / O 菱形 / N 折线 / Y 三臂（自身镜像）
#   T、L 互为镜像；J、R 互为镜像；S、Z 互为镜像
PIECES = {
    "I": [(0, 0), (1, 0), (2, 0), (3, 0)],
    "O": [(0, 0), (1, 0), (0, 1), (1, 1)],
    "T": [(0, 0), (1, 0), (2, 0), (1, -1)],
    "L": [(0, 0), (1, 0), (2, 0), (0, 1)],
    "J": [(0, 0), (1, 0), (2, 0), (2, 1)],
    "S": [(0, 0), (1, 0), (1, 1), (2, 1)],
    "Z": [(0, 0), (0, 1), (1, 1), (1, 2)],
    "R": [(0, 0), (0, 1), (0, 2), (1, 2)],
    "N": [(0, 0), (0, 1), (1, 1), (2, 0)],
    "Y": [(0, 1), (1, 1), (1, 2), (2, 0)],
}
COLORS = {
    "I": (80, 220, 230),
    "O": (240, 210, 70),
    "T": (170, 90, 220),
    "L": (240, 150, 60),
    "J": (70, 120, 230),
    "S": (90, 200, 90),
    "Z": (230, 80, 80),
    "R": (60, 190, 160),
    "N": (235, 120, 200),
    "Y": (170, 210, 80),
}

# ------------------------------------------------------------------ 音效
# 所有音效都用代码合成（正弦/方波 + 衰减包络），不加载任何音频文件。
# 没有可用音频设备时自动静音；HEX_TETRIS_SOUND=0 可强制关闭。
SOUND_ENABLED = os.environ.get("HEX_TETRIS_SOUND", "1").lower() not in (
    "0", "off", "false", "no")
SOUND_MASTER = 0.7


def _note(freq, dur, volume=0.5, slide=None, kind="sine"):
    """一个音符：频率 Hz、时长秒、音量、可选滑音终点、波形。"""
    return (freq, dur, volume, slide, kind)


SOUND_SPECS = {
    "move": [_note(240, 0.035, 0.22, kind="square")],
    "rotate": [_note(360, 0.04, 0.22, kind="square"),
               _note(500, 0.03, 0.18, kind="square")],
    "lock": [_note(190, 0.09, 0.5, slide=90)],
    "clear1": [_note(523, 0.07, 0.4), _note(784, 0.12, 0.4)],
    "clear2": [_note(523, 0.06, 0.4), _note(659, 0.06, 0.4),
               _note(784, 0.14, 0.4)],
    "clear3": [_note(523, 0.06, 0.4), _note(659, 0.06, 0.4),
               _note(784, 0.06, 0.4), _note(1047, 0.16, 0.4)],
    "level": [_note(0, 0.22, 0.0), _note(659, 0.09, 0.4),
              _note(988, 0.16, 0.4)],
    "over": [_note(392, 0.16, 0.4, slide=330),
             _note(262, 0.32, 0.4, slide=110)],
    "pause": [_note(520, 0.05, 0.28, kind="square")],
}


def _build_sound(parts, rate, channels):
    """把音符序列合成为 mixer 当前格式的 Sound。"""
    data = array.array("h")
    for freq, dur, volume, slide, kind in parts:
        n = max(1, int(rate * dur))
        end = freq if slide is None else slide
        phase = 0.0
        attack = max(1, int(rate * 0.004))     # 4ms 淡入，避免爆音
        for i in range(n):
            t = i / n
            phase += math.tau * (freq + (end - freq) * t) / rate
            wave = math.sin(phase)
            if kind == "square":
                wave = 0.65 if wave >= 0 else -0.65
            env = min(1.0, i / attack) * (1.0 - t) ** 1.6
            value = int(max(-1.0, min(1.0, wave * env * volume * SOUND_MASTER)) * 32767)
            for _ in range(channels):
                data.append(value)
    return pygame.mixer.Sound(buffer=data.tobytes())


class SoundBank:
    """按名字播放音效；无音频设备时所有调用都是空操作。"""

    def __init__(self, enabled=True):
        self.enabled = enabled and SOUND_ENABLED
        self.sounds = {}
        if not self.enabled:
            return
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            init = pygame.mixer.get_init()
            if not init or abs(init[1]) != 16:      # 只合成 16 位采样
                self.enabled = False
                return
            rate, _, channels = init
            self.sounds = {name: _build_sound(parts, rate, abs(channels))
                           for name, parts in SOUND_SPECS.items()}
        except (pygame.error, ValueError):
            self.enabled = False
            self.sounds = {}

    def play(self, name):
        if not self.enabled:
            return
        sound = self.sounds.get(name)
        if sound is not None:
            sound.play()

    def toggle(self):
        if not self.sounds:
            return self.enabled
        self.enabled = not self.enabled
        if not self.enabled:
            try:
                pygame.mixer.stop()
            except pygame.error:
                pass
        return self.enabled


BG_COLOR = (10, 12, 17)
PANEL_COLOR = (16, 20, 27)
EMPTY_LINE = (46, 78, 66)
BORDER_COLOR = (120, 230, 190)
TEXT_DIM = (150, 175, 165)

# 三个移动方向（轴向增量）。向下 = 同一列 +1 行，垂直下落 1 格。
DOWN = (0, 1)
LEFT = (-1, 1)      # 左下
RIGHT = (1, 0)      # 右下
# 旋转踢墙（轴向，均为刚性平移）
KICKS = [(0, 0), (-1, 1), (1, 0), (0, 1), (0, -1), (-1, 0), (1, -1)]

GRAVITY_BASE = 1040
GRAVITY_MIN = 180
LOCK_DELAY = 840
DAS = 340
DAS_REPEAT = 110
SOFT_DROP_MS = 55
# 落定后的短暂停顿：新方块在这段时间内不响应按键、不下落，
# 避免按住下键 / 连按空格时一下连掉两块。
SPAWN_PAUSE = 150

# 布局
MARGIN = 24
PANEL_W = 290
GAP = 24
PANEL_DESIGN_H = 600   # 面板内容完整显示所需的高度；更矮时字号/行距一起等比缩小
S_MIN, HEX_MAX = 7.0, 40.0

# ------------------------------------------------------- 字体探测与降级
# 不写死任何字体路径：pygame.font.get_fonts() 给出的就是系统已注册的字体
# （Linux 走 fontconfig、Windows 走注册表、macOS 扫字体目录），再用 freetype
# 实测字形——能画出中文才算数。都没有就退回英文界面，缺箭头就换成 ASCII，
# 避免屏幕上一堆豆腐块。

# 家族名按偏好排序（pygame 已归一化为小写无空格），只用来决定先试谁；
# 都不命中时会暴力扫描系统里的其余字体，所以这里漏了也不会漏字体。
FONT_NAME_KEYWORDS = (
    "microsoftyahei", "yahei",                          # 微软雅黑
    "pingfang", "hiragino",                             # macOS
    "notosanscjk", "notoserifcjk", "sourcehan", "cjk",
    "wenquanyi", "wqy", "droidsansfallback",
    "simhei", "simsun", "heiti", "songti", "kaiti",
    "dengxian", "microsoftjhenghei", "msjh", "uming", "ukai",
)

# 细体/极细体做 HUD 太刺眼，排在常规字重之后；…UI 变体在 fontconfig 里
# 常常指向某个奇怪的权重（本机 “Microsoft YaHei UI” 就落到 Light）
LIGHT_STYLES = ("light", "thin", "ultralight", "extralight", "hairline")

CJK_PROBE = "中文棋盘六边形方块消行得分等级暂停音效开关重开退出"
ARROW_PROBE = "←↑→↓"
GLYPH_FALLBACK = {"←": "<", "→": ">", "↑": "^", "↓": "v",
                  "↔": "<>", "…": "..."}

_FONT_CHOICE = None   # (path 或 None, 是否有中文字形)


def _has_glyphs(path, sample):
    """用 freetype 实测字形：某个字符拿不到度量，就说明字体里没有它。

    光看度量不够——彩色/符号字体（如 NotoColorEmoji）会给任何字符都返度量，
    所以还要求样本里前几个字真能画出不同的图（位图字体则会直接报错）。
    freetype 整个模块不存在时无法探测，只能相信字体本身，返回 True。
    """
    if _freetype is None:
        return True
    try:
        _freetype.init()   # 模块被导入时 pygame.init() 可能还没跑
        face = _freetype.Font(path, 16)
        if any(face.get_metrics(ch) == [None] for ch in sample):
            return False
        if len(sample) < 2:
            return True
        shots = {pygame.image.tostring(face.render(ch)[0], "RGBA")
                 for ch in sample[:3]}
        return len(shots) > 1
    except (OSError, RuntimeError, ValueError, pygame.error):
        return False       # 打不开或画不出来：当这个字体不能用，换下一个


def _font_paths():
    """依次给出系统字体文件：先关键词命中的常规字重，再其余，最后细体。"""
    try:
        pygame.font.init()
        names = pygame.font.get_fonts()
    except pygame.error:
        names = []

    def styled(name):
        return name.endswith("ui") or any(s in name for s in LIGHT_STYLES)

    order, used = [], set()
    for keyword in FONT_NAME_KEYWORDS:
        for name in names:
            if name in used or styled(name):
                continue
            if keyword in name:
                used.add(name)
                order.append(name)
    rest = [n for n in names if n not in used]
    order.extend(n for n in rest if not styled(n))
    order.extend(n for n in rest if styled(n))
    seen = set()
    for name in order:
        path = pygame.font.match_font(name)
        if path and path not in seen:
            seen.add(path)
            yield path


def resolve_font():
    """挑一个能满足需求的字体，结果缓存。返回 (path, 支持中文)。

    优先“中文 + 箭头”都有的，退一步只要中文，最后才用 pygame 自带字体
    （path 为 None）。
    """
    global _FONT_CHOICE
    if _FONT_CHOICE is None:
        cjk_only = None
        for path in _font_paths():
            if not _has_glyphs(path, CJK_PROBE):
                continue
            if _has_glyphs(path, ARROW_PROBE):
                _FONT_CHOICE = (path, True)
                break
            if cjk_only is None:
                cjk_only = (path, True)
        if _FONT_CHOICE is None:
            _FONT_CHOICE = cjk_only or (None, False)
    return _FONT_CHOICE


def _glyph_table():
    """当前字体缺哪些字形，就给这些字符准备 ASCII 替身。"""
    path = resolve_font()[0]
    return {bad: good for bad, good in GLYPH_FALLBACK.items()
            if not _has_glyphs(path, bad)}


def _replace_glyphs(value, table):
    if isinstance(value, str):
        for bad, good in table.items():
            value = value.replace(bad, good)
        return value
    if isinstance(value, list):
        return [_replace_glyphs(v, table) for v in value]
    return value


def _build_text():
    """选文案语言：locale 要中文但机器没有中文字体时，退回英文。"""
    lang = detect_lang()
    if lang == "zh" and not resolve_font()[1]:
        lang = "en"
    text = dict(STRINGS[lang])
    table = _glyph_table()
    return {k: _replace_glyphs(v, table) for k, v in text.items()}


TEXT = _build_text()
DEFAULT_PLAYER_NAME = TEXT["anon"]

# ------------------------------------------------------------------ 棋盘数据
BOARD_CELLS = [(q, r)
               for q in range(-Q_MAX, Q_MAX + 1)
               for r in range(-R_MAX, R_MAX + 1)
               if abs(q + r) <= S_MAX]
BOARD_SET = set(BOARD_CELLS)

# 消行用的“行”: 与底边 (左下 / 右下斜边) 平行, 各取半边, 每行最多 8 格。
#   左 8 列 (q = -7..0): r = 常数 的斜线
#   右 8 列 (q =  0..7): s = -q-r = 常数 的斜线
# 竖直列不参与消行。
LEFT_ROWS = [[(q, r) for q in range(-Q_MAX, 1) if (q, r) in BOARD_SET]
             for r in range(-R_MAX, R_MAX + 1)]
RIGHT_ROWS = [[(q, -s - q) for q in range(0, Q_MAX + 1) if (q, -s - q) in BOARD_SET]
              for s in range(-S_MAX, S_MAX + 1)]
_seen_rows, ROWS = set(), []
for _row in LEFT_ROWS + RIGHT_ROWS:
    _key = frozenset(_row)
    if _row and _key not in _seen_rows:
        _seen_rows.add(_key)
        ROWS.append(_row)


# --------------------------------------------------------------- 自适应几何
def configure(win_w, win_h):
    """根据窗口大小算出格距/原点/面板位置，保证整个六边形棋盘放进窗口。"""
    global WIN_W, WIN_H, S, HEX_W, HEX_H, ORIGIN_X, ORIGIN_Y, PANEL_RECT
    WIN_W = max(520, int(win_w))
    WIN_H = max(360, int(win_h))
    s_by_height = (WIN_H - 2 * MARGIN) / (BOARD_ROWS * math.sqrt(3))
    s_by_width = (WIN_W - 2 * MARGIN - GAP - PANEL_W) / BOARD_SPAN
    S = max(S_MIN, min(HEX_MAX, s_by_height, s_by_width))
    HEX_W = 1.5 * S
    HEX_H = math.sqrt(3) * S
    # 棋盘与记分牌始终靠在一起，作为一个整组在窗口里水平居中
    group_w = BOARD_SPAN * S + GAP + PANEL_W
    left = max(MARGIN, (WIN_W - group_w) / 2)
    ORIGIN_X = left + BOARD_SPAN * S / 2
    ORIGIN_Y = WIN_H / 2
    PANEL_RECT = pygame.Rect(int(left + BOARD_SPAN * S + GAP), MARGIN,
                             PANEL_W, WIN_H - 2 * MARGIN)


# 默认布局（导入即可用；main() 会按屏幕大小覆盖）
configure(900, 880)


# ------------------------------------------------------------------ 坐标工具
def rot_cw(cells):
    """轴向坐标绕原点顺时针旋转 60°。"""
    return [(-r, q + r) for q, r in cells]


def piece_pivot(name):
    """方块的旋转枢轴: 离重心最近的自身格子。

    六边形网格上只有格子中心是合法的 60° 旋转中心（绕顶点转会把格子
    甩到半格位置），所以枢轴只能选格子。取离重心最近的一格，旋转时
    方块就不会大幅甩出去。
    """
    cells = PIECES[name]
    cq = sum(q for q, _ in cells) / len(cells)
    cr = sum(r for _, r in cells) / len(cells)

    def key(c):
        q, r = c
        d = (q - cq) ** 2 + (r - cr) ** 2
        far = max(abs(q - a) + abs(r - b) + abs((a + b) - (q + r)) for a, b in cells)
        return (round(d, 9), far, c)

    return min(cells, key=key)


PIVOTS = {name: piece_pivot(name) for name in PIECES}


def piece_rel(name, rot):
    """方块各格相对枢轴的轴向坐标（已旋转 rot 个 60°）。"""
    pq, pr = PIVOTS[name]
    cells = [(q - pq, r - pr) for q, r in PIECES[name]]
    for _ in range(rot % 6):
        cells = rot_cw(cells)
    return cells


def cell_center(q, r):
    return (ORIGIN_X + HEX_W * q,
            ORIGIN_Y + HEX_H * (r + q / 2.0))


def hex_points(cx, cy, s):
    """平顶六边形的 6 个顶点。"""
    return [(cx + s * math.cos(math.radians(60 * i)),
             cy + s * math.sin(math.radians(60 * i))) for i in range(6)]


def clamp(color):
    return tuple(max(0, min(255, int(v))) for v in color)


def lighten(color, f):
    return clamp((color[0] * f, color[1] * f, color[2] * f))


def darken(color, f):
    return lighten(color, f)


def draw_hex(surf, cx, cy, s, fill=None, outline=None, width=2):
    pts = hex_points(cx, cy, s)
    if fill:
        pygame.draw.polygon(surf, fill, pts)
    if outline:
        pygame.draw.polygon(surf, outline, pts, width)


def draw_cell(surf, cx, cy, s, color):
    pygame.draw.polygon(surf, color, hex_points(cx, cy, s))
    pygame.draw.polygon(surf, lighten(color, 1.35), hex_points(cx, cy, s * 0.58))
    pygame.draw.polygon(surf, darken(color, 0.45), hex_points(cx, cy, s), 2)


def clear_full_lines(filled):
    """原地消除所有被填满的整行（8 格）, 上方方块整体下落, 返回消除的行数。

    靠近棋盘顶端顶点、不足 8 格的斜线不参与消除。
    """
    full = [row for row in ROWS if len(row) == 8 and all(c in filled for c in row)]
    if not full:
        return 0

    removed = set()
    for row in full:
        removed.update(row)

    removed_by_col = {}
    for q, r in removed:
        removed_by_col.setdefault(q, []).append(r)
    for c in removed:
        filled.pop(c, None)

    # 同一列中位于被消格子上方的方块, 下落格数 = 该列中被消去的格子数
    settled = {}
    for (q, r), color in filled.items():
        down = sum(1 for rr in removed_by_col.get(q, ()) if rr > r)
        settled[(q, r + down)] = color
    filled.clear()
    filled.update(settled)
    return len(full)


def load_highscores():
    """读取 Top 5 记录；文件缺失/损坏时返回空列表。"""
    try:
        with open(HIGHSCORE_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return []
    if isinstance(raw, dict):
        raw = raw.get("scores", [])
    if not isinstance(raw, list):
        return []

    scores = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            score = int(item.get("score", 0))
        except (TypeError, ValueError):
            continue
        if score <= 0:
            continue
        name = str(item.get("name") or "").strip()[:HIGHSCORE_NAME_LIMIT]
        scores.append({"name": name or DEFAULT_PLAYER_NAME, "score": score})
    scores.sort(key=lambda e: -e["score"])
    return scores[:HIGHSCORE_LIMIT]


def save_highscores(scores):
    """原子写入记录；失败时静默忽略，不影响游戏。"""
    tmp = HIGHSCORE_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"scores": scores}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, HIGHSCORE_FILE)
    except OSError:
        pass


def fit_text(s, font, max_w):
    """把文字截短到 max_w 像素内，超出部分用省略号。"""
    if font.size(s)[0] <= max_w:
        return s
    while s and font.size(s + "…")[0] > max_w:
        s = s[:-1]
    return s + "…"


def load_font(size):
    path = resolve_font()[0]
    if path:
        try:
            return pygame.font.Font(path, size)
        except pygame.error:
            pass
    return pygame.font.Font(None, size)


# --------------------------------------------------------------------- 游戏
class Game:
    def __init__(self, screen):
        self.screen = screen
        self.f_title = load_font(34)
        self.f_big = load_font(26)
        self.f_mid = load_font(20)
        self.f_small = load_font(16)
        self.font_cache = {}
        self.highscores = load_highscores()
        self.sounds = SoundBank()
        self.name_entry = None
        self.last_rank = None
        self.reset()

    # -- 状态 ---------------------------------------------------------------
    def reset(self):
        self.filled = {}
        self.score = 0
        self.lines = 0
        self.level = 1
        self.game_over = False
        self.paused = False
        self.name_entry = None
        self.last_rank = None
        self.bag = []
        self.drop_timer = 0
        self.lock_timer = 0
        self.spawn_timer = 0
        self.das_dir = 0
        self.das_timer = 0
        self.piece = self.spawn(self.draw_name())
        self.next_name = self.draw_name()
        if self.piece is None:
            self.finish_game()

    def draw_name(self):
        if not self.bag:
            self.bag = list(PIECES)
            random.shuffle(self.bag)
        return self.bag.pop()

    def spawn(self, name):
        """在棋盘顶部居中（q = 0）的固定位置生成方块。

        先把方块放到能完整容纳它的最高一行；若该出生位置已被占用则返回 None,
        由调用方判定游戏结束。
        """
        rel = piece_rel(name, 0)
        for ar in range(-S_MAX - 4, R_MAX + 1):
            cells = [(q, r + ar) for q, r in rel]
            if all(c in BOARD_SET for c in cells):
                break
        else:
            return None
        if any(c in self.filled for c in cells):
            return None
        return {"name": name, "rot": 0, "q": 0, "r": ar}

    def cells_at(self, piece, q, r):
        return [(cq + q, cr + r) for cq, cr in piece_rel(piece["name"], piece["rot"])]

    def cur_cells(self):
        return self.cells_at(self.piece, self.piece["q"], self.piece["r"])

    def fits(self, cells):
        return all(c in BOARD_SET and c not in self.filled for c in cells)

    # -- 操作 ---------------------------------------------------------------
    def try_move(self, delta):
        if self.piece is None:
            return False
        dq, dr = delta
        if self.fits(self.cells_at(self.piece, self.piece["q"] + dq, self.piece["r"] + dr)):
            self.piece["q"] += dq
            self.piece["r"] += dr
            self.lock_timer = 0
            if delta != DOWN:
                self.sounds.play("move")
            return True
        return False

    def try_rotate(self, direction):
        if self.piece is None:
            return False
        p = self.piece
        new_rot = (p["rot"] + (1 if direction > 0 else -1)) % 6
        rel = piece_rel(p["name"], new_rot)
        for dq, dr in KICKS:
            cells = [(cq + p["q"] + dq, cr + p["r"] + dr) for cq, cr in rel]
            if self.fits(cells):
                p["rot"] = new_rot
                p["q"] += dq
                p["r"] += dr
                self.lock_timer = 0
                self.sounds.play("rotate")
                return True
        return False

    def can_fall(self):
        dq, dr = DOWN
        return self.fits(self.cells_at(self.piece, self.piece["q"] + dq, self.piece["r"] + dr))

    def landing_anchor(self):
        p = self.piece
        q, r = p["q"], p["r"]
        dq, dr = DOWN
        while self.fits(self.cells_at(p, q + dq, r + dr)):
            q += dq
            r += dr
        return q, r

    def hard_drop(self):
        if self.piece is None:
            return
        p = self.piece
        q, r = self.landing_anchor()
        self.score += max(0, r - p["r"]) * 2
        p["q"], p["r"] = q, r
        self.lock()

    def gravity_ms(self):
        return max(GRAVITY_MIN, GRAVITY_BASE - (self.level - 1) * 90)

    def lock(self):
        for c in self.cur_cells():
            self.filled[c] = COLORS[self.piece["name"]]

        n = clear_full_lines(self.filled)
        leveled = False
        if n:
            score_table = {1: 100, 2: 400, 3: 900}
            self.lines += n
            self.score += score_table.get(n, n * n * 100) * self.level
            new_level = 1 + self.lines // 10
            leveled = new_level > self.level
            self.level = new_level
            self.sounds.play("clear3" if n >= 3 else f"clear{n}")
        else:
            self.sounds.play("lock")
        if leveled:
            self.sounds.play("level")

        self.piece = self.spawn(self.next_name)
        self.next_name = self.draw_name()
        self.drop_timer = 0
        self.lock_timer = 0
        self.spawn_timer = SPAWN_PAUSE
        if self.piece is None:
            self.finish_game()

    # -- 最高分 -------------------------------------------------------------
    def best_score(self):
        return self.highscores[0]["score"] if self.highscores else 0

    def qualifies(self):
        """当前得分能否进入 Top 5。"""
        if self.score <= 0:
            return False
        if len(self.highscores) < HIGHSCORE_LIMIT:
            return True
        return self.score > self.highscores[-1]["score"]

    def finish_game(self):
        self.sounds.play("over")
        self.game_over = True
        self.name_entry = "" if self.qualifies() else None

    def submit_name(self):
        name = self.name_entry.strip()[:HIGHSCORE_NAME_LIMIT] or DEFAULT_PLAYER_NAME
        entry = {"name": name, "score": self.score}
        scores = sorted(self.highscores + [entry], key=lambda e: -e["score"])
        scores = scores[:HIGHSCORE_LIMIT]
        self.last_rank = next((i + 1 for i, e in enumerate(scores) if e is entry), None)
        if self.last_rank is not None:
            self.highscores = scores
            save_highscores(scores)
        self.name_entry = None

    # -- 主循环回调 ---------------------------------------------------------
    def on_key(self, key, text=""):
        if key == pygame.K_ESCAPE:
            return False
        if self.name_entry is not None:
            if key == pygame.K_BACKSPACE:
                self.name_entry = self.name_entry[:-1]
            elif key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.submit_name()
            elif text and text.isprintable() and len(self.name_entry) < HIGHSCORE_NAME_LIMIT:
                self.name_entry += text
            return True
        if key == pygame.K_m:
            self.sounds.toggle()
            return True
        if key == pygame.K_r:
            self.reset()
            return True
        if self.game_over:
            return True
        if key == pygame.K_p:
            self.paused = not self.paused
            self.sounds.play("pause")
            return True
        if self.paused:
            return True
        if self.spawn_timer > 0:
            return True

        if key in (pygame.K_LEFT, pygame.K_a):
            self.try_move(LEFT)
            self.das_dir, self.das_timer = -1, DAS
        elif key in (pygame.K_RIGHT, pygame.K_d):
            self.try_move(RIGHT)
            self.das_dir, self.das_timer = 1, DAS
        elif key in (pygame.K_UP, pygame.K_x, pygame.K_w):
            self.try_rotate(1)
        elif key == pygame.K_z:
            self.try_rotate(-1)
        elif key == pygame.K_SPACE:
            self.hard_drop()
        return True

    def update(self, dt):
        if self.game_over or self.paused:
            return

        if self.spawn_timer > 0:
            self.spawn_timer = max(0, self.spawn_timer - dt)
            return

        if self.das_dir:
            self.das_timer -= dt
            if self.das_timer <= 0:
                self.das_timer = DAS_REPEAT
                self.try_move(LEFT if self.das_dir < 0 else RIGHT)

        keys = pygame.key.get_pressed()
        soft = keys[pygame.K_DOWN] or keys[pygame.K_s]
        interval = SOFT_DROP_MS if soft else self.gravity_ms()

        if self.can_fall():
            self.drop_timer += dt
            if self.drop_timer >= interval:
                self.drop_timer = 0
                self.try_move(DOWN)
                if soft:
                    self.score += 1
        else:
            self.lock_timer += dt
            if self.lock_timer >= LOCK_DELAY:
                self.lock()

    # -- 绘制 ---------------------------------------------------------------
    def font(self, size):
        """按字号取字体（面板随窗口高度缩放时复用）。"""
        size = max(8, int(size))
        f = self.font_cache.get(size)
        if f is None:
            f = self.font_cache[size] = load_font(size)
        return f

    def text(self, s, font, color, pos, center=False, right=False):
        img = font.render(s, True, color)
        rect = img.get_rect()
        if center:
            rect.center = pos
        elif right:
            rect.topright = pos
        else:
            rect.topleft = pos
        self.screen.blit(img, rect)

    def draw_board(self):
        r = max(2, int(S * 0.1))
        for q, cell_r in BOARD_CELLS:
            cx, cy = cell_center(q, cell_r)
            color = self.filled.get((q, cell_r))
            if color is None:
                draw_hex(self.screen, cx, cy, S, None, EMPTY_LINE, r)
            else:
                draw_cell(self.screen, cx, cy, S, color)

        if self.game_over:
            return

        color = COLORS[self.piece["name"]]
        for c in self.cells_at(self.piece, *self.landing_anchor()):
            if c in BOARD_SET and c not in self.filled:
                draw_hex(self.screen, *cell_center(*c), S - 3, None, lighten(color, 1.05), 2)
        for q, cell_r in self.cur_cells():
            draw_cell(self.screen, *cell_center(q, cell_r), S, color)

    def draw_preview(self, name, box, size):
        pts = [(1.5 * size * q, math.sqrt(3) * size * (r + q / 2.0))
               for q, r in PIECES[name]]
        ox = box.centerx - (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
        oy = box.centery - (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
        for x, y in pts:
            draw_cell(self.screen, ox + x, oy + y, size, COLORS[name])

    def draw_panel(self):
        r = PANEL_RECT
        panel = pygame.Surface(r.size, pygame.SRCALPHA)
        panel.fill((*PANEL_COLOR, 235))
        pygame.draw.rect(panel, (*BORDER_COLOR, 90), panel.get_rect(), 2, border_radius=16)
        self.screen.blit(panel, r.topleft)

        # 面板内容随可用高度整体等比缩放：矮窗口里字号和行距一起变小，不会互相挤压
        k = min(1.0, r.height / PANEL_DESIGN_H)
        f_title = self.font(34 * k)
        f_big = self.font(26 * k)
        f_mid = self.font(20 * k)
        f_small = self.font(16 * k)
        pad = max(8, int(26 * k))
        row = f_small.get_linesize()          # 帮助/排行榜行高，跟字体走

        y = r.top + int(12 * k)
        self.text("HEX TETRIS", f_title, (240, 210, 70),
                  (r.centerx, y + f_title.get_height() // 2), center=True)
        y += f_title.get_height() + int(4 * k)
        self.text(TEXT["subtitle"], f_small, TEXT_DIM,
                  (r.centerx, y + f_small.get_height() // 2), center=True)
        y += f_small.get_height() + int(10 * k)

        self.text("NEXT", f_mid, (80, 220, 230), (r.left + pad, y))
        y += f_mid.get_height() + int(6 * k)
        box = pygame.Rect(r.left + pad, y, r.width - 2 * pad, max(40, int(120 * k)))
        pygame.draw.rect(self.screen, (40, 70, 60), box, 2, border_radius=10)
        self.draw_preview(self.next_name, box,
                          max(5, int(min(S * 0.75, box.height * 0.28))))

        y = box.bottom + int(22 * k)
        step = max(f_big.get_linesize(), int(38 * k))
        for label, value in ((TEXT["score"], self.score), (TEXT["best"], self.best_score()),
                             (TEXT["lines"], self.lines), (TEXT["level"], self.level)):
            self.text(label, f_mid, TEXT_DIM, (r.left + pad, y))
            self.text(str(value), f_big, (235, 240, 238),
                      (r.right - pad, y - int(4 * k)), right=True)
            y += step

        lines = TEXT["help"]
        help_top = r.bottom - int(24 * k) - row * len(lines)

        # Top 5（窗口太矮时自动少显示几行）
        y += int(4 * k)
        top_label_h = f_mid.get_height() + int(8 * k)
        if y + top_label_h + row <= help_top:
            self.text("TOP 5", f_mid, (80, 220, 230), (r.left + pad, y))
            y += top_label_h
            if not self.highscores:
                self.text(TEXT["no_records"], f_small, TEXT_DIM, (r.left + pad, y))
            for i, entry in enumerate(self.highscores, 1):
                if y + row > help_top:
                    break
                top = entry["score"] == self.best_score()
                color = (240, 210, 70) if top else (235, 240, 238)
                self.text(str(i), f_small, TEXT_DIM, (r.left + pad, y))
                name = fit_text(entry["name"], f_small,
                                r.width - 3 * pad - int(80 * k))
                self.text(name, f_small, color, (r.left + 2 * pad, y))
                self.text(str(entry["score"]), f_small, color,
                          (r.right - pad, y), right=True)
                y += row

        y = help_top
        for line in lines:
            self.text(line, f_small, TEXT_DIM, (r.left + pad, y))
            y += row

    def overlay(self, title, subtitle, color):
        shade = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 175))
        self.screen.blit(shade, (0, 0))
        self.text(title, self.f_title, color, (WIN_W // 2, WIN_H // 2 - 18), center=True)
        self.text(subtitle, self.f_mid, (235, 240, 238), (WIN_W // 2, WIN_H // 2 + 30), center=True)

    def draw(self):
        self.screen.fill(BG_COLOR)
        self.draw_board()
        self.draw_panel()
        if self.paused and not self.game_over:
            self.overlay(TEXT["paused"], TEXT["resume"], (240, 210, 70))
        if self.game_over:
            self.overlay(TEXT["game_over"], TEXT["score_line"] % self.score, (240, 210, 70))
            cx, cy = WIN_W // 2, WIN_H // 2
            if self.name_entry is not None:
                self.text(TEXT["new_record"] % HIGHSCORE_NAME_LIMIT,
                          self.f_mid, (80, 220, 230), (cx, cy + 80), center=True)
                box = pygame.Rect(0, 0, 320, 48)
                box.center = (cx, cy + 130)
                pygame.draw.rect(self.screen, (40, 70, 60), box, 2, border_radius=8)
                shown = self.name_entry + "_"
                self.text(shown, self.f_big, (235, 240, 238), box.center, center=True)
                self.text(TEXT["name_keys"], self.f_small, TEXT_DIM,
                          (cx, cy + 180), center=True)
            else:
                if self.last_rank:
                    tip = TEXT["rank"] % (self.last_rank, self.best_score())
                    color = (80, 220, 230)
                else:
                    tip = TEXT["best_only"] % self.best_score()
                    color = (235, 240, 238)
                self.text(tip, self.f_mid, color, (cx, cy + 80), center=True)
                self.text(TEXT["restart"], self.f_mid, (235, 240, 238),
                          (cx, cy + 126), center=True)


def main():
    pygame.init()
    sizes = pygame.display.get_desktop_sizes() or [(1024, 768)]
    max_w = max(w for w, _ in sizes)
    max_h = max(h for _, h in sizes)
    configure(min(920, max_w - 80), min(880, max_h - 120))
    screen = pygame.display.set_mode((WIN_W, WIN_H), pygame.RESIZABLE)
    pygame.display.set_caption(TEXT["caption"])
    clock = pygame.time.Clock()
    game = Game(screen)

    running = True
    fullscreen = False
    windowed_size = (WIN_W, WIN_H)
    while running:
        dt = clock.tick(FPS)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE:
                if fullscreen:
                    configure(event.w, event.h)
                    screen = pygame.display.set_mode((WIN_W, WIN_H), pygame.FULLSCREEN)
                else:
                    windowed_size = (event.w, event.h)
                    configure(event.w, event.h)
                    screen = pygame.display.set_mode((WIN_W, WIN_H), pygame.RESIZABLE)
                game.screen = screen
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and (event.mod & pygame.KMOD_ALT):
                    fullscreen = not fullscreen
                    if fullscreen:
                        windowed_size = (WIN_W, WIN_H)
                        w, h = pygame.display.get_desktop_sizes()[0]
                        configure(w, h)
                        screen = pygame.display.set_mode((WIN_W, WIN_H), pygame.FULLSCREEN)
                    else:
                        configure(*windowed_size)
                        screen = pygame.display.set_mode((WIN_W, WIN_H), pygame.RESIZABLE)
                    game.screen = screen
                elif game.on_key(event.key, event.unicode) is False:
                    running = False
            elif event.type == pygame.KEYUP:
                if event.key in (pygame.K_LEFT, pygame.K_a) and game.das_dir < 0:
                    game.das_dir = 0
                elif event.key in (pygame.K_RIGHT, pygame.K_d) and game.das_dir > 0:
                    game.das_dir = 0
        game.update(dt)
        game.draw()
        pygame.display.flip()
    pygame.quit()


if __name__ == "__main__":
    main()
