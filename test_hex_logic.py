#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2026 Pluto Yang
# SPDX-License-Identifier: GPL-3.0-or-later
"""hex_tetris 的逻辑自检 + 无头渲染快照。"""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

import hex_tetris as H  # noqa: E402

NEIGHBORS = {(1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)}


def px(q, r):
    return H.HEX_W * q, H.HEX_H * (r + q / 2.0)


def test_board_shape():
    """六条边依次为 16,8,8,16,8,8（循环即 8x8x16x8x8x16），左右两边 16 格。"""
    def n(pred):
        return sum(1 for c in H.BOARD_CELLS if pred(*c))

    left = n(lambda q, r: q == -H.Q_MAX)
    upper_left = n(lambda q, r: -(q + r) == H.S_MAX)
    upper_right = n(lambda q, r: r == -H.R_MAX)
    right = n(lambda q, r: q == H.Q_MAX)
    lower_right = n(lambda q, r: -(q + r) == -H.S_MAX)
    lower_left = n(lambda q, r: r == H.R_MAX)
    assert (left, upper_left, upper_right, right, lower_right, lower_left) == \
        (16, 8, 8, 16, 8, 8), (left, upper_left, upper_right, right, lower_right, lower_left)
    assert len(H.BOARD_CELLS) == 289


def test_pieces_connected():
    for name, cells in H.PIECES.items():
        assert len(cells) == 4, name
        cells = set(cells)
        start = next(iter(cells))
        seen, stack = {start}, [start]
        while stack:
            q, r = stack.pop()
            for dq, dr in NEIGHBORS:
                nb = (q + dq, r + dr)
                if nb in cells and nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        assert seen == cells, f"{name} 不是连通块"


def test_fall_is_vertical_one_cell():
    for name in H.PIECES:
        for rot in range(6):
            for q, r in H.piece_rel(name, rot):
                a = px(q, r)
                b = px(q + H.DOWN[0], r + H.DOWN[1])
                assert abs(a[0] - b[0]) < 1e-9                     # 同一列, x 不变
                assert abs((b[1] - a[1]) - H.HEX_H) < 1e-9         # 垂直下落 1 格


def test_lateral_steps_are_diagonal():
    """左右跨一列: 横向 1.5S; 两种竖向分量各 ±半个六边形高。"""
    for direction, (down, up) in H.LATERAL_STEPS.items():
        assert down[0] == up[0] == direction
        for q, r in H.piece_rel("O", 0):
            x0, y0 = px(q, r)
            xd, yd = px(q + down[0], r + down[1])
            xu, yu = px(q + up[0], r + up[1])
            assert abs(xd - x0 - direction * 1.5 * H.S) < 1e-9
            assert abs(xu - x0 - direction * 1.5 * H.S) < 1e-9
            assert abs((yd - y0) - H.HEX_H / 2) < 1e-9
            assert abs((yu - y0) + H.HEX_H / 2) < 1e-9


def test_lateral_alternates_vertical():
    """同方向连按: 斜下 → 斜上 → 斜下 …（两次净高度不变）；换向重新从斜下开始。"""
    pygame.init()
    screen = pygame.display.set_mode((H.WIN_W, H.WIN_H))
    g = H.Game(screen)
    g.filled.clear()
    g.piece["q"], g.piece["r"] = -2, 0          # 棋盘中间, 四周都通
    g.reset_fall_level()
    p = g.piece
    assert g.fits(g.cur_cells())
    q0, r0 = p["q"], p["r"]

    assert g.try_lateral(-1) and (p["q"], p["r"]) == (q0 - 1, r0 + 1)   # 左下
    assert g.try_lateral(-1) and (p["q"], p["r"]) == (q0 - 2, r0 + 1)   # 左上
    assert g.try_lateral(-1) and (p["q"], p["r"]) == (q0 - 3, r0 + 2)   # 左下
    assert g.try_lateral(1) and (p["q"], p["r"]) == (q0 - 2, r0 + 2)    # 换向: 右下
    assert g.try_lateral(1) and (p["q"], p["r"]) == (q0 - 1, r0 + 1)    # 右上

    g.hard_drop()
    assert g.lateral_dir == 0 and g.lateral_next_up is False             # 新方块重新算
    pygame.quit()


