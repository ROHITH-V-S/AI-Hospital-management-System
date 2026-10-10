"""The Forecast agent's model: next-week occupancy for every hospital.

Target
    Inpatient occupancy (census / staffed beds) ``h`` weeks after the week the
    forecast is made, for h = 1, 2, 4.

Model
    One gradient-boosted tree model shared by all hospitals
    (``sklearn.ensemble.HistGradientBoostingRegressor``, absolute-error loss).
    It handles missing inputs natively, which matters: an untrusted report is
    passed as *missing*, never as a guessed value.

Inputs (all known at forecast time -- nothing from after week t)
    The hospital's own last four weekly occupancies, their mean and spread,
    the value 52 weeks before the target week, ICU occupancy, the share of
    patients with COVID-19 and its one-week change, the same three signals for
    the hospital's state and for the nation, bed count, hospital type, metro
    flag, and the target week's position in the year.

Uncertainty
    Split-conformal intervals: absolute errors on a calibration window the
    model never trained on give, per hospital-size quartile, the half-width
    that covered 90% of outcomes. Reported coverage on the *test* window shows
    whether that promise held.

Time split (by target week; no row crosses a boundary)
    train  2020-08-02 .. 2022-06-26
    calib  2022-07-03 .. 2022-12-25
    test   2023-01-01 .. 2024-04-21

Trust ablation
    ``trusted=True`` masks every RED or MISSING report before building inputs
    and drops untrusted targets from training. ``trusted=False`` uses every
    report as published. Both are scored only on test weeks whose true value is
    trusted -- an untrusted report cannot be the answer key.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

START = pd.Timestamp("2020-08-02")
TRAIN_END = pd.Timestamp("2022-06-26")
CALIB_END = pd.Timestamp("2022-12-25")
TEST_END = pd.Timestamp("2024-04-21")
HORIZONS = (1, 2, 4)
COVERAGE = 0.90
SUBTYPES = ("Short Term", "Critical Access Hospitals")

FEATURES = [
    "occ_0", "occ_1", "occ_2", "occ_3", "occ_mean4", "occ_std4", "occ_lastyear",
    "icu_occ_0", "covid_share_0", "covid_share_d1",
    "state_occ_0", "state_occ_d1", "state_covid_0", "state_covid_d1",
    "nat_covid_0", "nat_covid_d1",
    "log_beds", "critical_access", "metro", "woy_sin", "woy_cos",
]


@dataclass
class Panel:
    """Week x hospital matrices, aligned. Rows are weeks, columns hospitals."""
    weeks: pd.DatetimeIndex
    hospitals: pd.Index
    occ: pd.DataFrame
    used: pd.DataFrame
    beds: pd.DataFrame
    icu_occ: pd.DataFrame
    covid_share: pd.DataFrame
    trusted: pd.DataFrame          # True where the report is usable (GREEN/AMBER)
    info: pd.DataFrame             # per hospital: state, subtype, metro, lat, lon, name


def build_panel(df: pd.DataFrame, levels: pd.Series, trusted: bool = True) -> Panel:
    """Pivot the canonical frame into aligned matrices.

    With ``trusted=True`` values from RED/MISSING reports become NaN.
    """
    d = df[df["subtype"].isin(SUBTYPES) & (df["week"] >= START)
           & (df["week"] <= TEST_END)].copy()
    lv = levels.loc[d.index]
    ok = lv.isin(["GREEN", "AMBER"])
    if trusted:
        for c in ("used", "beds", "icu_used", "icu_beds", "covid_used"):
            d.loc[~ok, c] = np.nan
    weeks = pd.date_range(START, TEST_END, freq="7D")

    def piv(col):
        return d.pivot(index="week", columns="hospital_pk", values=col).reindex(weeks)

    used, beds = piv("used"), piv("beds")
    with np.errstate(divide="ignore", invalid="ignore"):
        occ = used / beds.where(beds > 0)
        icu_occ = piv("icu_used") / piv("icu_beds").where(piv("icu_beds") > 0)
        covid = piv("covid_used") / used.where(used > 0)
    d["_ok"] = ok
    tr = (d.pivot(index="week", columns="hospital_pk", values="_ok")
          .reindex(weeks).reindex(columns=occ.columns))
    tr = tr.astype("boolean").fillna(False).astype(bool)
    info = (d.sort_values("week").groupby("hospital_pk")
            [["state", "subtype", "metro", "lat", "lon", "name", "city"]].last())
    info = info.reindex(occ.columns)
    return Panel(weeks, occ.columns, occ, used, beds, icu_occ, covid, tr, info)


def _state_signal(panel: Panel, num: pd.DataFrame, den: pd.DataFrame) -> pd.DataFrame:
    """Ratio of state totals, broadcast back to each hospital's column."""
    state = panel.info["state"]
    both = num.notna() & den.notna()
    n = num.where(both).T.groupby(state).sum(min_count=1).T
    m = den.where(both).T.groupby(state).sum(min_count=1).T
    ratio = n / m.where(m > 0)
    return ratio.reindex(columns=state.values).set_axis(panel.hospitals, axis=1)


