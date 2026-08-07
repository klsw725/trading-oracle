from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from io import StringIO
import warnings

import numpy as np
from numpy.typing import NDArray
import pandas as pd  # noqa: PANDAS_OK - statsmodels requires pandas inputs
from statsmodels.tools.sm_exceptions import InfeasibleTestError, ValueWarning
from statsmodels.tsa.stattools import adfuller, grangercausalitytests

from .statistical_models import MappingRecord, SeriesFrame, SeriesLink, VerificationConfig


type FloatVector = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class PairFrame:
    timestamps: tuple[datetime, ...]
    subject: FloatVector
    object: FloatVector


@dataclass(frozen=True, slots=True)
class SplitFrame:
    full: PairFrame
    train: PairFrame
    embargo: PairFrame
    holdout: PairFrame


@dataclass(frozen=True, slots=True)
class SplitProblem:
    reason: str


@dataclass(frozen=True, slots=True)
class Stationarity:
    values: FloatVector
    order: int
    p_value: float


@dataclass(frozen=True, slots=True)
class GrangerEvidence:
    lag: int
    p_value: float
    f_stat: float
    direction_match: bool
    rows: int


@dataclass(frozen=True, slots=True)
class WindowEvidence:
    window_id: str
    rows: int
    p_value: float
    direction_match: bool
    mean_shift: float
    variance_ratio: float
    status: str


def _raw_series(frame: SeriesFrame) -> pd.Series[float]:
    values = {item.timestamp: float(item.value) for item in frame.observations}
    return pd.Series(values, dtype="float64").sort_index()


def _transform(values: pd.Series[float], link: SeriesLink) -> pd.Series[float]:
    operations = {
        "level": lambda: values,
        "diff_1d": lambda: values.diff(1),
        "pct_change_1d": lambda: values.pct_change(1, fill_method=None),
        "pct_change_5d": lambda: values.pct_change(5, fill_method=None),
        "pct_change_20d": lambda: values.pct_change(20, fill_method=None),
        "spread": lambda: values,
        "custom_formula": lambda: values,
    }
    return operations[link.transform]()


def mapped_series(mapping: MappingRecord, frames: dict[str, SeriesFrame]) -> pd.Series[float]:
    transformed = {
        link.series_id: _transform(_raw_series(frames[link.series_id]), link)
        for link in mapping.series_links
    }
    if mapping.mapping_kind == "single_series":
        return transformed[mapping.series_links[0].series_id]
    table = pd.concat(transformed, axis=1)
    if mapping.formula is None:
        return pd.Series(dtype="float64")
    evaluated = table.eval(mapping.formula, engine="python")
    if not isinstance(evaluated, pd.Series):
        return pd.Series(dtype="float64")
    return evaluated.astype("float64")


def _pair_frame(table: pd.DataFrame) -> PairFrame:
    if not isinstance(table.index, pd.DatetimeIndex):
        return PairFrame((), np.array([], dtype=np.float64), np.array([], dtype=np.float64))
    timestamps = tuple(table.index.to_pydatetime().tolist())
    subject = table["subject"].to_numpy(dtype=np.float64)
    object_ = table["object"].to_numpy(dtype=np.float64)
    return PairFrame(timestamps, subject, object_)


def align_and_split(subject: pd.Series[float], object_: pd.Series[float], config: VerificationConfig) -> SplitFrame | SplitProblem:
    aligned = pd.concat({"subject": subject, "object": object_}, axis=1)
    aligned = aligned.replace([np.inf, -np.inf], np.nan).dropna().sort_index()
    rows = len(aligned)
    if rows == 0:
        return SplitProblem("no_aligned_rows")
    train_rows = int((Decimal(rows) * config.train_fraction).to_integral_value(rounding=ROUND_FLOOR))
    expected_embargo = int((Decimal(rows) * config.embargo_fraction).to_integral_value(rounding=ROUND_HALF_UP))
    if config.embargo_sessions != expected_embargo:
        return SplitProblem("embargo_sessions_do_not_match_10_percent")
    holdout_start = train_rows + config.embargo_sessions
    expected_holdout = rows - train_rows - expected_embargo
    if rows - holdout_start != expected_holdout or holdout_start >= rows:
        return SplitProblem("split_policy_rows_invalid")
    return SplitFrame(
        _pair_frame(aligned),
        _pair_frame(aligned.iloc[:train_rows]),
        _pair_frame(aligned.iloc[train_rows:holdout_start]),
        _pair_frame(aligned.iloc[holdout_start:]),
    )


