"""Unit tests for the demand-forecasting and replenishment maths."""
import math

from backend.app.services import forecast as fc


class TestDemandClassification:
    def test_steady_daily_demand_is_smooth(self):
        assert fc.classify_demand([4, 5, 4, 4, 5, 4, 5, 4])["pattern"] == "smooth"

    def test_regular_gaps_are_intermittent(self):
        series = [0, 0, 2, 0, 0, 2, 0, 0, 2, 0, 0, 2]
        assert fc.classify_demand(series)["pattern"] == "intermittent"

    def test_rare_and_wildly_varying_demand_is_lumpy(self):
        series = [0] * 10 + [30] + [0] * 10 + [1] + [0] * 5 + [18]
        assert fc.classify_demand(series)["pattern"] == "lumpy"

    def test_frequent_but_erratic_demand_is_erratic(self):
        assert fc.classify_demand([1, 12, 2, 20, 1, 15, 3, 11])["pattern"] == "erratic"

    def test_a_never_sold_item_has_no_pattern(self):
        info = fc.classify_demand([0] * 90)
        assert info["pattern"] == "none"
        assert info["occurrences"] == 0

    def test_average_demand_interval_is_measured(self):
        # 3 sales across 12 days: one sale roughly every 4 days.
        info = fc.classify_demand([0, 0, 2, 0, 0, 0, 2, 0, 0, 2, 0, 0])
        assert info["adi"] == 4.0


class TestCroston:
    def test_rate_approximates_observed_demand(self):
        """3 sales of 2 units over 12 days is 0.5/day; SBA sits just under."""
        rate = fc.croston_sba([0, 0, 2, 0, 0, 0, 2, 0, 0, 2, 0, 0])
        assert 0.4 < rate < 0.7

    def test_no_sales_forecasts_zero(self):
        assert fc.croston_sba([0] * 30) == 0.0

    def test_sba_is_below_plain_croston(self):
        """The Syntetos-Boylan correction removes Croston's known upward bias."""
        series = [0, 0, 3, 0, 0, 3, 0, 0, 3]
        alpha = 0.1
        sba = fc.croston_sba(series, alpha)
        plain = sba / (1 - alpha / 2)
        assert sba < plain


class TestHolt:
    def test_rising_demand_projects_upward(self):
        level, trend = fc.holt_linear([1, 2, 3, 4, 5, 6, 7, 8])
        assert trend > 0
        assert level + trend > 8 * 0.5

    def test_falling_demand_projects_downward(self):
        _, trend = fc.holt_linear([10, 9, 8, 7, 6, 5, 4, 3])
        assert trend < 0

    def test_flat_series_has_no_trend(self):
        level, trend = fc.holt_linear([5] * 12)
        assert abs(trend) < 0.01
        assert abs(level - 5) < 0.01


class TestForecastSelection:
    def test_intermittent_series_uses_croston(self):
        _, info = fc.forecast_daily_rate([0, 0, 2, 0, 0, 2, 0, 0, 2, 0, 0, 2])
        assert info["method"] == "croston-sba"

    def test_smooth_series_uses_holt(self):
        _, info = fc.forecast_daily_rate([4, 5, 4, 4, 5, 4, 5, 4])
        assert info["method"] == "holt"

    def test_forecast_never_goes_negative(self):
        rate, _ = fc.forecast_daily_rate([9, 7, 5, 3, 1, 0, 0, 0])
        assert rate >= 0

    def test_forecast_cannot_run_away_from_observed_volume(self):
        series = [0] * 20 + [50]
        rate, _ = fc.forecast_daily_rate(series)
        assert rate <= fc._mean(series) * 3


