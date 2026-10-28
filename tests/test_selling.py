"""Pure price-planning tests; no Home Assistant runtime or inverter required."""

from __future__ import annotations

import importlib.util
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "custom_components/deye_tou_manager/selling.py"
SPEC = importlib.util.spec_from_file_location("deye_selling_planner", MODULE)
SELLING = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELLING)


def price_day(day: date, hourly: list[float]) -> list[dict]:
    start_day = datetime.combine(day, time())
    records = []
    for hour, price in enumerate(hourly):
        for minute in (0, 15, 30, 45):
            start = start_day + timedelta(hours=hour, minutes=minute)
            end = start + timedelta(minutes=15)
            end_label = (f"{day} 24:00:00" if hour == 23 and minute == 45
                         else end.strftime("%Y-%m-%d %H:%M:%S"))
            records.append({
                "business_date": day.isoformat(),
                "period": f"{start:%H:%M} - {end:%H:%M}",
                "dtime": end_label,
                "rce_pln": str(price),
            })
    return records


class SellingPlannerTests(unittest.TestCase):
    day = date(2026, 10, 26)

    def test_hourly_averages_and_unit_conversion(self):
        records = price_day(self.day, [500.0] * 24)
        records[4]["rce_pln"] = "800"
        self.assertAlmostEqual(SELLING.hourly_prices(records, self.day, "PLN/MWh")[1], .575)
        self.assertAlmostEqual(SELLING.hourly_prices(records, self.day, "PLN/kWh")[1], 575)

    def test_selects_individual_one_hour_ranges_and_ranks_them(self):
        hourly = [100.0] * 24
        hourly[7:9] = [600.0, 700.0]
        hourly[16:19] = [900.0, 950.0, 800.0]
        hourly[21] = 550.0
        plan = SELLING.make_sell_plan(
            price_day(self.day, hourly), self.day, "PLN/MWh",
            threshold=.5, max_ranges=2, time_of_day="any",
        )
        self.assertEqual([(r["start"], r["end"]) for r in plan["ranges"]],
                         [("16:00", "17:00"), ("17:00", "18:00")])
        self.assertEqual(plan["ranges"][1]["average_price"], .95)

    def test_morning_preference_stops_at_noon(self):
        hourly = [500.0] * 24
        hourly[11] = 900.0
        hourly[12] = 1000.0
        plan = SELLING.make_sell_plan(
            price_day(self.day, hourly), self.day, "PLN/MWh",
            threshold=.8, max_ranges=2, time_of_day="morning",
        )
        self.assertEqual([(r["start"], r["end"]) for r in plan["ranges"]],
                         [("11:00", "12:00")])

    def test_evening_range_excludes_ended_hours_but_keeps_current_hour(self):
        hourly = [100.0] * 24
        hourly[16], hourly[18], hourly[21] = 900.0, 1000.0, 800.0
        plan = SELLING.make_sell_plan(
            price_day(self.day, hourly), self.day, "PLN/MWh",
            threshold=.5, max_ranges=3, time_of_day="evening",
            now=datetime(2026, 10, 26, 18, 20),
        )
        self.assertEqual([(r["start"], r["end"]) for r in plan["ranges"]],
                         [("18:00", "19:00"), ("21:00", "22:00")])

    def test_missing_quarter_and_duplicate_fail_closed(self):
        records = price_day(self.day, [500.0] * 24)
        with self.assertRaises(SELLING.SellingPlanError):
            SELLING.hourly_prices(records[:-1], self.day, "PLN/MWh")
        with self.assertRaises(SELLING.SellingPlanError):
            SELLING.hourly_prices(records + records[:1], self.day, "PLN/MWh")

    def test_wrong_date_or_timestamp_fails_closed(self):
        records = price_day(self.day, [500.0] * 24)
        records[0]["business_date"] = "2026-10-27"
        with self.assertRaises(SELLING.SellingPlanError):
            SELLING.hourly_prices(records, self.day, "PLN/MWh")
        records = price_day(self.day, [500.0] * 24)
        records[0]["dtime"] = "2026-10-26 01:15:00"
        with self.assertRaises(SELLING.SellingPlanError):
            SELLING.hourly_prices(records, self.day, "PLN/MWh")

    def test_rejects_invalid_settings(self):
        records = price_day(self.day, [500.0] * 24)
        for settings in (
            {"threshold": -.1, "max_ranges": 2, "time_of_day": "any"},
            {"threshold": .5, "max_ranges": 0, "time_of_day": "any"},
            {"threshold": .5, "max_ranges": 2, "time_of_day": "night"},
        ):
            with self.assertRaises(SELLING.SellingPlanError):
                SELLING.make_sell_plan(records, self.day, "PLN/MWh", **settings)


if __name__ == "__main__":
    unittest.main()
