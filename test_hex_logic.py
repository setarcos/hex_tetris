#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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


def test_lateral_is_diagonal_down():
    for name in H.PIECES:
        for q, r in H.piece_rel(name, 0):
            x0, y0 = px(q, r)
            for delta, sx in ((H.LEFT, -1), (H.RIGHT, 1)):
                x1, y1 = px(q + delta[0], r + delta[1])
                assert abs((x1 - x0) - sx * 1.5 * H.S) < 1e-9
                assert abs((y1 - y0) - H.HEX_H / 2) < 1e-9


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
    test_lateral_is_diagonal_down()
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
    test_spawn_and_lock()
    make_shot("/tmp/hex_shot.png")
    print("ALL LOGIC TESTS PASSED")
