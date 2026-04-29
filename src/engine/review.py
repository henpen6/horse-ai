from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

_PAYOUT_KEY_BY_BET_TYPE = {
    "WIN": "win",
    "QUINELLA": "quinella",
    "EXACTA": "exacta",
    "WIDE": "wide",
    "TRIO": "trio",
    "TRIFECTA": "trifecta",
}

_UNORDERED_BET_TYPES = set(["QUINELLA", "WIDE", "TRIO"])


def review_bets(portfolio_bets: List[Dict[str, Any]], result: Dict[str, Any]) -> Dict[str, Any]:
    finish_order = result.get("finish_order") or []
    podium_numbers = _extract_finish_numbers(finish_order)
    first = podium_numbers[0] if len(podium_numbers) >= 1 else None
    second = podium_numbers[1] if len(podium_numbers) >= 2 else None
    third = podium_numbers[2] if len(podium_numbers) >= 3 else None
    top2 = set(podium_numbers[:2])
    top3 = set(podium_numbers[:3])
    payouts = result.get("payouts") or {}

    reviewed_bets = []
    total_stake = 0
    total_payout = 0
    hit_count = 0
    hit_types = []

    for original_bet in portfolio_bets:
        reviewed_bet = dict(original_bet)
        bet_type = str(reviewed_bet.get("bet_type") or "")
        numbers = _extract_bet_numbers(reviewed_bet)
        stake_yen = _coerce_int(reviewed_bet.get("stake_yen"))
        hit = _is_hit(
            bet_type=bet_type,
            numbers=numbers,
            first=first,
            second=second,
            third=third,
            top2=top2,
            top3=top3,
        )
        payout_per_100 = _lookup_payout_per_100(
            bet_type=bet_type,
            numbers=numbers,
            payouts=payouts,
        )
        actual_payout = _calculate_actual_payout(stake_yen, payout_per_100) if hit else 0

        reviewed_bet["numbers"] = numbers
        reviewed_bet["stake_yen"] = stake_yen
        reviewed_bet["hit"] = hit
        reviewed_bet["payout_per_100"] = payout_per_100
        reviewed_bet["payout"] = actual_payout
        reviewed_bets.append(reviewed_bet)

        total_stake += stake_yen
        total_payout += actual_payout
        if hit:
            hit_count += 1
            if bet_type and bet_type not in hit_types:
                hit_types.append(bet_type)

    profit = total_payout - total_stake
    return_rate = round(float(total_payout) / float(total_stake), 3) if total_stake else 0.0

    return {
        "bets": reviewed_bets,
        "total_stake": total_stake,
        "total_payout": total_payout,
        "profit": profit,
        "return_rate": return_rate,
        "hit_count": hit_count,
        "hit_types": hit_types,
    }


def _extract_finish_numbers(finish_order: List[Dict[str, Any]]) -> List[int]:
    numbers = []
    for item in finish_order[:3]:
        number = item.get("number")
        if number is None:
            number = item.get("horse_number")
        if number is None:
            continue
        numbers.append(_coerce_int(number))
    return numbers


def _extract_bet_numbers(bet: Dict[str, Any]) -> List[int]:
    if isinstance(bet.get("numbers"), list):
        return [_coerce_int(value) for value in bet.get("numbers") or []]
    if bet.get("number") is not None:
        return [_coerce_int(bet.get("number"))]
    return []


def _extract_payout_numbers(item: Dict[str, Any]) -> List[int]:
    if isinstance(item.get("numbers"), list):
        return [_coerce_int(value) for value in item.get("numbers") or []]
    if item.get("number") is not None:
        return [_coerce_int(item.get("number"))]
    return []


def _is_hit(
    *,
    bet_type: str,
    numbers: List[int],
    first: Optional[int],
    second: Optional[int],
    third: Optional[int],
    top2: Set[int],
    top3: Set[int],
) -> bool:
    if bet_type == "WIN":
        return len(numbers) == 1 and first == numbers[0]
    if bet_type == "QUINELLA":
        return len(numbers) == 2 and len(top2) == 2 and set(numbers) == top2
    if bet_type == "EXACTA":
        return len(numbers) == 2 and first is not None and second is not None and numbers == [first, second]
    if bet_type == "WIDE":
        return len(numbers) == 2 and set(numbers).issubset(top3)
    if bet_type == "TRIO":
        return len(numbers) == 3 and len(top3) == 3 and set(numbers) == top3
    if bet_type == "TRIFECTA":
        return (
            len(numbers) == 3
            and first is not None
            and second is not None
            and third is not None
            and numbers == [first, second, third]
        )
    return False


def _lookup_payout_per_100(
    *,
    bet_type: str,
    numbers: List[int],
    payouts: Dict[str, List[Dict[str, Any]]],
) -> int:
    payout_key = _PAYOUT_KEY_BY_BET_TYPE.get(bet_type)
    if payout_key is None:
        return 0

    target_numbers = _normalize_numbers(bet_type, numbers)
    for payout_item in payouts.get(payout_key) or []:
        payout_numbers = _extract_payout_numbers(payout_item)
        if _normalize_numbers(bet_type, payout_numbers) == target_numbers:
            return _coerce_int(payout_item.get("payout"))
    return 0


