"""校园资料目录验证分析脚本。

只使用 Python 标准库。默认在项目根目录运行：
    python scripts/analyze.py

也可以指定测试数据目录或输出 JSON：
    python scripts/analyze.py --data-dir path/to/data --json
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
ORGANIC_SOURCES = {"目录自然流量", "免费详情帖", "朋友推荐"}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def read_csv(data_dir: Path, filename: str) -> list[dict[str, str]]:
    path = data_dir / filename
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def to_float(value: object) -> float:
    try:
        return float(str(value or "0").strip())
    except ValueError:
        return 0.0


def parse_rate(value: object) -> float:
    text = str(value or "").strip()
    if text.endswith("%"):
        return to_float(text[:-1]) / 100
    rate = to_float(text)
    return rate / 100 if rate > 1 else rate


def percent(value: float | None) -> str:
    return "暂无数据" if value is None else f"{value:.1%}"


def ratio(numerator: float, denominator: float) -> float | None:
    return None if denominator == 0 else numerator / denominator


def transaction_key(row: dict[str, str]) -> str:
    return (row.get("transaction_id") or row.get("order_id") or "").strip()


def compare(value: float, operator: str, threshold: float) -> bool:
    return {
        ">=": value >= threshold,
        ">": value > threshold,
        "<=": value <= threshold,
        "<": value < threshold,
        "==": value == threshold,
    }.get(operator, False)


def validate_references(
    sellers: list[dict[str, str]],
    materials: list[dict[str, str]],
    listings: list[dict[str, str]],
    orders: list[dict[str, str]],
) -> list[str]:
    errors: list[str] = []
    seller_ids = {row.get("seller_id", "") for row in sellers}
    material_ids = {row.get("material_id", "") for row in materials}
    listing_ids = {row.get("listing_id", "") for row in listings}

    for filename, rows, key in (
        ("sellers.csv", sellers, "seller_id"),
        ("materials.csv", materials, "material_id"),
        ("listings.csv", listings, "listing_id"),
        ("orders.csv", orders, "order_id"),
    ):
        values = [row.get(key, "").strip() for row in rows]
        duplicates = sorted(value for value, count in Counter(values).items() if value and count > 1)
        if duplicates:
            errors.append(f"{filename} 的 {key} 重复：{'、'.join(duplicates)}")

    for row in sellers:
        rate = parse_rate(row.get("commission_rate"))
        if row.get("commission_rate") and not 0 <= rate <= 1:
            errors.append(f"卖家 {row.get('seller_id')} 的抽成比例不在 0 到 1 之间")

    for row in materials:
        if row.get("seller_id") not in seller_ids:
            errors.append(f"资料 {row.get('material_id')} 引用了不存在的卖家 {row.get('seller_id')}")

    for row in listings:
        linked = [row.get("material_id", "").strip()]
        linked += [item.strip() for item in row.get("material_ids", "").split("|")]
        for material_id in filter(None, linked):
            if material_id not in material_ids:
                errors.append(f"发布 {row.get('listing_id')} 引用了不存在的资料 {material_id}")

    for row in orders:
        if row.get("material_id") not in material_ids:
            errors.append(f"订单行 {row.get('order_id')} 引用了不存在的资料 {row.get('material_id')}")
        if row.get("listing_id") and row.get("listing_id") not in listing_ids:
            errors.append(f"订单行 {row.get('order_id')} 引用了不存在的发布 {row.get('listing_id')}")

    return errors


def analyze(data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, object]:
    sellers = read_csv(data_dir, "sellers.csv")
    materials = read_csv(data_dir, "materials.csv")
    listings = read_csv(data_dir, "listings.csv")
    orders = read_csv(data_dir, "orders.csv")
    feedback = read_csv(data_dir, "feedback.csv")
    target_rows = read_csv(data_dir, "validation_targets.csv")

    seller_by_id = {row["seller_id"]: row for row in sellers}
    material_by_id = {row["material_id"]: row for row in materials}
    active_listings = [row for row in listings if row.get("published_at", "").strip()]

    valid_lines = [
        row
        for row in orders
        if row.get("delivery_status") == "已交付" and row.get("refunded") != "是"
    ]
    paid_lines = [row for row in orders if to_float(row.get("amount_paid")) > 0]
    valid_transaction_ids = {transaction_key(row) for row in valid_lines if transaction_key(row)}
    all_paid_transaction_ids = {transaction_key(row) for row in paid_lines if transaction_key(row)}

    total_revenue = sum(to_float(row.get("amount_paid")) for row in valid_lines)
    platform_commission = 0.0
    category_units: Counter[str] = Counter()
    category_revenue: defaultdict[str, float] = defaultdict(float)
    category_transactions: defaultdict[str, set[str]] = defaultdict(set)
    buyer_transactions: defaultdict[str, set[str]] = defaultdict(set)
    transaction_sources: defaultdict[str, set[str]] = defaultdict(set)

    for row in valid_lines:
        material = material_by_id.get(row.get("material_id", ""), {})
        seller = seller_by_id.get(material.get("seller_id", ""), {})
        amount = to_float(row.get("amount_paid"))
        rate = parse_rate(seller.get("commission_rate"))
        platform_commission += amount * rate
        category = material.get("category") or "未分类"
        tx = transaction_key(row)
        category_units[category] += 1
        category_revenue[category] += amount
        if tx:
            category_transactions[category].add(tx)
            transaction_sources[tx].add(row.get("source_channel", "").strip())
        buyer = row.get("buyer_id", "").strip()
        if buyer and tx:
            buyer_transactions[buyer].add(tx)

    promotion_cost = sum(to_float(row.get("promotion_cost")) for row in active_listings)
    total_views = sum(int(to_float(row.get("views"))) for row in active_listings)
    reported_inquiries = sum(int(to_float(row.get("inquiries"))) for row in active_listings)

    feedback_buyers = {row.get("buyer_id", "").strip() for row in feedback if row.get("buyer_id", "").strip()}
    anonymous_feedback = sum(1 for row in feedback if not row.get("buyer_id", "").strip())
    valid_inquiries = len(feedback_buyers) + anonymous_feedback if feedback else reported_inquiries

    unique_buyers = len(buyer_transactions)
    repeat_buyers = sum(1 for transactions in buyer_transactions.values() if len(transactions) >= 2)
    organic_transactions = sum(
        1
        for tx in valid_transaction_ids
        if transaction_sources.get(tx, set()) & ORGANIC_SOURCES
    )
    refunded_transactions = {
        transaction_key(row) for row in paid_lines if row.get("refunded") == "是" and transaction_key(row)
    }
    response_minutes = [
        to_float(row.get("first_response_minutes"))
        for row in feedback
        if str(row.get("first_response_minutes", "")).strip()
    ]

    category_inquiries: Counter[str] = Counter()
    for row in feedback:
        material = material_by_id.get(row.get("material_id", ""), {})
        category = material.get("category")
        if not category:
            offer = row.get("offer_code", "")
            category = {"A": "公共课", "B": "计算机课程", "C": "实验学习参考"}.get(offer[:1], "未分类")
        category_inquiries[category] += 1

    metrics: dict[str, float] = {
        "catalog_views": float(total_views),
        "valid_inquiries": float(valid_inquiries),
        "valid_transactions": float(len(valid_transaction_ids)),
        "unique_buyers": float(unique_buyers),
        "categories_with_orders": float(len(category_transactions)),
        "organic_order_share": ratio(organic_transactions, len(valid_transaction_ids)) or 0.0,
        "promotion_budget": promotion_cost,
        "refund_rate": ratio(len(refunded_transactions), len(all_paid_transaction_ids)) or 0.0,
        "response_minutes": statistics.median(response_minutes) if response_minutes else 0.0,
    }

    gates = []
    for row in target_rows:
        metric = row.get("metric", "")
        value = metrics.get(metric, 0.0)
        threshold = to_float(row.get("threshold"))
        operator = row.get("operator", "")
        has_data = not (
            metric == "response_minutes" and not response_minutes
        )
        gates.append(
            {
                "metric": metric,
                "value": value,
                "operator": operator,
                "threshold": threshold,
                "unit": row.get("unit", ""),
                "passed": compare(value, operator, threshold) if has_data else None,
            }
        )

    transactions = len(valid_transaction_ids)
    if transactions <= 2:
        stage = "0–2单：检查目录封面、时机和品类，暂不继续扩充库存"
    elif transactions <= 4:
        stage = "3–4单：存在弱信号，只修改一个变量后复测"
    elif transactions <= 9:
        stage = "5–9单：暑假需求得到初步证明，扩充表现最好的两个品类"
    else:
        stage = "10单以上：进入30单复验，并在开学季重复目录测试"

    return {
        "metrics": metrics,
        "units_sold": len(valid_lines),
        "total_revenue": total_revenue,
        "platform_commission": platform_commission,
        "seller_payout": total_revenue - platform_commission,
        "promotion_cost": promotion_cost,
        "platform_contribution": platform_commission - promotion_cost,
        "platform_roi": ratio(platform_commission, promotion_cost),
        "conversion_rate": ratio(len(valid_transaction_ids), valid_inquiries),
        "repeat_rate": ratio(repeat_buyers, unique_buyers),
        "category_units": dict(category_units),
        "category_revenue": dict(category_revenue),
        "category_transactions": {key: len(value) for key, value in category_transactions.items()},
        "category_inquiries": dict(category_inquiries),
        "gates": gates,
        "stage": stage,
        "errors": validate_references(sellers, materials, listings, orders),
        "pending_material_reviews": sum(1 for row in materials if row.get("review_status") != "已通过"),
        "planned_promotion_cost": sum(to_float(row.get("promotion_cost")) for row in listings),
    }


def print_report(result: dict[str, object]) -> None:
    metrics = result["metrics"]
    assert isinstance(metrics, dict)
    print("校园资料目录验证概览")
    print("=" * 42)
    print(f"有效浏览：{metrics['catalog_views']:.0f} 次")
    print(f"有效咨询：{metrics['valid_inquiries']:.0f} 人")
    print(f"有效交易：{metrics['valid_transactions']:.0f} 笔（资料行 {result['units_sold']} 份）")
    print(f"不同买家：{metrics['unique_buyers']:.0f} 人")
    print(f"成交品类：{metrics['categories_with_orders']:.0f} 类")
    print(f"总实收：{result['total_revenue']:.2f} 元")
    print(f"平台佣金：{result['platform_commission']:.2f} 元")
    print(f"卖家结算：{result['seller_payout']:.2f} 元")
    print(f"已发生推广费：{result['promotion_cost']:.2f} 元")
    print(f"平台净贡献：{result['platform_contribution']:.2f} 元")
    roi = result["platform_roi"]
    print(f"平台佣金 ROI：{'暂无推广费' if roi is None else f'{roi:.2f}'}")
    print(f"咨询→交易转化率：{percent(result['conversion_rate'])}")
    print(f"自然成交占比：{percent(metrics['organic_order_share'])}")
    print(f"复购买家率：{percent(result['repeat_rate'])}")
    print(f"退款率：{percent(metrics['refund_rate'])}")
    print(f"待完成审核的资料：{result['pending_material_reviews']} 份")
    print(f"全部计划置顶费用：{result['planned_promotion_cost']:.2f} 元（未发布时间不计入实际成本）")

    print("\n验证门槛")
    print("-" * 42)
    for gate in result["gates"]:
        status = "待记录" if gate["passed"] is None else ("通过" if gate["passed"] else "未通过")
        print(
            f"{status}｜{gate['metric']}：{gate['value']:.2f} "
            f"{gate['operator']} {gate['threshold']:.2f} {gate['unit']}"
        )

    print("\n品类表现")
    print("-" * 42)
    categories = sorted(
        set(result["category_units"]) | set(result["category_inquiries"])
    )
    if not categories:
        print("暂无咨询或成交数据")
    for category in categories:
        print(
            f"{category}：咨询 {result['category_inquiries'].get(category, 0)}，"
            f"交易 {result['category_transactions'].get(category, 0)}，"
            f"资料 {result['category_units'].get(category, 0)} 份，"
            f"实收 {result['category_revenue'].get(category, 0):.2f} 元"
        )

    print("\n阶段判断")
    print("-" * 42)
    print(result["stage"])
    if result["errors"]:
        print("\n数据完整性问题")
        print("-" * 42)
        for error in result["errors"]:
            print(f"- {error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="分析校园资料目录验证数据")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--json", action="store_true", help="输出 JSON，便于其他工具读取")
    args = parser.parse_args()
    result = analyze(args.data_dir)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_report(result)


if __name__ == "__main__":
    main()