class TestSeasonality:
    def test_saturday_spike_is_detected(self):
        # 12 weeks; index 5 of each week is triple the other days.
        series = []
        for _ in range(12):
            series += [2, 2, 2, 2, 2, 6, 2]
        indices = fc.seasonal_indices(series, 7)
        assert indices[5] == max(indices)
        assert indices[5] > 1.5

    def test_indices_average_to_one(self):
        series = [1, 2, 3, 4, 5, 6, 7] * 8
        indices = fc.seasonal_indices(series, 7)
        assert abs(fc._mean(indices) - 1.0) < 1e-9

    def test_short_series_returns_neutral_indices(self):
        assert fc.seasonal_indices([1, 2, 3], 7) == [1.0] * 7


class TestReplenishment:
    def test_safety_stock_rises_with_volatility(self):
        steady = fc.safety_stock(1.0, 7, 14)
        volatile = fc.safety_stock(4.0, 7, 14)
        assert volatile > steady

    def test_zero_variability_needs_no_buffer(self):
        assert fc.safety_stock(0.0, 7, 14) == 0.0

    def test_reorder_point_covers_lead_time_demand(self):
        """With no variability the reorder point is exactly lead-time demand."""
        assert fc.reorder_point(2.0, 10, 0, 0.0) == 20.0

    def test_longer_lead_time_raises_the_reorder_point(self):
        assert fc.reorder_point(2.0, 30, 0, 1.0) > fc.reorder_point(2.0, 7, 0, 1.0)

    def test_eoq_matches_the_wilson_formula(self):
        # sqrt(2 * 1000 * 150 / (40 * 0.25)) = sqrt(30000) ~= 173.2
        assert abs(fc.economic_order_quantity(1000, 150, 40, 0.25) - math.sqrt(30000)) < 0.01

    def test_eoq_is_zero_without_demand(self):
        assert fc.economic_order_quantity(0, 150, 40) == 0.0

    def test_eoq_is_zero_for_a_free_item(self):
        """A zero unit cost has no carrying cost, so the formula cannot apply."""
        assert fc.economic_order_quantity(1000, 150, 0) == 0.0

    def test_days_of_cover(self):
        assert fc.days_of_cover(20, 2.0) == 10.0

    def test_unsold_stock_has_unlimited_cover(self):
        assert fc.days_of_cover(20, 0.0) is None


class TestClassification:
    def test_abc_puts_the_top_earners_in_a(self):
        rows = [{"sku": "A1", "value": 800}, {"sku": "B1", "value": 150},
                {"sku": "C1", "value": 40}, {"sku": "C2", "value": 10}]
        ranked = fc.abc_classify(rows)
        by_sku = {r["sku"]: r["abc"] for r in ranked}
        assert by_sku["A1"] == "A"
        assert by_sku["C2"] == "C"

    def test_abc_handles_a_shop_with_no_sales(self):
        ranked = fc.abc_classify([{"sku": "X", "value": 0}])
        assert ranked[0]["abc"] == "C"

    def test_xyz_grades_predictability(self):
        assert fc.xyz_class(0.1) == "X"
        assert fc.xyz_class(0.7) == "Y"
        assert fc.xyz_class(3.0) == "Z"

    def test_movement_classes(self):
        assert fc.movement_class(0.5, 2, 90) == "fast"     # ~15/month
        assert fc.movement_class(0.1, 10, 90) == "medium"  # ~3/month
        assert fc.movement_class(0.02, 40, 90) == "slow"   # ~0.6/month
        assert fc.movement_class(0.0, None, 90) == "dead"

    def test_long_unsold_item_is_dead_however_fast_it_once_was(self):
        assert fc.movement_class(1.0, 200, 365) == "dead"


class TestUrgency:
    def test_out_of_stock_a_class_item_is_most_urgent(self):
        assert fc.urgency_score(0, 10, 1.0, "A") > fc.urgency_score(0, 10, 1.0, "C")

    def test_well_stocked_item_is_not_urgent(self):
        assert fc.urgency_score(500, 10, 0.5, "A") == 0.0

    def test_score_stays_within_bounds(self):
        for on_hand in (0, 1, 50, 1000):
            for rop in (0, 5, 100):
                score = fc.urgency_score(on_hand, rop, 2.0, "A")
                assert 0.0 <= score <= 100.0