def _normalize_numbers(bet_type: str, numbers: List[int]) -> Tuple[int, ...]:
    if bet_type in _UNORDERED_BET_TYPES:
        return tuple(sorted(numbers))
    return tuple(numbers)


def _calculate_actual_payout(stake_yen: int, payout_per_100: int) -> int:
    if stake_yen <= 0 or payout_per_100 <= 0:
        return 0
    return int(round(float(payout_per_100) * (float(stake_yen) / 100.0)))


def _coerce_int(value: Any) -> int:
    return int(value or 0)


def _generate_proposals(
    *,
    axis_eval: dict,
    ev_rank_analysis: list,
    data_gap_analysis: dict,
    axis_type: str,
    top_unknown_x: str,
) -> list:
    proposals = []
    pid = [1]

    def add(category, observation, impact, proposal, priority):
        proposals.append(
            {
                "id": f"P{pid[0]}",
                "category": category,
                "observation": observation,
                "impact": impact,
                "proposal": proposal,
                "priority": priority,
            }
        )
        pid[0] += 1

    winner = next((x for x in ev_rank_analysis if x.get("position") == 1), None)
    if winner and not winner.get("in_portfolio"):
        ev_rank = winner.get("ev_rank")
        ev_val = winner.get("ev")
        ev_text = f"EV={ev_val:.3f}" if ev_val is not None else "EV不明"
        rank_text = f"EV{ev_rank}位" if ev_rank else "EV圏外"
        add(
            category="portfolio",
            observation=f"1着#{winner['number']}{winner['name']}（{rank_text}, {ev_text}）はポートフォリオ外",
            impact="1着馬を買えなかったため直接的な収益機会を逃した",
            proposal=f"ポートフォリオの対象馬を広げる、または{rank_text}でも購入対象に含まれる買い目設計を検討",
            priority="high" if (ev_rank and ev_rank <= 5) else "medium",
        )

    if not axis_eval.get("functioned") and axis_eval.get("finish_position") is not None:
        pos = axis_eval["finish_position"]
        add(
            category="axis",
            observation=f"軸#{axis_eval['number']}{axis_eval.get('name', '')}（Type{axis_type}/X={top_unknown_x}）→{pos}着（軸不発）",
            impact=f"Type{axis_type}ポートフォリオは軸馬の上位入着を前提としており、今回は構造的に外れた",
            proposal=f"X={top_unknown_x}かつTypeAを使う条件を見直す。軸単勝オッズ閾値や複数軸戦略を検討",
            priority="high" if axis_type == "A" else "medium",
        )

    if top_unknown_x == "X-High" and axis_type == "B" and axis_eval.get("functioned"):
        add(
            category="axis",
            observation=f"X-High判定でTypeB強制→軸は{axis_eval['finish_position']}着（機能）",
            impact="X-HighによるTypeA禁止が今回は過剰に保守的だった可能性",
            proposal="X-High判定の条件（体重変化、休養日数等）の閾値を個別に再評価",
            priority="low",
        )

    if data_gap_analysis.get("winning_combo_affected"):
        trio_missing = data_gap_analysis["trio_missing"]
        trio_total = data_gap_analysis["trio_total"]
        add(
            category="data",
            observation=f"3連複データ欠損（{trio_total - trio_missing}/{trio_total}件取得）→勝利コンボはデータ欠損範囲",
            impact="3連複の正確なオッズが不明なままポートフォリオを組んだ",
            proposal="3連複データ欠損時は3連複ベットを抑制し、代わりに馬連・ワイドへ振替するフォールバック追加",
            priority="medium",
        )
    elif data_gap_analysis["trio_missing"] > 0:
        pct = int(100 * data_gap_analysis["trio_missing"] / max(data_gap_analysis["trio_total"], 1))
        if pct > 20:
            add(
                category="data",
                observation=f"3連複データ欠損率 {pct}%（{data_gap_analysis['trio_missing']}/{data_gap_analysis['trio_total']}件欠損）",
                impact="高欠損率のまま3連複を購入している可能性",
                proposal="欠損率が一定以上の場合は3連複ベットを自動スキップするガード追加",
                priority="low",
            )

    return proposals


