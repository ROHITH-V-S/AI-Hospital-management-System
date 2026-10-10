"""ForecastAgent: next week's occupancy for each hospital, with a 90% range.

Serves forecasts produced by the fitted model (``experiments/rq2_forecast.py``),
which only ever used information available at the forecast week.
"""

from __future__ import annotations

import math

import pandas as pd

from .messages import Message


class ForecastAgent:
    address = "forecaster"

    def __init__(self, forecasts: pd.DataFrame) -> None:
        self._f = forecasts.set_index(["hospital_pk", "week"])

    def forecast(self, hospital_id: str, week: pd.Timestamp) -> tuple[float, float]:
        try:
            r = self._f.loc[(hospital_id, week)]
        except KeyError:
            return math.nan, math.nan
        return float(r["ml_pred"]), float(r["ml_hi"])

    def announce(self, hospital_id: str, week: pd.Timestamp) -> Message:
        p, hi = self.forecast(hospital_id, week)
        return Message("FORECAST", self.address, "coordinator", str(week.date()),
                       {"hospital": hospital_id,
                        "occupancy": None if math.isnan(p) else round(p, 4),
                        "upper_90": None if math.isnan(hi) else round(hi, 4)})
