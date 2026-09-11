"""Deterministic internal estimates; no invented market prices or grade premiums."""

import re
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation


def calculate_pricing(
    minimum, quality: dict, commission="0.35", referral="0.10", context=None
) -> dict:
    rate, referral_rate = Decimal(commission), Decimal(referral)
    if not Decimal(0) <= referral_rate <= rate < Decimal(1):
        raise ValueError("佣金比例必须满足 0 <= 推荐人比例 <= 平台比例 < 1")
    result = {
        "platform_commission_rate": str(rate),
        "referral_commission_rate": str(referral_rate),
        "seller_share": str(1 - rate),
        "platform_share_with_referral": str(rate - referral_rate),
        "confidence": "LOW_CONFIDENCE",
        "provenance": "SYSTEM_CALCULATED",
        "requires_human_confirmation": True,
        "pricing_reasoning": [],
    }
    text = str(minimum or "").strip()
    if not re.fullmatch(r"(?:人民币\s*)?[¥￥]?\s*\d+(?:\.\d{1,2})?\s*元?", text):
        return {
            **result,
            "status": "UNKNOWN",
            "pricing_reasoning": ["最低到手价缺失、含区间或不明确，不能猜测售价。"],
        }
    try:
        value = Decimal(re.search(r"\d+(?:\.\d+)?", text).group())
    except (InvalidOperation, AttributeError):
        return {**result, "status": "UNKNOWN"}
    theoretical = value / (1 - rate)
    floor = theoretical.quantize(Decimal("0.01"), rounding=ROUND_CEILING)
    suggested_min = theoretical.to_integral_value(rounding=ROUND_CEILING)
    context = context or {}
    count = sum(quality.get("counts", {}).values())
    effective = quality.get("effective_content_files", 0)
    ratio = Decimal(effective) / Decimal(count) if count else Decimal(0)
    # Explicit experimental rubric, not an estimate of actual market demand.
    factors = {
        "有效内容占比至少80%": ratio >= Decimal(".8"),
        "至少3份有效内容": effective >= 3,
        "来源学院专业明确": bool(context.get("source_known")),
        "年份明确": bool(context.get("year_known")),
        "有实际章节目录": bool(context.get("has_catalog")),
        "有授权样图草稿": bool(context.get("has_previews")),
    }
    markup = Decimal(".05") + Decimal(".04") * sum(factors.values())
    if quality.get("risk_counts", {}).get("YELLOW") or context.get("declared_missing"):
        markup = min(markup, Decimal(".10"))
    list_price = (suggested_min * (1 + markup)).to_integral_value(
        rounding=ROUND_CEILING
    )
    result.update(
        status="DRAFT",
        seller_min_take_home=str(value),
        theoretical_min_sale_price=str(floor),
        recommended_min_sale_price=str(suggested_min),
        recommended_list_price=str(list_price),
        recommended_price_range=[str(suggested_min), str(list_price)],
    )
    result["experimental_markup"] = str(markup)
    result["factors"] = factors
    result["payout_example"] = {
        "sale_price": str(list_price),
        "seller": str(
            (list_price * (1 - rate)).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
        ),
        "referrer": str(
            (list_price * referral_rate).quantize(
                Decimal(".01"), rounding=ROUND_HALF_UP
            )
        ),
        "platform_with_referral": str(
            (list_price * (rate - referral_rate)).quantize(
                Decimal(".01"), rounding=ROUND_HALF_UP
            )
        ),
    }
    result["pricing_reasoning"] = [
        "最低成交价按卖家到手底线和佣金比例计算，并向上取整。",
        "缺少可比成交数据；挂牌范围按明确列出的完整性/来源/目录/样图规则给出试验空间，不是市场价。",
        f"有效内容 {quality.get('effective_content_files', 0)} 份；模板、缺失与风险需先确认，不因成绩声明加价。",
    ]
    if quality.get("risk_counts", {}).get("RED", 0) or quality.get("counts", {}).get(
        "EMPTY_TEMPLATE", 0
    ):
        result["status"] = "HOLD_FOR_REVIEW"
        result["pricing_reasoning"].append(
            "存在红色风险或空模板，暂停对外使用价格建议。"
        )
    return result
