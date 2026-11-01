"""ピックルボールのダブルスの対戦表を作る（管理者メニュー「🎾 対戦表」）。

Streamlit には依存しない。参加者は名前のリストで受け取り、
試合ごとに {"courts": [{"team1": [..], "team2": [..]}, ...], "rest": [..]} のリストを返す。

- rotation    : 毎試合ペアが入れ替わる。同じペア・同じ相手・試合数の偏りをなるべく減らす
- fixed_pairs : 最初にペアを決めて、ペア同士で総当たり
"""

from __future__ import annotations

import random
from collections import Counter

# 4人を2チームに分ける3通り（0,1 vs 2,3 / 0,2 vs 1,3 / 0,3 vs 1,2）
_SPLITS = [((0, 1), (2, 3)), ((0, 2), (1, 3)), ((0, 3), (1, 2))]


def _key(a: str, b: str) -> frozenset:
    return frozenset((a, b))


def rotation(players: list[str], rounds: int, courts: int = 2, seed: int = 0) -> list[dict]:
    """毎試合ペアを入れ替える対戦表。"""
    rng = random.Random(seed)
    players = list(dict.fromkeys(players))  # 同じ名前は1人として扱う
    games = Counter({p: 0 for p in players})
    rested = Counter({p: 0 for p in players})      # 休んだ回数
    rest_streak = Counter({p: 0 for p in players})  # 続けて休んだ回数
    partner: Counter = Counter()
    opponent: Counter = Counter()
    plan = []
    for _ in range(rounds):
        k = min(courts, len(players) // 4)
        if k == 0:
            break
        # 試合数が少ない人 → 続けて休んでいる人 を優先して出場させる
        order = sorted(players, key=lambda p: (games[p], -rest_streak[p], -rested[p], rng.random()))
        playing, resting = order[:4 * k], order[4 * k:]

        best, best_score = None, None
        for _ in range(300):
            pool = playing[:]
            rng.shuffle(pool)
            courts_plan, score = [], 0
            for c in range(k):
                g = pool[c * 4:(c + 1) * 4]
                options = []
                for t1, t2 in _SPLITS:
                    a, b = g[t1[0]], g[t1[1]]
                    c_, d = g[t2[0]], g[t2[1]]
                    s = (partner[_key(a, b)] + partner[_key(c_, d)]) * 10
                    s += sum(opponent[_key(x, y)] for x in (a, b) for y in (c_, d)) * 3
                    options.append((s, [a, b], [c_, d]))
                s, t1, t2 = min(options, key=lambda o: o[0])
                score += s
                courts_plan.append({"team1": t1, "team2": t2})
            if best_score is None or score < best_score:
                best, best_score = courts_plan, score
                if score == 0:
                    break

        for m in best:
            a, b = m["team1"]
            c_, d = m["team2"]
            partner[_key(a, b)] += 1
            partner[_key(c_, d)] += 1
            for x in (a, b):
                for y in (c_, d):
                    opponent[_key(x, y)] += 1
            for p in (a, b, c_, d):
                games[p] += 1
                rest_streak[p] = 0
        for p in resting:
            rested[p] += 1
            rest_streak[p] += 1
        plan.append({"courts": best, "rest": sorted(resting, key=players.index)})
    return plan


def make_pairs(players: list[str], seed: int = 0) -> list[list[str]]:
    """ペアを決める。人数が奇数なら最後のペアを3人（交代で出る）にする。"""
    rng = random.Random(seed)
    pool = list(dict.fromkeys(players))
    rng.shuffle(pool)
    pairs = [pool[i:i + 2] for i in range(0, len(pool) - len(pool) % 2, 2)]
    if len(pool) % 2:
        if pairs:
            pairs[-1].append(pool[-1])
        else:
            pairs = [[pool[-1]]]
    return pairs


def fixed_pairs(players: list[str], rounds: int, courts: int = 2, seed: int = 0) -> tuple[list[list[str]], list[dict]]:
    """ペア同士の総当たり。(ペアの一覧, 対戦表) を返す。"""
    pairs = make_pairs(players, seed)
    n = len(pairs)
    if n < 2:
        return pairs, []
    # 総当たりの組み合わせを「回」ごとに作る（サークル方式）
    ids = list(range(n)) + ([None] if n % 2 else [])
    m = len(ids)
    match_rounds = []
    for r in range(m - 1):
        rnd = []
        for i in range(m // 2):
            a, b = ids[i], ids[m - 1 - i]
            if a is not None and b is not None:
                rnd.append((a, b))
        match_rounds.append(rnd)
        ids = [ids[0]] + [ids[-1]] + ids[1:-1]
    matches = [mt for rnd in match_rounds for mt in rnd]

    # コート数ずつ、同じペアが同時に入らないように試合を詰める
    plan, played = [], Counter()
    remaining = matches[:]
    while remaining and len(plan) < rounds:
        slot, busy = [], set()
        for mt in sorted(remaining, key=lambda x: (played[x[0]] + played[x[1]])):
            if len(slot) == courts:
                break
            if mt[0] in busy or mt[1] in busy:
                continue
            slot.append(mt)
            busy |= set(mt)
        for mt in slot:
            remaining.remove(mt)
            played[mt[0]] += 1
            played[mt[1]] += 1
        resting = [p for i, pr in enumerate(pairs) if i not in busy for p in pr]
        plan.append({"courts": [{"team1": pairs[a], "team2": pairs[b], "pairs": [a, b]} for a, b in slot],
                     "rest": resting})
        if not remaining and len(plan) < rounds:  # 一巡したら、もう一巡
            remaining = matches[:]
    return pairs, plan


def summary(players: list[str], plan: list[dict]) -> dict[str, dict]:
    """一人ずつの試合数・休み数。"""
    out = {p: {"games": 0, "rest": 0} for p in players}
    for rnd in plan:
        for m in rnd["courts"]:
            for p in m["team1"] + m["team2"]:
                if p in out:
                    out[p]["games"] += 1
        for p in rnd["rest"]:
            if p in out:
                out[p]["rest"] += 1
    return out


def plan_text(title: str, plan: list[dict], pairs: list[list[str]] | None = None) -> str:
    """LINE などに貼る文章。"""
    lines = [f"【{title} 対戦表】"]
    if pairs:
        lines.append("")
        lines.append("■ ペア")
        for i, pr in enumerate(pairs):
            lines.append(f"{chr(65 + i)}：{'・'.join(pr)}" + ("（3人で交代）" if len(pr) == 3 else ""))
    for i, rnd in enumerate(plan, 1):
        lines.append("")
        lines.append(f"■ 第{i}試合")
        for c, m in enumerate(rnd["courts"], 1):
            lines.append(f"コート{c}：{'・'.join(m['team1'])} vs {'・'.join(m['team2'])}")
        if rnd["rest"]:
            lines.append(f"休み：{'、'.join(rnd['rest'])}")
    return "\n".join(lines)


def default_rounds(n_players: int, courts: int = 2) -> int:
    """全員がだいたい6試合できる回数（6〜12回の間）。"""
    on_court = min(courts, max(1, n_players // 4)) * 4
    if n_players < 4:
        return 0
    return max(6, min(12, round(6 * n_players / on_court)))

