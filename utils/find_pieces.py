#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2026 Pluto Yang
# SPDX-License-Identifier: GPL-3.0-or-later
"""搜索并图形化显示六边形网格上全部独立的四格方块（tetrahex）。

规则
----
- 棋盘格子是六边形，6 邻域连通（axial 坐标）。
- 只取 4 格、边连通、平移后等价的形状（fixed shapes）。
- 等价判定只考虑 6 个 60° 旋转，**不把镜像当成同一形状**
  （即 one-sided tetrahex）。所以同一块的镜像会各自算一种独立方块，
  例如 S 与它的镜像。

结果
----
固定摆放 44 种 → 旋转去重后 10 种独立方块；若连镜像也去重则 7 种。
脚本会把 10 种方块画成一张拼图，并与 hex_tetris.PIECES 对照，标出重复项与未收录项。

运行
----
    .venv/bin/python utils/find_pieces.py            # 显示窗口并保存 pieces.png
    .venv/bin/python utils/find_pieces.py --no-show  # 只保存图片（无显示环境自动如此）
"""

import argparse
import math
import os
import sys

# 脚本在 utils/ 下，把仓库根目录加进 sys.path 以 import hex_tetris
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 无显示环境自动使用 dummy 驱动，保证仍能生成图片
if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame  # noqa: E402

import hex_tetris as H  # noqa: E402

NEIGHBORS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1))
SIZE = 4

# 版面
MARGIN, GAP, HEADER = 24, 10, 122
TILE_W, TILE_H, COLS = 224, 252, 5
BG = (10, 12, 17)
TILE_BG = (18, 23, 31)
TILE_NEW = (240, 170, 60)       # 未收录：橙色边框
TILE_OLD = (90, 200, 160)       # 已收录：绿色边框
TILE_DUP = (230, 90, 90)        # 重复：红色边框
TEXT = (232, 238, 235)
DIM = (150, 175, 165)

PALETTE = [
    (80, 220, 230), (240, 210, 70), (170, 90, 220), (240, 150, 60),
    (70, 120, 230), (90, 200, 90), (230, 80, 80), (230, 110, 200),
    (120, 220, 140), (200, 160, 90),
]


# ----------------------------------------------------------------- 搜索算法
def normalize(cells):
    """平移规范化：最小 q、最小 r 都移到 0。"""
    mq = min(q for q, _ in cells)
    mr = min(r for _, r in cells)
    return tuple(sorted((q - mq, r - mr) for q, r in cells))


def rot60(cells):
    """绕原点顺时针旋转 60°（axial 坐标）。"""
    return [(-r, q + r) for q, r in cells]


def mirror(cells):
    """镜像（沿 q = r 轴翻折）。"""
    return [(r, q) for q, r in cells]


def canonical(cells, allow_mirror=False):
    """返回该形状在旋转（可选镜像）等价类中的字典序最小代表元。"""
    forms = []
    cur = list(cells)
    for _ in range(6):
        forms.append(normalize(cur))
        cur = rot60(cur)
    if allow_mirror:
        cur = mirror(cells)
        for _ in range(6):
            forms.append(normalize(cur))
            cur = rot60(cur)
    return min(forms)


def all_fixed_shapes(n=SIZE):
    """枚举全部 n 格连通形状（平移去重，保留朝向）。"""
    shapes = {normalize([(0, 0)])}
    for _ in range(n - 1):
        grown = set()
        for shape in shapes:
            for q, r in shape:
                for dq, dr in NEIGHBORS:
                    c = (q + dq, r + dr)
                    if c not in shape:
                        grown.add(normalize(list(shape) + [c]))
        shapes = grown
    return shapes


# ------------------------------------------------------------------- 绘图
def cell_px(q, r, s):
    """局部像素坐标（平顶六边形）。"""
    return 1.5 * s * q, math.sqrt(3) * s * (r + q / 2.0)


def draw_piece(surf, cells, box, color):
    """把方块按比例放进 box 并居中绘制。"""
    pts = [cell_px(q, r, 1.0) for q, r in cells]
    min_x, max_x = min(p[0] for p in pts), max(p[0] for p in pts)
    min_y, max_y = min(p[1] for p in pts), max(p[1] for p in pts)
    span_x = (max_x - min_x) + 2.0                    # 每格半径 1
    span_y = (max_y - min_y) + math.sqrt(3.0)
    s = min(box.width / span_x, box.height / span_y)
    ox = box.centerx - s * (min_x + max_x) / 2.0
    oy = box.centery - s * (min_y + max_y) / 2.0
    for q, r in cells:
        x, y = cell_px(q, r, s)
        H.draw_cell(surf, ox + x, oy + y, s, color)


def blit_text(surf, font, text, color, pos, center=False, right=False):
    img = font.render(text, True, color)
    rect = img.get_rect()
    if center:
        rect.center = pos
    elif right:
        rect.topright = pos
    else:
        rect.topleft = pos
    surf.blit(img, rect)


