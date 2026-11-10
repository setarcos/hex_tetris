#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hex Tetris 自动玩家。

直接复用 hex_tetris 的棋盘 / 方块 / 消行逻辑，不模拟键盘：
每个方块用 BFS 枚举所有可达姿态（旋转 + 左斜下 / 右斜下 / 下落），
逐个试落并评估棋盘，选最好的一处硬降。

用法:
    .venv/bin/python auto_play.py                  # 开窗口看 AI 玩
    .venv/bin/python auto_play.py --fast           # 窗口内不等待，尽快玩
    .venv/bin/python auto_play.py --headless 5000  # 无窗口跑 5000 个方块看统计
"""

import argparse
import random
import sys
from collections import deque

import pygame

import hex_tetris as ht

# ------------------------------------------------------------------ 评估权重
W_LINES = 1000.0    # 每消一行
W_HOLES = 24.0      # 每个"三面被围"的空格
W_AGG = 1.0         # 各列高度之和
W_MAX = 6.0         # 最高的一列
W_BUMP = 1.5        # 相邻列高度差之和
W_POT = 10.0        # 接近填满的斜行（(n/8)^3）

MAX_STATES = 1500   # 单个方块 BFS 状态上限

# 每一竖列的格子（r 从小到大 = 从上到下）
COLS = []
for _q in range(-ht.Q_MAX, ht.Q_MAX + 1):
    _rs = [r for r in range(-ht.R_MAX, ht.R_MAX + 1)
           if (r >= -ht.S_MAX - _q and r <= ht.S_MAX - _q)]
    COLS.append((_q, _rs))

# 一个空格若三个"上方"邻居都被填住，就基本再也填不进去了
UPPER = ((0, -1), (-1, 0), (1, -1))


# ------------------------------------------------------------------ 可达性
def rel_cells(name, rot):
    return ht.piece_rel(name, rot)


def fits_state(game, name, q, r, rot):
    return game.fits([(cq + q, cr + r) for cq, cr in rel_cells(name, rot)])


def transitions(game, name, q, r, rot):
    """与 Game.try_move / Game.try_rotate 完全一致的合法走法。"""
    out = []
    if fits_state(game, name, q - 1, r + 1, rot):      # LEFT  = 左下
        out.append(((q - 1, r + 1, rot), "L"))
    if fits_state(game, name, q + 1, r, rot):          # RIGHT = 右下
        out.append(((q + 1, r, rot), "R"))
    if fits_state(game, name, q, r + 1, rot):          # 下落
        out.append(((q, r + 1, rot), "D"))
    for step, move in ((1, "CW"), (-1, "CCW")):
        nrot = (rot + step) % 6
        for dq, dr in ht.KICKS:
            if fits_state(game, name, q + dq, r + dr, nrot):
                out.append(((q + dq, r + dr, nrot), move))
                break
    return out


def reachable(game, name, q0, r0, rot0):
    """BFS 返回 {状态: 从起点到该状态的动作序列}。"""
    start = (q0, r0, rot0)
    paths = {start: ()}
    todo = deque([start])
    while todo and len(paths) < MAX_STATES:
        q, r, rot = todo.popleft()
        path = paths[(q, r, rot)]
        for state, move in transitions(game, name, q, r, rot):
            if state not in paths:
                paths[state] = path + (move,)
                todo.append(state)
                if len(paths) >= MAX_STATES:
                    break
    return paths


def drop_to(game, name, q, r, rot):
    """在 (q, r, rot) 处一直垂直下落到落点，返回落点 r。"""
    while fits_state(game, name, q, r + 1, rot):
        r += 1
    return r


# ------------------------------------------------------------------ 评估
def board_metrics(filled):
    heights = []
    holes = 0
    for q, rs in COLS:
        top = None
        for i, r in enumerate(rs):
            if (q, r) in filled:
                if top is None:
                    top = i
            elif top is not None:
                holes += 1
        heights.append(0 if top is None else len(rs) - top)

    agg = sum(heights)
    tallest = max(heights) if heights else 0
    bump = sum(abs(heights[i] - heights[i + 1]) for i in range(len(heights) - 1))

    potential = 0.0
    for row in ht.ROWS:
        if len(row) == 8:
            n = sum(1 for c in row if c in filled)
            potential += (n / 8.0) ** 3
    return heights, holes, agg, tallest, bump, potential


def evaluate(game, name, q, r, rot):
    """把方块放在 (q, r) 后（含消行）给棋盘打分。"""
    filled = dict(game.filled)
    for c in rel_cells(name, rot):
        filled[(c[0] + q, c[1] + r)] = (0, 0, 0)
    cleared = ht.clear_full_lines(filled)
    _, holes, agg, tallest, bump, potential = board_metrics(filled)
    score = (W_LINES * cleared
             - W_HOLES * holes
             - W_AGG * agg
             - W_MAX * tallest
             - W_BUMP * bump
             + W_POT * potential)
    return score


def best_move(game):
    """返回 (动作序列, 评估分)；动作序列执行完后硬降即可。"""
    if game.piece is None:
        return (), 0.0
    name = game.piece["name"]
    q0, r0, rot0 = game.piece["q"], game.piece["r"], game.piece["rot"]
    paths = reachable(game, name, q0, r0, rot0)

    best_score, best_path = None, ()
    seen = set()
    for (q, r, rot), path in paths.items():
        land_r = drop_to(game, name, q, r, rot)
        key = (q, land_r, rot)
        if key in seen:
            continue
        seen.add(key)
        score = evaluate(game, name, q, land_r, rot)
        if best_score is None or score > best_score:
            best_score, best_path = score, path
    return best_path, (best_score if best_score is not None else 0.0)


def apply_action(game, action):
    if action == "L":
        return game.try_move(ht.LEFT)
    if action == "R":
        return game.try_move(ht.RIGHT)
    if action == "D":
        return game.try_move(ht.DOWN)
    if action == "CW":
        return game.try_rotate(1)
    if action == "CCW":
        return game.try_rotate(-1)
    raise ValueError(action)


# ------------------------------------------------------------------ 运行模式
def play_headless(pieces, seed=None):
    if seed is not None:
        random.seed(seed)
    pygame.init()
    game = ht.Game(pygame.Surface((8, 8)))
    played = 0
    while played < pieces and not game.game_over:
        if game.piece is None:
            break
        path, _ = best_move(game)
        for action in path:
            apply_action(game, action)
        game.hard_drop()
        played += 1
        if played % 100 == 0:
            print(f"  {played:5d} 块  消行 {game.lines:5d}  得分 {game.score:8d}",
                  flush=True)
    print(f"结束：{played} 块，消行 {game.lines}，得分 {game.score}，"
          f"等级 {game.level}，游戏结束={game.game_over}")
    return played, game.lines, game.score


def play_window(fast=False, seed=None):
    if seed is not None:
        random.seed(seed)
    pygame.init()
    sizes = pygame.display.get_desktop_sizes() or [(1024, 768)]
    max_w = max(w for w, _ in sizes)
    max_h = max(h for _, h in sizes)
    ht.configure(min(920, max_w - 80), min(880, max_h - 120))
    screen = pygame.display.set_mode((ht.WIN_W, ht.WIN_H), pygame.RESIZABLE)
    pygame.display.set_caption("Hex Tetris - AI 自动玩家")
    clock = pygame.time.Clock()
    game = ht.Game(screen)

    action_delay = 16 if fast else 45
    piece_delay = 20 if fast else 220
    wait = 0
    plan = []
    running = True

    while running:
        dt = clock.tick(ht.FPS)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE:
                ht.configure(event.w, event.h)
                screen = pygame.display.set_mode((ht.WIN_W, ht.WIN_H), pygame.RESIZABLE)
                game.screen = screen
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_r:
                    game.reset()
                    plan = []
                elif game.name_entry is not None:
                    game.on_key(event.key, event.unicode)
                elif event.key == pygame.K_m:
                    game.sounds.toggle()
                elif event.key == pygame.K_p and not game.game_over:
                    game.paused = not game.paused

        if not game.game_over and not game.paused:
            wait -= dt
            if wait <= 0:
                if not plan:
                    plan = list(best_move(game)[0])
                if plan:
                    if apply_action(game, plan.pop(0)):
                        wait = action_delay
                    else:              # 计划失效（理论上不会），重新规划
                        plan = []
                else:
                    game.hard_drop()
                    plan = []
                    wait = piece_delay

        game.draw()
        pygame.display.flip()

    pygame.quit()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Hex Tetris 自动玩家")
    ap.add_argument("--headless", type=int, metavar="N",
                    help="不开窗口，自动玩 N 个方块后输出统计")
    ap.add_argument("--fast", action="store_true", help="窗口内加速")
    ap.add_argument("--seed", type=int, help="随机种子")
    args = ap.parse_args(argv)

    if args.headless:
        play_headless(args.headless, args.seed)
    else:
        play_window(args.fast, args.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