def compute_post_race_analysis(
    *,
    locked_plan: dict,
    result: dict,
) -> dict:
    """
    Analyze algorithm performance post-race and generate improvement proposals.

    Returns:
    {
      "axis_eval": {
        "number": int, "name": str, "finish_position": int|None,
        "axis_type": str, "unknown_x": str,
        "functioned": bool,
      },
      "ev_rank_analysis": [
        {
          "position": 1, "number": int, "name": str,
          "ev_rank": int,
          "ev": float,
          "in_portfolio": bool,
        }, ...
      ],
      "data_gap_analysis": {
        "trio_missing": int,
        "trio_total": int,
        "trifecta_missing": int,
        "trifecta_total": int,
        "winning_combo_affected": bool,
      },
      "proposals": [
        {
          "id": "P1",
          "category": "portfolio",
          "observation": str,
          "impact": str,
          "proposal": str,
          "priority": "high" | "medium" | "low",
        }, ...
      ],
    }
    """
    engine_result = locked_plan.get("engine_result") or {}
    portfolio_bets = locked_plan.get("portfolio") or []
    collector_result = locked_plan.get("collector_result") or {}

    candidates = engine_result.get("candidates") or []
    top_candidate = engine_result.get("top_candidate") or {}
    axis_number = top_candidate.get("number")
    axis_type = engine_result.get("axis_type") or "?"
    top_unknown_x = engine_result.get("top_unknown_x") or "X-None"

    finish_order = result.get("finish_order") or []
    top3 = finish_order[:3]

    ev_rank_by_number = {}
    for rank, c in enumerate(candidates, start=1):
        n = c.get("number")
        if n is not None:
            ev_rank_by_number[n] = {"rank": rank, "ev": c.get("expected_value")}

    portfolio_numbers = set()
    for bet in portfolio_bets:
        if bet.get("number") is not None:
            portfolio_numbers.add(_coerce_int(bet["number"]))
        for n in bet.get("numbers") or []:
            portfolio_numbers.add(_coerce_int(n))

    axis_finish_position = None
    for item in finish_order:
        if _coerce_int(item.get("number") or item.get("horse_number")) == axis_number:
            axis_finish_position = item.get("position") or item.get("place")
            break
    # Axis "functions" if in top-2, OR in top-3 when portfolio has TRIO/WIDE bets
    portfolio_has_trio_or_wide = any(
        bet.get("bet_type") in ("TRIO", "WIDE") for bet in portfolio_bets
    )
    if portfolio_has_trio_or_wide:
        axis_functioned = axis_finish_position in (1, 2, 3) if axis_finish_position is not None else False
    else:
        axis_functioned = axis_finish_position in (1, 2) if axis_finish_position is not None else False

    axis_eval = {
        "number": axis_number,
        "name": top_candidate.get("name"),
        "finish_position": axis_finish_position,
        "axis_type": axis_type,
        "unknown_x": top_unknown_x,
        "functioned": axis_functioned,
    }

    ev_rank_analysis = []
    for item in top3:
        pos = item.get("position") or item.get("place")
        num = _coerce_int(item.get("number") or item.get("horse_number"))
        name = item.get("name") or item.get("horse_name") or "?"
        rank_info = ev_rank_by_number.get(num) or {}
        ev_rank_analysis.append(
            {
                "position": pos,
                "number": num,
                "name": name,
                "ev_rank": rank_info.get("rank"),
                "ev": rank_info.get("ev"),
                "in_portfolio": num in portfolio_numbers,
            }
        )

    extra_odds = collector_result.get("extra_odds") or {}
    n_field = len(collector_result.get("entries") or [])
    trio_combos_theoretical = max(0, (n_field * (n_field - 1) * (n_field - 2)) // 6) if n_field >= 3 else 0
    trio_combos_actual = len(extra_odds.get("trio") or [])
    trio_missing = max(0, trio_combos_theoretical - trio_combos_actual) if trio_combos_theoretical > 0 else 0

    trifecta_combos_theoretical = max(0, n_field * (n_field - 1) * (n_field - 2)) if n_field >= 3 else 0
    trifecta_combos_actual = len(extra_odds.get("trifecta") or [])
    trifecta_missing = max(0, trifecta_combos_theoretical - trifecta_combos_actual) if trifecta_combos_theoretical > 0 else 0

    winning_combo_numbers = tuple(
        sorted(_coerce_int(item.get("number") or item.get("horse_number")) for item in top3)
    )
    trio_numbers_in_data = set()
    for trio_item in extra_odds.get("trio") or []:
        horses = trio_item.get("horses") or trio_item.get("numbers") or []
        combo = tuple(sorted(_coerce_int(n) for n in horses))
        trio_numbers_in_data.add(combo)
    winning_combo_affected = (
        len(winning_combo_numbers) == 3 and winning_combo_numbers not in trio_numbers_in_data and trio_combos_theoretical > 0
    )

    data_gap_analysis = {
        "trio_missing": trio_missing,
        "trio_total": trio_combos_theoretical,
        "trifecta_missing": trifecta_missing,
        "trifecta_total": trifecta_combos_theoretical,
        "winning_combo_affected": winning_combo_affected,
    }

    proposals = _generate_proposals(
        axis_eval=axis_eval,
        ev_rank_analysis=ev_rank_analysis,
        data_gap_analysis=data_gap_analysis,
        axis_type=axis_type,
        top_unknown_x=top_unknown_x,
    )

    return {
        "axis_eval": axis_eval,
        "ev_rank_analysis": ev_rank_analysis,
        "data_gap_analysis": data_gap_analysis,
        "proposals": proposals,
    }