def stationary(values: FloatVector, alpha: float, max_order: int) -> Stationarity | None:
    current = values.copy()
    for order in range(max_order + 1):
        if len(current) < 12 or np.ptp(current) == 0:
            return None
        try:
            p_value = float(adfuller(current, maxlag=1, autolag="t-stat")[1])
        except (ValueError, np.linalg.LinAlgError):
            return None
        if p_value < alpha:
            return Stationarity(current, order, p_value)
        current = np.diff(current)
    return None


def difference(values: FloatVector, order: int) -> FloatVector:
    return np.diff(values, n=order) if order else values.copy()


def granger(subject: FloatVector, object_: FloatVector, lag: int, expected_sign: int) -> GrangerEvidence | None:
    rows = min(len(subject), len(object_))
    if rows <= lag + 3:
        return None
    data = np.column_stack((object_[-rows:], subject[-rows:]))
    try:
        with redirect_stdout(StringIO()), warnings.catch_warnings():
            warnings.simplefilter("ignore", ValueWarning)
            result = grangercausalitytests(data, [lag])
        f_stat, p_value, _, _ = result[lag][0]["ssr_ftest"]
    except (ValueError, InfeasibleTestError, np.linalg.LinAlgError):
        return None
    lagged_subject = subject[-rows:-lag]
    aligned_object = object_[-rows + lag :]
    subject_std = float(np.std(lagged_subject))
    object_std = float(np.std(aligned_object))
    if subject_std == 0 or object_std == 0:
        return None
    covariance = float(np.mean((lagged_subject - np.mean(lagged_subject)) * (aligned_object - np.mean(aligned_object))))
    correlation = covariance / (subject_std * object_std)
    if not np.isfinite(f_stat) or not np.isfinite(p_value) or f_stat < 0:
        return None
    return GrangerEvidence(lag, float(p_value), float(f_stat), correlation * expected_sign > 0, rows - lag)


def signed(values: FloatVector, mapping: MappingRecord) -> FloatVector:
    directions = {link.direction for link in mapping.series_links}
    return -values if directions == {"inverse"} else values


def structural_window(window_id: str, frame: PairFrame, baseline: PairFrame, lag: int, expected_sign: int, config: VerificationConfig) -> WindowEvidence:
    rows = min(len(frame.subject), len(frame.object))
    if rows < config.min_window_rows:
        return WindowEvidence(window_id, rows, 1.0, False, 0.0, 1.0, "inconclusive")
    evidence = granger(frame.subject, frame.object, lag, expected_sign)
    baseline_std = max(float(np.std(baseline.subject)), float(np.std(baseline.object)))
    baseline_var = max(float(np.var(baseline.subject)), float(np.var(baseline.object)))
    if evidence is None or baseline_std == 0 or baseline_var == 0:
        return WindowEvidence(window_id, rows, 1.0, False, 0.0, 1.0, "inconclusive")
    mean_shift = max(abs(float(np.mean(frame.subject) - np.mean(baseline.subject))), abs(float(np.mean(frame.object) - np.mean(baseline.object)))) / baseline_std
    window_var = max(float(np.var(frame.subject)), float(np.var(frame.object)))
    variance_ratio = max(window_var / baseline_var, baseline_var / window_var) if window_var > 0 else float("inf")
    failed = not evidence.direction_match or mean_shift > float(config.max_mean_shift) or variance_ratio > float(config.max_variance_ratio)
    return WindowEvidence(window_id, rows, evidence.p_value, evidence.direction_match, mean_shift, variance_ratio, "fail" if failed else "pass")