def features(panel: Panel, h: int) -> pd.DataFrame:
    """Long frame: one row per (forecast week t, hospital), inputs at t, target at t+h."""
    occ = panel.occ
    cols = {
        "occ_0": occ, "occ_1": occ.shift(1), "occ_2": occ.shift(2), "occ_3": occ.shift(3),
    }
    stack4 = np.stack([cols[f"occ_{k}"].to_numpy() for k in range(4)])
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            cols["occ_mean4"] = pd.DataFrame(np.nanmean(stack4, 0), occ.index, occ.columns)
            cols["occ_std4"] = pd.DataFrame(np.nanstd(stack4, 0), occ.index, occ.columns)
    cols["occ_lastyear"] = occ.shift(52 - h)
    cols["icu_occ_0"] = panel.icu_occ
    cols["covid_share_0"] = panel.covid_share
    cols["covid_share_d1"] = panel.covid_share - panel.covid_share.shift(1)
    covid_used = panel.covid_share * panel.used
    s_occ = _state_signal(panel, panel.used, panel.beds)
    s_cov = _state_signal(panel, covid_used, panel.used)
    cols["state_occ_0"], cols["state_occ_d1"] = s_occ, s_occ - s_occ.shift(1)
    cols["state_covid_0"], cols["state_covid_d1"] = s_cov, s_cov - s_cov.shift(1)
    both = covid_used.notna() & panel.used.notna()
    nat = covid_used.where(both).sum(1) / panel.used.where(both).sum(1)
    nat_df = pd.DataFrame(np.repeat(nat.to_numpy()[:, None], occ.shape[1], 1),
                          occ.index, occ.columns)
    cols["nat_covid_0"], cols["nat_covid_d1"] = nat_df, nat_df - nat_df.shift(1)
    cols["log_beds"] = np.log1p(panel.beds.ffill(limit=4))

    long = {k: v.to_numpy().ravel() for k, v in cols.items()}
    W, H = occ.shape
    t_week = np.repeat(panel.weeks.to_numpy(), H)
    target_week = t_week + np.timedelta64(7 * h, "D")
    woy = pd.DatetimeIndex(target_week).isocalendar().week.to_numpy().astype(float)
    long["woy_sin"] = np.sin(2 * np.pi * woy / 52.18)
    long["woy_cos"] = np.cos(2 * np.pi * woy / 52.18)
    long["critical_access"] = np.tile(
        (panel.info["subtype"] == "Critical Access Hospitals").to_numpy(float), W)
    long["metro"] = np.tile(panel.info["metro"].astype(float).to_numpy(), W)

    out = pd.DataFrame(long)
    out["week"] = t_week
    out["target_week"] = target_week
    out["hospital_pk"] = np.tile(panel.hospitals.to_numpy(), W)
    out["y"] = occ.shift(-h).to_numpy().ravel()
    out["y_trusted"] = panel.trusted.shift(-h, fill_value=False).to_numpy(bool).ravel()
    out["beds_0"] = panel.beds.to_numpy().ravel()
    # Persistence baselines use the most recent available value (up to 3 weeks back).
    out["base_last"] = out["occ_0"].fillna(out["occ_1"]).fillna(out["occ_2"]).fillna(out["occ_3"])
    out["base_mean4"] = out["occ_mean4"]
    out["base_lastyear"] = out["occ_lastyear"]
    return out


