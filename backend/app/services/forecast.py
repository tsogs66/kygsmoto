"""Demand forecasting and replenishment maths.

Pure functions only, so the statistics can be unit-tested without a database.

A parts counter sells most of its 1,800+ SKUs a handful of times a month, so the
series are mostly zeros with occasional spikes.  Classical exponential smoothing
biases badly on that shape, so demand is first classified using the
Syntetos-Boylan scheme (average demand interval vs. squared coefficient of
variation) and intermittent/lumpy series are forecast with Croston's method
(SBA-corrected) instead of Holt's.
"""
import math

# Syntetos-Boylan cut-offs separating smooth / erratic / intermittent / lumpy demand.
ADI_CUTOFF = 1.32
CV2_CUTOFF = 0.49


def _mean(values):
    return sum(values) / len(values) if values else 0.0


def _stdev(values):
    """Sample standard deviation."""
    if len(values) < 2:
        return 0.0
    avg = _mean(values)
    return math.sqrt(sum((v - avg) ** 2 for v in values) / (len(values) - 1))


def classify_demand(series):
    """Classify a demand series as smooth, erratic, intermittent, lumpy or none.

    Returns a dict with the average demand interval (ADI), the squared
    coefficient of variation of non-zero demand sizes (CV2) and the label.
    """
    non_zero = [v for v in series if v > 0]
    if not non_zero:
        return {"pattern": "none", "adi": 0.0, "cv2": 0.0, "periods": len(series),
                "occurrences": 0}

    adi = len(series) / len(non_zero)
    avg_size = _mean(non_zero)
    cv2 = (_stdev(non_zero) / avg_size) ** 2 if avg_size > 0 else 0.0

    if adi < ADI_CUTOFF:
        pattern = "smooth" if cv2 < CV2_CUTOFF else "erratic"
    else:
        pattern = "intermittent" if cv2 < CV2_CUTOFF else "lumpy"

    return {"pattern": pattern, "adi": adi, "cv2": cv2, "periods": len(series),
            "occurrences": len(non_zero)}


def croston_sba(series, alpha=0.1):
    """Croston's method with the Syntetos-Boylan Approximation.

    Smooths demand size and inter-arrival interval separately, then returns the
    per-period demand rate size/interval, de-biased by (1 - alpha/2).
    """
    non_zero_idx = [i for i, v in enumerate(series) if v > 0]
    if not non_zero_idx:
        return 0.0

    # Seed from the series averages rather than the first observation. Seeding
    # from the first gap makes the estimate hostage to one arbitrary event — an
    # item whose first recorded sale opens the window would be seeded with an
    # interval of one day and forecast as an everyday seller.
    size = _mean([series[i] for i in non_zero_idx])
    interval = len(series) / len(non_zero_idx)

    for prev, idx in zip(non_zero_idx, non_zero_idx[1:]):
        size += alpha * (series[idx] - size)
        interval += alpha * ((idx - prev) - interval)

    if interval <= 0:
        return 0.0
    return (1 - alpha / 2) * (size / interval)


def holt_linear(series, alpha=0.3, beta=0.1):
    """Holt's linear (double) exponential smoothing.

    Returns (level, trend); the one-period-ahead forecast is level + trend.
    """
    if not series:
        return 0.0, 0.0
    if len(series) == 1:
        return float(series[0]), 0.0

    level = float(series[0])
    trend = float(series[1] - series[0])
    for value in series[1:]:
        prev_level = level
        level = alpha * value + (1 - alpha) * (level + trend)
        trend = beta * (level - prev_level) + (1 - beta) * trend
    return level, trend


def seasonal_indices(series, period=7):
    """Average-based seasonal indices, normalised to a mean of 1.0.

    With a weekly period this captures the Saturday rush a parts shop sees.
    """
    if len(series) < period * 2:
        return [1.0] * period

    overall = _mean(series)
    if overall <= 0:
        return [1.0] * period

    indices = []
    for offset in range(period):
        bucket = series[offset::period]
        indices.append(_mean(bucket) / overall if bucket else 1.0)

    scale = _mean(indices)
    if scale <= 0:
        return [1.0] * period
    return [i / scale for i in indices]


