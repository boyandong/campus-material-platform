import csv
import tempfile
import unittest
from pathlib import Path

from scripts.analyze import analyze, parse_rate


HEADERS = {
    "sellers.csv": ["seller_id", "commission_rate"],
    "materials.csv": ["material_id", "seller_id", "category", "review_status"],
    "listings.csv": ["listing_id", "material_id", "material_ids", "published_at", "promotion_cost", "views", "inquiries"],
    "orders.csv": ["order_id", "transaction_id", "buyer_id", "material_id", "listing_id", "amount_paid", "source_channel", "delivery_status", "refunded"],
    "feedback.csv": ["feedback_id", "buyer_id", "material_id", "offer_code", "first_response_minutes"],
    "validation_targets.csv": ["metric", "operator", "threshold", "unit"],
}


def write_csv(folder, filename, rows):
    with (folder / filename).open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=HEADERS[filename])
        writer.writeheader()
        writer.writerows(rows)


class AnalyzeTests(unittest.TestCase):
    def test_rate_parsing_accepts_decimal_and_percent(self):
        self.assertEqual(parse_rate("0.20"), 0.2)
        self.assertEqual(parse_rate("20%"), 0.2)
        self.assertEqual(parse_rate("20"), 0.2)

    def test_catalog_metrics_use_commission_and_unique_transactions(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            write_csv(folder, "sellers.csv", [
                {"seller_id": "S1", "commission_rate": "0.20"},
                {"seller_id": "S2", "commission_rate": "20%"},
            ])
            write_csv(folder, "materials.csv", [
                {"material_id": "A01", "seller_id": "S1", "category": "公共课", "review_status": "已通过"},
                {"material_id": "B01", "seller_id": "S2", "category": "计算机课程", "review_status": "已通过"},
            ])
            write_csv(folder, "listings.csv", [
                {"listing_id": "L1", "material_ids": "A01|B01", "published_at": "2026-08-04 19:00", "promotion_cost": "8.8", "views": "500", "inquiries": "10"},
                {"listing_id": "L2", "material_ids": "A01|B01", "published_at": "", "promotion_cost": "8.8", "views": "0", "inquiries": "0"},
            ])
            rows = []
            for index, (buyer, material, source) in enumerate([
                ("U1", "A01", "目录自然流量"),
                ("U2", "A01", "校园集市目录置顶"),
                ("U3", "B01", "朋友推荐"),
                ("U1", "B01", "校园集市目录置顶"),
                ("U2", "B01", "校园集市目录置顶"),
            ], start=1):
                rows.append({
                    "order_id": f"O{index}", "transaction_id": f"T{index}", "buyer_id": buyer,
                    "material_id": material, "listing_id": "L1", "amount_paid": "5",
                    "source_channel": source, "delivery_status": "已交付", "refunded": "否",
                })
            write_csv(folder, "orders.csv", rows)
            write_csv(folder, "feedback.csv", [])
            write_csv(folder, "validation_targets.csv", [
                {"metric": "catalog_views", "operator": ">=", "threshold": "500", "unit": "次"},
                {"metric": "valid_transactions", "operator": ">=", "threshold": "5", "unit": "笔"},
                {"metric": "organic_order_share", "operator": ">=", "threshold": "0.30", "unit": "比例"},
            ])

            result = analyze(folder)
            self.assertEqual(result["metrics"]["valid_transactions"], 5)
            self.assertEqual(result["metrics"]["unique_buyers"], 3)
            self.assertEqual(result["platform_commission"], 5)
            self.assertEqual(result["seller_payout"], 20)
            self.assertEqual(result["promotion_cost"], 8.8)
            self.assertEqual(result["planned_promotion_cost"], 17.6)
            self.assertAlmostEqual(result["metrics"]["organic_order_share"], 0.4)
            self.assertTrue(all(gate["passed"] for gate in result["gates"]))

    def test_invalid_material_reference_is_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            for filename in HEADERS:
                write_csv(folder, filename, [])
            write_csv(folder, "orders.csv", [{
                "order_id": "O1", "transaction_id": "T1", "buyer_id": "U1",
                "material_id": "MISSING", "listing_id": "", "amount_paid": "5",
                "source_channel": "目录自然流量", "delivery_status": "已交付", "refunded": "否",
            }])
            result = analyze(folder)
            self.assertTrue(any("MISSING" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