def test_lateral_falls_back_to_other_diagonal():
    """轮到的那一步被挡时, 同方向的另一斜向仍能走。"""
    pygame.init()
    screen = pygame.display.set_mode((H.WIN_W, H.WIN_H))
    g = H.Game(screen)
    g.filled.clear()
    g.piece = {"name": "I", "rot": 0, "q": -2, "r": 0}
    g.reset_fall_level()
    p = g.piece
    assert g.fits(g.cur_cells())
    for c in g.cells_at(p, p["q"] - 1, p["r"] + 1):      # 占住左下目标
        g.filled[c] = (1, 2, 3)
    assert not g.fits(g.cells_at(p, p["q"] - 1, p["r"] + 1))
    assert g.fits(g.cells_at(p, p["q"] - 1, p["r"]))
    assert g.try_lateral(-1)
    assert (p["q"], p["r"]) == (-3, 0)                  # 改走了左上
    assert g.lateral_next_up is False                    # 下一次回到左下
    pygame.quit()


def test_lateral_cannot_climb():
    """贴地时连续按同一方向不能顺着斜上一路爬高: 相对下落基准最多偏半格。"""
    pygame.init()
    screen = pygame.display.set_mode((H.WIN_W, H.WIN_H))
    g = H.Game(screen)
    g.filled.clear()
    for c in H.BOARD_CELLS:                     # 造一层平地板（q <= 1 才有 r >= 6）
        if c[1] >= 6:
            g.filled[c] = (1, 2, 3)
    g.piece = {"name": "O", "rot": 0, "q": 0, "r": 0}
    while g.try_move(H.DOWN):
        pass
    g.reset_fall_level()
    key0 = g.half_level(g.piece["q"], g.piece["r"])
    assert not g.can_fall()                     # 已经贴地

    moved = 0
    for _ in range(8):
        if g.try_lateral(-1):
            moved += 1
        assert g.half_level(g.piece["q"], g.piece["r"]) >= key0 - 1
    assert moved == 1, moved                    # 只能横移一列，不能接着往上爬


def test_rotation_is_rigid():
    def dist2(a, b):
        return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2

    for name, cells in H.PIECES.items():
        for i in range(len(cells)):
            for j in range(i + 1, len(cells)):
                before = dist2(px(*cells[i]), px(*cells[j]))
                rot = H.rot_cw(cells)
                after = dist2(px(*rot[i]), px(*rot[j]))
                assert abs(before - after) < 1e-6, (name, i, j)


def test_rows_are_half_diagonals():
    """每行 = 与左下/右下斜边平行、只取左 8 列或右 8 列的一段, 每行最多 8 格。"""
    assert H.ROWS
    for row in H.ROWS:
        assert 1 <= len(row) <= 8, row
        qs = [q for q, _ in row]
        if all(q <= 0 for q in qs):
            assert len({r for _, r in row}) == 1          # 左半: r 相同
        else:
            assert all(q >= 0 for q in qs)
            assert len({-(q + r) for q, r in row}) == 1   # 右半: s 相同


def test_left_row_clear_and_fall():
    # 左下底边 r=11, 左半 8 格
    row = [(q, 11) for q in range(-H.Q_MAX, 1)]
    assert row == [c for c in H.BOARD_CELLS if c[1] == 11 and c[0] <= 0]
    assert len(row) == 8
    filled = {c: (1, 2, 3) for c in row}
    filled[(0, 10)] = (4, 5, 6)             # 上方一格
    assert H.clear_full_lines(filled) == 1
    assert filled == {(0, 11): (4, 5, 6)}   # 消行后整体下落 1 格


def test_right_row_clear_and_fall():
    # 右下底边 s=-11, 右半 8 格
    row = [(q, 11 - q) for q in range(0, H.Q_MAX + 1)]
    assert row == [c for c in H.BOARD_CELLS if -(c[0] + c[1]) == -H.S_MAX and c[0] >= 0]
    assert len(row) == 8
    filled = {c: (1, 2, 3) for c in row}
    filled[(0, 10)] = (4, 5, 6)
    assert H.clear_full_lines(filled) == 1
    assert filled == {(0, 11): (4, 5, 6)}


