"""Build the per-week decision inputs. Shared by RQ3 and the live platform.

``base_frame`` puts, on one row per hospital-week: what was reported, whether
it is trusted, the last trusted bed count, and what was reported the week
after (used only for scoring). ``arm_frame`` then chooses which forecast and
which trust rule a given strategy is allowed to use.
"""

from __future__ import annotations

import pandas as pd

from ..forecast.model import CALIB_END, SUBTYPES, TEST_END

FIRST_DECISION = CALIB_END
LAST_DECISION = TEST_END - pd.Timedelta(days=7)
ARMS = ("mahros", "greedy", "persistence", "no_trust", "oracle")


def base_frame(df: pd.DataFrame, first=FIRST_DECISION, last=LAST_DECISION) -> pd.DataFrame:
    d = df[df["subtype"].isin(SUBTYPES)][
        ["hospital_pk", "name", "city", "week", "state", "lat", "lon", "used", "beds",
         "level", "flags"]].copy()
    d["ok"] = d["level"].isin(["GREEN", "AMBER"])
    d = d.sort_values(["hospital_pk", "week"]).reset_index(drop=True)
    # Beds the coordinator may rely on: the latest trusted figure, at most 4 weeks old.
    d["beds_trusted"] = (d["beds"].where(d["ok"]).groupby(d["hospital_pk"]).ffill(limit=4))
    nxt = d[["hospital_pk", "week", "used", "beds", "ok"]].copy()
    nxt["week"] = nxt["week"] - pd.Timedelta(days=7)
    d = d.merge(nxt.rename(columns={"used": "used_next", "beds": "beds_next",
                                    "ok": "trusted_next"}),
                on=["hospital_pk", "week"], how="left")
    d["trusted_next"] = d["trusted_next"].astype("boolean").fillna(False).astype(bool)
    return d[(d["week"] >= first) & (d["week"] <= last)].reset_index(drop=True)


def arm_frame(base: pd.DataFrame, fc: pd.DataFrame, arm: str) -> pd.DataFrame:
    """Inputs a strategy is allowed to see: pred, hi, beds, can_receive."""
    f = base.merge(fc, on=["hospital_pk", "week"], how="left")
    if arm in ("mahros", "greedy"):
        f["pred"], f["hi"], f["beds_use"], f["can_receive"] = (
            f["ml_pred"], f["ml_hi"], f["beds_trusted"], f["ok"])
    elif arm == "persistence":
        f["pred"], f["hi"], f["beds_use"], f["can_receive"] = (
            f["persist_pred"], f["persist_hi"], f["beds_trusted"], f["ok"])
    elif arm == "no_trust":
        f["pred"], f["hi"], f["beds_use"] = f["raw_pred"], f["raw_hi"], f["beds"]
        f["can_receive"] = f["beds"].notna() & f["used"].notna()
    elif arm == "oracle":
        occ = f["used_next"] / f["beds_next"]
        f["pred"] = occ.where(f["trusted_next"])
        f["hi"] = f["pred"]
        f["beds_use"] = f["beds_next"]
        f["can_receive"] = f["trusted_next"]
    else:
        raise ValueError(arm)
    f["can_receive"] = f["can_receive"].astype("boolean").fillna(False).astype(bool)
    return f.drop(columns=["beds"]).rename(columns={"beds_use": "beds"})
