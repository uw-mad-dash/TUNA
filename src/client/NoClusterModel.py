import warnings

import pandas as pd

warnings.filterwarnings("ignore")


# path hack
import os
import sys

sys.path.insert(0, os.path.abspath(".."))
from benchmarks import Benchmark
from sklearn.ensemble import RandomForestRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


class NoClusterModel:
    def __init__(
        self,
        df: pd.DataFrame = None,
        X: pd.DataFrame = None,
        Y: pd.Series = None,
        empty: bool = False,
    ):
        if empty:
            self.X = None
            self.Y = None
            return

        self.df = df[(df["Average Performance"] > 5)]

        self.X = self.df[self.model_metrics]
        self.Y = self.df["Normalized Performance"]

        if X is not None:
            self.X = X
        if Y is not None:
            self.Y = Y

    def update_model(self, df):
        df = df[(df["Average Performance"] > 5)]

        if self.X is None:
            self.X = df.drop(columns=["Normalized Performance"])
        else:
            self.X = pd.concat([self.X, df.drop(columns=["Normalized Performance"])])
        if self.Y is None:
            self.Y = df["Normalized Performance"]
        else:
            self.Y = pd.concat([self.Y, df["Normalized Performance"]])
        self.model_metrics = self.X.columns

    def predict(self, x):
        model = Pipeline(
            [
                ("scaler", StandardScaler()),
                (
                    "ridge",
                    RandomForestRegressor(
                        n_estimators=1000,
                        criterion="friedman_mse",
                    ),
                ),
            ]
        )
        if self.X is None or len(self.X) == 0:
            return [0]
        model.fit(self.X[self.model_metrics], self.Y)
        return model.predict(x[self.model_metrics])

    def dump(self, filepath: str):
        if self.X is not None and self.Y is not None:
            self.X.to_csv(f"{filepath}_X.csv")
            self.Y.to_csv(f"{filepath}_Y.csv")
        else:
            print("Failed to dump")