def test_fall_count_per_column():
    # 同时消掉左半 r=10 与 r=11 两行 -> 该列上方方块下落 2 格
    filled = {}
    for r in (10, 11):
        for q in range(-H.Q_MAX, 1):
            filled[(q, r)] = (1, 2, 3)
    filled[(0, 9)] = (4, 5, 6)
    assert H.clear_full_lines(filled) == 2
    assert filled == {(0, 11): (4, 5, 6)}


def test_vertical_column_does_not_clear():
    """竖列本身不是消行对象: 填满中间一段竖列不会消行。"""
    column = [c for c in H.BOARD_CELLS if c[0] == 0 and (0, -H.R_MAX) < c < (0, H.R_MAX)]
    filled = {c: (1, 2, 3) for c in column}
    assert H.clear_full_lines(filled) == 0
    assert len(filled) == len(column)


def test_short_rows_do_not_clear():
    """不足 8 格的上层斜线即使填满也不消除。"""
    short = [row for row in H.ROWS if len(row) < 8]
    assert short
    for row in short:
        filled = {c: (1, 2, 3) for c in row}
        assert H.clear_full_lines(filled) == 0, row
        assert set(filled) == set(row), row


def test_spawn_fixed_and_death():
    """出生点固定在顶部居中 q=0；该处被占即判定死亡。"""
    pygame.init()
    screen = pygame.display.set_mode((H.WIN_W, H.WIN_H))
    g = H.Game(screen)
    for name in H.PIECES:
        g.filled.clear()
        p = g.spawn(name)
        assert p is not None and p["q"] == 0, name
        cells = g.cells_at(p, p["q"], p["r"])
        assert all(c in H.BOARD_SET for c in cells), name

    # 占满 q = 0 整列 -> 任何方块都无法在出生点放下
    g.filled.clear()
    for r in range(-H.R_MAX, H.R_MAX + 1):
        g.filled[(0, r)] = (1, 2, 3)
    assert all(g.spawn(name) is None for name in H.PIECES)
    pygame.quit()


def test_rotation_pivots_near_centroid():
    """旋转枢轴必须是离重心最近的自身格子, 且旋转时重心漂移不超过 1.5 个格距。"""
    def centroid(cells):
        xs = [px(*c)[0] for c in cells]
        ys = [px(*c)[1] for c in cells]
        return sum(xs) / len(xs), sum(ys) / len(ys)

    for name, cells in H.PIECES.items():
        pivot = H.PIVOTS[name]
        assert pivot in cells, name                       # 枢轴必须是自身格子
        # 只允许格子中心做枢轴: 枢轴格在 6 个姿态里都停在相对原点
        for rot in range(6):
            assert (0, 0) in H.piece_rel(name, rot), (name, rot)
        # 重心漂移: 不超过 1.5 个格距 (六边形网格格距 = √3 · S)
        cell_dist = H.HEX_H
        c0 = centroid(H.piece_rel(name, 0))
        for rot in range(6):
            cx, cy = centroid(H.piece_rel(name, rot))
            drift = ((cx - c0[0]) ** 2 + (cy - c0[1]) ** 2) ** 0.5
            assert drift <= 1.5 * cell_dist, (name, rot, drift / cell_dist)


def test_pause_after_lock():
    """落定后短暂停顿: 新方块在 SPAWN_PAUSE 内不响应按键、不下落。"""
    pygame.init()
    screen = pygame.display.set_mode((H.WIN_W, H.WIN_H))
    g = H.Game(screen)
    g.hard_drop()
    assert g.piece is not None
    assert g.spawn_timer == H.SPAWN_PAUSE

    anchor = (g.piece["q"], g.piece["r"], g.piece["rot"])
    g.update(H.SPAWN_PAUSE - 1)
    assert (g.piece["q"], g.piece["r"], g.piece["rot"]) == anchor
    for key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_SPACE):
        g.on_key(key)
    assert (g.piece["q"], g.piece["r"], g.piece["rot"]) == anchor

    # 停顿结束: 恢复下落
    g.update(1)
    assert g.spawn_timer == 0
    g.update(g.gravity_ms())
    assert (g.piece["q"], g.piece["r"]) != anchor[:2]
    pygame.quit()


