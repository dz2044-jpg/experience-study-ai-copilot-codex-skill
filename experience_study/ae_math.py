"""A/E ratio and confidence interval math."""

from __future__ import annotations

import pandas as pd
from scipy import stats


def compute_mortality_rate_ci(
    mac: float,
    moc: float,
    confidence_level: float = 0.95,
) -> tuple[float | None, float | None]:
    """Compute a beta-binomial mortality rate confidence interval."""

    if pd.isna(mac) or pd.isna(moc) or moc <= 0 or mac < 0 or mac > moc:
        return (None, None)
    alpha_beta = mac + 0.5
    beta_beta = moc - mac + 0.5
    lower_quantile = (1 - confidence_level) / 2
    upper_quantile = 1 - lower_quantile
    return (
        stats.beta.ppf(lower_quantile, alpha_beta, beta_beta),
        stats.beta.ppf(upper_quantile, alpha_beta, beta_beta),
    )


def compute_ae_ci(
    mac: float,
    moc: float,
    mec: float,
    confidence_level: float = 0.95,
) -> tuple[float | None, float | None]:
    """Compute count A/E confidence interval bounds."""

    rate_lower, rate_upper = compute_mortality_rate_ci(mac, moc, confidence_level)
    if rate_lower is None or rate_upper is None or mec <= 0:
        return (None, None)
    return (rate_lower * moc / mec, rate_upper * moc / mec)


def compute_ae_ci_amount(
    mac: float,
    moc: float,
    mec: float,
    actual_amount: float,
    expected_amount: float,
    confidence_level: float = 0.95,
) -> tuple[float | None, float | None]:
    """Compute amount A/E confidence interval bounds using average claim size."""

    if (
        pd.isna(mac)
        or pd.isna(moc)
        or pd.isna(mec)
        or pd.isna(actual_amount)
        or pd.isna(expected_amount)
        or mec <= 0
        or expected_amount <= 0
    ):
        return (None, None)

    average_claim = actual_amount / mac if mac > 0 else expected_amount / mec
    rate_lower, rate_upper = compute_mortality_rate_ci(mac, moc, confidence_level)
    if rate_lower is None or rate_upper is None:
        return (None, None)
    return (
        rate_lower * moc * average_claim / expected_amount,
        rate_upper * moc * average_claim / expected_amount,
    )
