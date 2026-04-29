from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


class SoftStopCode:
    """Recoverable / "wait and retry" conditions distinct from HardStopCode.

    The engine returns these when the failure is upstream data lag — not a
    fault. Bot callers should schedule auto-retry, not surface error UX.
    """
    WAITING_ON_DATA = "WAITING_ON_DATA"


SOFT_STOP_MESSAGES = {
    SoftStopCode.WAITING_ON_DATA: (
        "JRA がオッズを順次公開中です。発走 5 分前まで待って再試行してください。"
    ),
}


@dataclass(frozen=True)
class SoftStop:
    code: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def build_soft_stop(code: str, *, details: dict[str, Any] | None = None, reason: str | None = None) -> SoftStop:
    return SoftStop(
        code=code,
        reason=reason or SOFT_STOP_MESSAGES.get(code, code),
        details=details or {},
    )


class HardStopCode:
    REQUEST_PARSE_ERROR = "REQUEST_PARSE_ERROR"
    REQUEST_VALIDATION_ERROR = "REQUEST_VALIDATION_ERROR"
    SNAPSHOT_LOAD_FAILED = "SNAPSHOT_LOAD_FAILED"
    COLLECTOR_RESULT_MISSING = "COLLECTOR_RESULT_MISSING"
    COLLECTOR_FETCH_FAILED = "COLLECTOR_FETCH_FAILED"
    COLLECTOR_RACE_NOT_FOUND = "COLLECTOR_RACE_NOT_FOUND"
    COLLECTOR_PARSE_FAILED = "COLLECTOR_PARSE_FAILED"
    REQUIRED_WIN_ODDS_MISSING = "REQUIRED_WIN_ODDS_MISSING"
    REQUIRED_ODDS_MISSING = "REQUIRED_ODDS_MISSING"
    POSITIVE_EV_NOT_FOUND = "POSITIVE_EV_NOT_FOUND"
    STAKE_CALCULATION_FAILED = "STAKE_CALCULATION_FAILED"
    RACE_IDENTITY_DATE_MISMATCH = "RACE_IDENTITY_DATE_MISMATCH"
    RACE_IDENTITY_VENUE_MISMATCH = "RACE_IDENTITY_VENUE_MISMATCH"
    RACE_IDENTITY_RACE_NUMBER_MISMATCH = "RACE_IDENTITY_RACE_NUMBER_MISMATCH"
    RACE_IDENTITY_RACE_NAME_MISMATCH = "RACE_IDENTITY_RACE_NAME_MISMATCH"
    IMAGE_EXTRACT_MISSING = "IMAGE_EXTRACT_MISSING"
    IMAGE_SCHEMA_INVALID = "IMAGE_SCHEMA_INVALID"
    IMAGE_HORSES_EMPTY = "IMAGE_HORSES_EMPTY"
    IMAGE_HORSE_NUMBER_DUPLICATED = "IMAGE_HORSE_NUMBER_DUPLICATED"
    IMAGE_HORSE_NAME_EMPTY = "IMAGE_HORSE_NAME_EMPTY"
    IMAGE_DATE_MISMATCH = "IMAGE_DATE_MISMATCH"
    IMAGE_RACE_NAME_MISMATCH = "IMAGE_RACE_NAME_MISMATCH"
    IMAGE_HORSE_COUNT_MISMATCH = "IMAGE_HORSE_COUNT_MISMATCH"
    IMAGE_HORSE_MAPPING_MISMATCH = "IMAGE_HORSE_MAPPING_MISMATCH"


DEFAULT_MESSAGES = {
    HardStopCode.REQUEST_PARSE_ERROR: "入力の解析に失敗しました。",
    HardStopCode.REQUEST_VALIDATION_ERROR: "入力の必須項目または形式が不正です。",
    HardStopCode.SNAPSHOT_LOAD_FAILED: "保存済み snapshot の読み込みに失敗しました。",
    HardStopCode.COLLECTOR_RESULT_MISSING: "比較対象の取得結果が不足しています。",
    HardStopCode.COLLECTOR_FETCH_FAILED: "JRA collector の取得に失敗しました。",
    HardStopCode.COLLECTOR_RACE_NOT_FOUND: "指定レースを JRA公式から特定できませんでした。",
    HardStopCode.COLLECTOR_PARSE_FAILED: "JRA collector の解析に失敗しました。",
    HardStopCode.COLLECTOR_FETCH_FAILED: "JRA collector の取得に失敗しました。",
    HardStopCode.COLLECTOR_RACE_NOT_FOUND: "JRA collector が対象レースを特定できませんでした。",
    HardStopCode.COLLECTOR_PARSE_FAILED: "JRA collector の解析に失敗しました。",
    HardStopCode.REQUIRED_WIN_ODDS_MISSING: "Engine 最小版に必要な単勝オッズが欠損しています。",
    HardStopCode.REQUIRED_ODDS_MISSING: "Engine 最小版に必要なオッズが欠損しています。",
    HardStopCode.POSITIVE_EV_NOT_FOUND: "positive EV の候補が見つかりませんでした。",
    HardStopCode.STAKE_CALCULATION_FAILED: "stake 計算に失敗しました。",
    HardStopCode.RACE_IDENTITY_DATE_MISMATCH: "入力と取得結果の日付が一致しません。",
    HardStopCode.RACE_IDENTITY_VENUE_MISMATCH: "入力と取得結果の開催場が一致しません。",
    HardStopCode.RACE_IDENTITY_RACE_NUMBER_MISMATCH: "入力と取得結果のレース番号が一致しません。",
    HardStopCode.RACE_IDENTITY_RACE_NAME_MISMATCH: "入力と取得結果のレース名が一致しません。",
    HardStopCode.IMAGE_EXTRACT_MISSING: "画像整合に必要な抽出済み情報が不足しています。",
    HardStopCode.IMAGE_SCHEMA_INVALID: "画像抽出結果の schema が不正です。",
    HardStopCode.IMAGE_HORSES_EMPTY: "画像抽出結果の horses が空配列です。",
    HardStopCode.IMAGE_HORSE_NUMBER_DUPLICATED: "画像抽出結果の horse.number が重複しています。",
    HardStopCode.IMAGE_HORSE_NAME_EMPTY: "画像抽出結果の horse.name が空文字です。",
    HardStopCode.IMAGE_DATE_MISMATCH: "画像抽出結果と取得結果の日付が一致しません。",
    HardStopCode.IMAGE_RACE_NAME_MISMATCH: "画像抽出結果と取得結果のレース名が一致しません。",
    HardStopCode.IMAGE_HORSE_COUNT_MISMATCH: "画像抽出結果と取得結果の出走頭数が一致しません。",
    HardStopCode.IMAGE_HORSE_MAPPING_MISMATCH: "画像抽出結果と取得結果の馬番-馬名対応が一致しません。",
}


@dataclass(frozen=True)
class HardStop:
    code: str
    reason: str
    details: dict[str, Any] = field(default_factory=dict)
    gate: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)



def build_hard_stop(code: str, *, details: dict[str, Any] | None = None, gate: str | None = None, reason: str | None = None) -> HardStop:
    return HardStop(
        code=code,
        reason=reason or DEFAULT_MESSAGES.get(code, code),
        details=details or {},
        gate=gate,
    )



def format_hard_stop_message(hard_stop: HardStop) -> str:
    suffix = f" gate={hard_stop.gate}" if hard_stop.gate else ""
    return f"HARD_STOP[{hard_stop.code}]{suffix}: {hard_stop.reason}"