def test_lock_delay_cannot_be_stalled_by_keys():
    """落底后连按移动/旋转不能拖延落定（以前可以永远不落）。"""
    pygame.init()
    screen = pygame.display.set_mode((H.WIN_W, H.WIN_H))
    keysets = ((pygame.K_UP,), (pygame.K_LEFT,),
               (pygame.K_LEFT, pygame.K_UP), (pygame.K_RIGHT, pygame.K_UP))
    for name in H.PIECES:
        for keys in keysets:
            g = H.Game(screen)
            g.spawn_timer = 0
            g.filled.clear()
            g.piece = g.spawn(name)
            assert g.piece is not None
            g.piece["q"], g.piece["r"] = g.landing_anchor()
            g.reset_fall_level()
            piece = g.piece
            elapsed = 0
            while g.piece is piece and elapsed < 5000:
                for key in keys:
                    g.on_key(key)
                g.update(16)
                elapsed += 16
            assert g.piece is not piece, f"{name} 连按 {keys} 仍在无限拖延落定"
            assert elapsed <= 3 * H.LOCK_DELAY, (name, keys, elapsed)
    pygame.quit()


def test_rotation_cannot_climb():
    """旋转踢墙也不能把方块抬到下落到达的位置之上（否则连按旋转能一级级往上爬）。"""
    pygame.init()
    screen = pygame.display.set_mode((H.WIN_W, H.WIN_H))
    rejected = 0
    for name in H.PIECES:
        for rot in range(6):
            g = H.Game(screen)
            g.spawn_timer = 0
            g.filled.clear()
            p = g.spawn(name)
            p["rot"] = rot
            p["q"], p["r"] = g.landing_anchor()
            if not g.fits(g.cur_cells()):
                continue
            g.piece = p
            g.reset_fall_level()
            fall = g.fall_level
            for direction in (1, -1):
                before = (p["q"], p["r"], p["rot"])
                if g.try_rotate(direction):
                    assert g.half_level(p["q"], p["r"]) >= fall - 1, (name, rot, direction)
                else:
                    assert (p["q"], p["r"], p["rot"]) == before, (name, rot, direction)
                    nrot = (rot + direction) % 6
                    rel = H.piece_rel(name, nrot)
                    if any(g.fits([(cq + p["q"] + dq, cr + p["r"] + dr) for cq, cr in rel])
                           for dq, dr in H.KICKS):
                        rejected += 1          # 本来能靠抬一整行转过去, 被限制挡下
    assert rejected, "棋盘底边应有只能靠整行上抬才转得动的姿态（现在被拒绝）"
    pygame.quit()


def test_spawn_and_lock():
    pygame.init()
    screen = pygame.display.set_mode((H.WIN_W, H.WIN_H))
    g = H.Game(screen)
    assert g.piece is not None
    for _ in range(40):
        if g.game_over:
            break
        g.hard_drop()
    assert any(g.filled.values())
    pygame.quit()


def make_shot(path):
    pygame.init()
    screen = pygame.display.set_mode((H.WIN_W, H.WIN_H))
    g = H.Game(screen)
    # 摆一些方块，让画面有内容
    for i, c in enumerate(sorted(H.BOARD_CELLS)):
        if c[1] >= 6 or (c[0] >= 3 and c[1] >= 2):
            g.filled[c] = list(H.COLORS.values())[i % len(H.COLORS)]
    g.on_key(pygame.K_LEFT)
    for _ in range(8):
        g.update(100)
    g.draw()
    pygame.image.save(screen, path)
    pygame.quit()
    print("screenshot ->", path)


if __name__ == "__main__":
    test_board_shape()
    test_pieces_connected()
    test_fall_is_vertical_one_cell()
    test_lateral_steps_are_diagonal()
    test_lateral_alternates_vertical()
    test_lateral_falls_back_to_other_diagonal()
    test_lateral_cannot_climb()
    test_rotation_cannot_climb()
    test_rotation_is_rigid()
    test_rotation_pivots_near_centroid()
    test_rows_are_half_diagonals()
    test_left_row_clear_and_fall()
    test_right_row_clear_and_fall()
    test_fall_count_per_column()
    test_vertical_column_does_not_clear()
    test_short_rows_do_not_clear()
    test_spawn_fixed_and_death()
    test_pause_after_lock()
    test_lock_delay_cannot_be_stalled_by_keys()
    test_spawn_and_lock()
    make_shot("/tmp/hex_shot.png")
    print("ALL LOGIC TESTS PASSED")