def forecast_daily_rate(series, alpha=0.1):
    """Forecast the mean daily demand rate for a daily series.

    Picks Croston/SBA for intermittent and lumpy demand and Holt's method for
    smooth and erratic demand, which keeps sparse SKUs from being forecast to
    zero while still tracking trend on the fast movers.
    """
    info = classify_demand(series)
    if info["pattern"] == "none":
        return 0.0, info

    if info["pattern"] in ("intermittent", "lumpy"):
        rate = croston_sba(series, alpha)
        info["method"] = "croston-sba"
    else:
        level, trend = holt_linear(series)
        rate = max(level + trend, 0.0)
        info["method"] = "holt"

    # Guard against a smoothed rate drifting far from observed volume.
    observed = _mean(series)
    if observed > 0:
        rate = min(rate, observed * 3)
    info["mean_daily"] = observed
    return max(rate, 0.0), info


def safety_stock(daily_sigma, lead_time_days, review_days=0.0, z=1.65):
    """Safety stock covering demand variability over lead time plus review period."""
    horizon = max(lead_time_days + review_days, 0.0)
    return z * daily_sigma * math.sqrt(horizon) if horizon > 0 else 0.0


def reorder_point(daily_rate, lead_time_days, review_days=0.0, daily_sigma=0.0, z=1.65):
    """Stock level at which a replenishment order should be raised."""
    horizon = max(lead_time_days + review_days, 0.0)
    return daily_rate * horizon + safety_stock(daily_sigma, lead_time_days, review_days, z)


def economic_order_quantity(annual_demand, order_cost, unit_cost, holding_rate=0.25):
    """Classic Wilson EOQ: the order size balancing ordering and carrying cost."""
    holding_cost = unit_cost * holding_rate
    if annual_demand <= 0 or holding_cost <= 0 or order_cost <= 0:
        return 0.0
    return math.sqrt((2 * annual_demand * order_cost) / holding_cost)


def days_of_cover(on_hand, daily_rate):
    """How many days the current stock lasts; None means effectively unlimited."""
    if daily_rate <= 0:
        return None
    return on_hand / daily_rate


def abc_classify(rows, value_key="value"):
    """Pareto (ABC) classification: A = top 80% of value, B = next 15%, C = rest.

    `rows` is a list of dicts; each gets an "abc" key. Returns the same list
    sorted by descending value.
    """
    ranked = sorted(rows, key=lambda r: r.get(value_key, 0) or 0, reverse=True)
    total = sum(max(r.get(value_key, 0) or 0, 0) for r in ranked)
    if total <= 0:
        for row in ranked:
            row["abc"] = "C"
            row["value_share"] = 0.0
            row["cumulative_share"] = 0.0
        return ranked

    running = 0.0
    for row in ranked:
        value = max(row.get(value_key, 0) or 0, 0)
        # Classify on the share accumulated *before* this row, so the item that
        # crosses a boundary still falls on the near side of it. Without this a
        # single item worth more than 80% of turnover would grade itself out of
        # class A and the shop's best seller would be treated as a C line.
        share_before = running / total
        running += value
        row["value_share"] = value / total
        row["cumulative_share"] = running / total
        row["abc"] = "A" if share_before < 0.80 else ("B" if share_before < 0.95 else "C")
    return ranked


def xyz_class(cv2):
    """Predictability class from the squared coefficient of variation."""
    if cv2 < 0.49:
        return "X"
    if cv2 < 1.0:
        return "Y"
    return "Z"


def movement_class(daily_rate, days_since_last_sale, horizon_days):
    """Bucket an item as fast / medium / slow / dead moving.

    Rates are expressed per 30 days so the thresholds read naturally for a shop
    that thinks in monthly volumes.
    """
    monthly = daily_rate * 30
    if days_since_last_sale is None or days_since_last_sale >= min(horizon_days, 180):
        return "dead"
    if monthly >= 8:
        return "fast"
    if monthly >= 2:
        return "medium"
    if monthly > 0:
        return "slow"
    return "dead"


def urgency_score(on_hand, rop, daily_rate, abc="C"):
    """0-100 ranking of how badly an item needs reordering; higher is worse."""
    weight = {"A": 1.0, "B": 0.75, "C": 0.5}.get(abc, 0.5)

    if rop <= 0:
        shortfall = 1.0 if on_hand <= 0 else 0.0
    else:
        shortfall = max(0.0, (rop - on_hand) / rop)

    cover = days_of_cover(on_hand, daily_rate)
    if cover is None:
        cover_pressure = 0.0
    elif cover <= 0:
        cover_pressure = 1.0
    else:
        cover_pressure = max(0.0, min(1.0, 1 - cover / 30))

    return round(min(100.0, 100 * weight * (0.6 * shortfall + 0.4 * cover_pressure)), 1)
