"""共通バリデーション関数 — 感情値・日付パースの検証ロジック"""
from datetime import date

# 感情軸の定数セット（emotion dict / emotion_filter 共通）
VALID_EMOTION_AXES: set[str] = {"joy", "anger", "sorrow", "fun"}


def validateEmotion(emotion: dict | None) -> None:
    """emotion dict のキーと値域を検証する。

    remember / topic_manage で使用。
    キーは VALID_EMOTION_AXES のいずれか、値は 0-255 の整数。

    Args:
        emotion: 感情値辞書 {"joy": 0-255, ...}

    Raises:
        ValueError: 不正なキーまたは値域外の場合
    """
    if not emotion:
        return

    invalid_keys = set(emotion.keys()) - VALID_EMOTION_AXES
    if invalid_keys:
        raise ValueError(f"emotion に不正なキーがあります: {invalid_keys}")

    for key, val in emotion.items():
        if not isinstance(val, int) or not (0 <= val <= 255):
            raise ValueError(f"emotion.{key} は 0〜255 の整数で指定してください: {val}")


def validateEmotionFilter(emotion_filter: dict | None) -> None:
    """emotion_filter のレンジフィルタ構造を検証する。

    recall / organize で使用。
    各軸に {min: int, max: int} 形式のレンジ指定を受け付ける。

    Args:
        emotion_filter: 感情レンジフィルタ {"joy": {"min": 10, "max": 50}, ...}

    Raises:
        ValueError: キーや値が不正な場合
    """
    if not emotion_filter:
        return

    for axis, range_spec in emotion_filter.items():
        if axis not in VALID_EMOTION_AXES:
            raise ValueError(
                f"emotion_filter のキーが不正です: '{axis}'（許可: {', '.join(sorted(VALID_EMOTION_AXES))}）"
            )
        if not isinstance(range_spec, dict):
            raise ValueError(f"emotion_filter['{axis}'] は辞書で指定してください")

        for bound_key, bound_val in range_spec.items():
            if bound_key not in ("min", "max"):
                raise ValueError(
                    f"emotion_filter['{axis}'] に不正なキー '{bound_key}'（許可: min, max）"
                )
            if not isinstance(bound_val, int) or bound_val < 0 or bound_val > 255:
                raise ValueError(
                    f"emotion_filter['{axis}']['{bound_key}'] は 0-255 の整数で指定してください: {bound_val}"
                )

        # min > max の矛盾チェック
        if "min" in range_spec and "max" in range_spec:
            if range_spec["min"] > range_spec["max"]:
                raise ValueError(
                    f"emotion_filter['{axis}'] の min({range_spec['min']}) が max({range_spec['max']}) より大きいです"
                )


def parseDateRange(
    date_from: str | None,
    date_to: str | None,
) -> tuple[date | None, date | None]:
    """日付文字列をパースし、from > to の矛盾を検証する。

    recall / organize で使用。

    Args:
        date_from: 開始日付文字列（YYYY-MM-DD）
        date_to: 終了日付文字列（YYYY-MM-DD）

    Returns:
        (parsed_date_from, parsed_date_to) のタプル

    Raises:
        ValueError: 日付形式が不正、または from > to の場合
    """
    parsed_from = None
    parsed_to = None

    if date_from:
        try:
            parsed_from = date.fromisoformat(date_from)
        except ValueError:
            raise ValueError(f"date_from の形式が不正です（YYYY-MM-DD）: {date_from}")

    if date_to:
        try:
            parsed_to = date.fromisoformat(date_to)
        except ValueError:
            raise ValueError(f"date_to の形式が不正です（YYYY-MM-DD）: {date_to}")

    if parsed_from and parsed_to and parsed_from > parsed_to:
        raise ValueError(
            f"date_from({date_from}) が date_to({date_to}) より後になっています"
        )

    return parsed_from, parsed_to