def build_sheet(keys, existing, fixed_n, free_n):
    rows = math.ceil(len(keys) / COLS)
    width = MARGIN * 2 + COLS * TILE_W + (COLS - 1) * GAP
    height = HEADER + rows * TILE_H + (rows - 1) * GAP + MARGIN
    surf = pygame.Surface((width, height))
    surf.fill(BG)

    f_title = H.load_font(32)
    f_mid = H.load_font(19)
    f_small = H.load_font(15)
    f_tiny = H.load_font(13)

    blit_text(surf, f_title, "六边形四格方块全集（旋转去重，镜像另算）",
              (240, 210, 70), (MARGIN, 20))
    blit_text(surf, f_mid,
              "固定摆放 %d  ·  独立方块 %d  ·  旋转+镜像去重 %d  ·  现有 PIECES 对照"
              % (fixed_n, len(keys), free_n),
              TEXT, (MARGIN, 62))
    blit_text(surf, f_small,
              "边框：绿=已收录   红=与其它方块重复   橙=未收录    "
              "“镜像 ↔ #n”表示镜像在旋转意义下是另一种独立方块",
              DIM, (MARGIN, 90))

    index = {key: i + 1 for i, key in enumerate(keys)}
    for key in keys:
        no = index[key]
        names = existing.get(key, [])
        mirror_key = canonical(mirror(key))
        chiral = mirror_key != key
        partner = index.get(mirror_key)

        col, row = (no - 1) % COLS, (no - 1) // COLS
        x = MARGIN + col * (TILE_W + GAP)
        y = HEADER + row * (TILE_H + GAP)
        rect = pygame.Rect(x, y, TILE_W, TILE_H)
        pygame.draw.rect(surf, TILE_BG, rect, border_radius=14)

        if len(names) > 1:
            border = TILE_DUP
        elif names:
            border = TILE_OLD
        else:
            border = TILE_NEW
        pygame.draw.rect(surf, border, rect, 2, border_radius=14)

        draw_piece(surf, key, pygame.Rect(x + 16, y + 12, TILE_W - 32, TILE_H - 116),
                   PALETTE[(no - 1) % len(PALETTE)])

        blit_text(surf, f_small, "#%d" % no, DIM, (x + 12, y + 8))
        if len(names) > 1:
            tag, tag_color = "重复: " + "/".join(names), TILE_DUP
        elif names:
            tag, tag_color = "已收录: " + "/".join(names), TILE_OLD
        else:
            tag, tag_color = "未收录", TILE_NEW
        blit_text(surf, f_small, tag, tag_color, (x + TILE_W - 12, y + 8), right=True)

        label = "/".join(names) if names else "新方块"
        blit_text(surf, f_mid, label, TEXT, (x + TILE_W // 2, y + TILE_H - 78), center=True)
        blit_text(surf, f_tiny, "镜像 ↔ #%d" % partner if chiral else "镜像 = 自身",
                  DIM, (x + TILE_W // 2, y + TILE_H - 52), center=True)
        coords = " ".join("(%d,%d)" % c for c in key)
        blit_text(surf, f_tiny, coords, DIM, (x + TILE_W // 2, y + TILE_H - 30), center=True)

    return surf


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="搜索六边形网格上的全部独立四格方块")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "pieces.png"),
                    help="输出图片路径 (默认 pieces.png)")
    ap.add_argument("--no-show", action="store_true", help="不弹出窗口，只保存图片")
    args = ap.parse_args()

    fixed = all_fixed_shapes(SIZE)
    classes = {}
    for s in fixed:
        classes.setdefault(canonical(s), s)
    free = {}
    for s in fixed:
        free.setdefault(canonical(s, allow_mirror=True), s)
    keys = sorted(classes)

    existing = {}
    for name, cells in H.PIECES.items():
        existing.setdefault(canonical(cells), []).append(name)

    print("固定摆放 fixed        : %d" % len(fixed))
    print("独立方块 one-sided    : %d" % len(classes))
    print("旋转+镜像去重 free    : %d" % len(free))
    print("\n=== 全部独立四格方块 ===")
    for i, key in enumerate(keys, 1):
        names = existing.get(key, [])
        tag = ("已有 " + "/".join(names)) if names else "未收录"
        print("  #%-2d %-28s %s" % (i, str(key), tag))

    dups = [v for v in existing.values() if len(v) > 1]
    missing = [i for i, k in enumerate(keys, 1) if k not in existing]
    print("\n现有 PIECES: %s" % " ".join(H.PIECES))
    if dups:
        print("旋转后重复: " + "；".join(" = ".join(v) for v in dups))
    else:
        print("旋转后重复: 无")
    print("未收录编号: %s" % (missing if missing else "无"))

    pygame.init()
    sheet = build_sheet(keys, existing, len(fixed), len(free))
    pygame.image.save(sheet, args.out)
    print("\n图片 -> %s" % args.out)

    headless = os.environ.get("SDL_VIDEODRIVER") == "dummy"
    if args.no_show or headless:
        pygame.quit()
        return

    screen = pygame.display.set_mode(sheet.get_size())
    pygame.display.set_caption("Hex Tetris - 全部独立四格方块")
    screen.blit(sheet, (0, 0))
    pygame.display.flip()
    clock = pygame.time.Clock()
    running = True
    while running:
        clock.tick(30)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key in (
                    pygame.K_ESCAPE, pygame.K_q, pygame.K_RETURN):
                running = False
    pygame.quit()


if __name__ == "__main__":
    main()