def split(fr: pd.DataFrame) -> dict[str, pd.DataFrame]:
    tw = fr["target_week"]
    return {
        "train": fr[(tw <= TRAIN_END)],
        "calib": fr[(tw > TRAIN_END) & (tw <= CALIB_END)],
        "test": fr[(tw > CALIB_END) & (tw <= TEST_END)],
    }


@dataclass
class Forecaster:
    """Fitted point model plus conformal half-widths per bed-size quartile."""
    h: int
    model: HistGradientBoostingRegressor
    size_edges: np.ndarray
    halfwidth: dict[int, float] = field(default_factory=dict)

    def size_bucket(self, beds: np.ndarray) -> np.ndarray:
        b = np.nan_to_num(beds, nan=np.nanmedian(beds) if np.isfinite(beds).any() else 0)
        return np.searchsorted(self.size_edges, b, side="right")

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        inputs = X if isinstance(self.model, _Persistence) else X[FEATURES]
        point = np.clip(self.model.predict(inputs), 0.0, 1.5)
        hw = np.array([self.halfwidth.get(int(k), np.nan)
                       for k in self.size_bucket(X["beds_0"].to_numpy())])
        return pd.DataFrame({"pred": point, "lo": np.clip(point - hw, 0, None),
                             "hi": point + hw}, index=X.index)


def _conformal(res: np.ndarray, buckets: np.ndarray, n_buckets: int) -> dict[int, float]:
    out = {}
    for k in range(n_buckets):
        r = np.sort(res[buckets == k])
        n = len(r)
        if n == 0:
            continue
        q = min(1.0, np.ceil((n + 1) * COVERAGE) / n)
        out[k] = float(np.quantile(r, q, method="higher"))
    return out


class _Persistence:
    """'Next week = the latest trusted week', wrapped to look like a model."""

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return X["base_last"].to_numpy()


def fit_persistence(fr: pd.DataFrame, h: int) -> "Forecaster":
    """The no-machine-learning baseline, given the same conformal treatment.

    So that when the coordinator runs on persistence instead of the model, the
    only thing that changes is the forecast -- not how uncertainty is handled.
    """
    parts = split(fr)
    tr = parts["train"]
    edges = np.nanquantile(tr["beds_0"], [0.25, 0.5, 0.75])
    fc = Forecaster(h, _Persistence(), edges)            # type: ignore[arg-type]
    cal = parts["calib"]
    cal = cal[cal["y_trusted"] & cal["y"].notna() & cal["base_last"].notna()]
    res = np.abs(cal["y"].to_numpy() - cal["base_last"].to_numpy())
    fc.halfwidth = _conformal(res, fc.size_bucket(cal["beds_0"].to_numpy()), len(edges) + 1)
    return fc


def fit(fr: pd.DataFrame, h: int, train_on_untrusted: bool = False,
        seed: int = 0) -> Forecaster:
    parts = split(fr)
    tr = parts["train"]
    tr = tr[tr["y"].notna() & tr["occ_0"].notna()]
    if not train_on_untrusted:
        tr = tr[tr["y_trusted"]]
    model = HistGradientBoostingRegressor(
        loss="absolute_error", max_iter=400, learning_rate=0.05,
        max_leaf_nodes=31, min_samples_leaf=200, l2_regularization=1.0,
        random_state=seed)
    model.fit(tr[FEATURES], tr["y"])
    edges = np.nanquantile(tr["beds_0"], [0.25, 0.5, 0.75])
    fc = Forecaster(h, model, edges)

    cal = parts["calib"]
    cal = cal[cal["y_trusted"] & cal["y"].notna() & cal["occ_0"].notna()]
    res = np.abs(cal["y"].to_numpy() - np.clip(model.predict(cal[FEATURES]), 0, 1.5))
    fc.halfwidth = _conformal(res, fc.size_bucket(cal["beds_0"].to_numpy()), len(edges) + 1)
    return fc
