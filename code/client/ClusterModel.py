import warnings

import pandas as pd

warnings.filterwarnings("ignore")

from sklearn.cluster import Birch
from sklearn.ensemble import RandomForestRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


class ClusterModel:
    def __init__(
        self,
        df: pd.DataFrame = None,
        X: pd.DataFrame = None,
        Y: pd.Series = None,
        empty: bool = False,
    ):
        self.init_constants()

        if empty:
            self.X = pd.DataFrame(
                columns=list(set(self.cluster_metrics + self.model_metrics))
            )
            self.Y = pd.Series()
            return

        self.df = df[(df["Average Performance"] > 5)]

        self.X = self.df[list(set(self.cluster_metrics + self.model_metrics))]
        self.Y = self.df["Normalized Performance"]

        if X is not None:
            self.X = X
        if Y is not None:
            self.Y = Y

    def init_constants(self):
        self.cluster_metrics = [
            "ctx_switches 75percentile",
            "interrupts 75percentile",
            "readbytes 75percentile",
            "soft_interrupts 75percentile",
            "writebytes 75percentile",
            "ctx_switches IQR",
            "interrupts IQR",
            "readbytes IQR",
            "soft_interrupts IQR",
            "writebytes IQR",
            "Performance",
        ]
        self.model_metrics = [
            "ctx_switches 25percentile",
            "interrupts 25percentile",
            "readbytes 25percentile",
            "soft_interrupts 25percentile",
            "writebytes 25percentile",
            "ctx_switches median",
            "interrupts median",
            "readbytes median",
            "soft_interrupts median",
            "writebytes median",
            "Performance",
        ]

    def update_model(self, df):
        df = df[(df["Average Performance"] > 5)]
        self.X = pd.concat(
            [self.X, df[list(set(self.cluster_metrics + self.model_metrics))]]
        )
        self.Y = pd.concat([self.Y, df["Normalized Performance"]])

    def predict(self, x):
        ys = []
        for _, x in x.iterrows():
            X_local = pd.concat([self.X, pd.DataFrame([x])], ignore_index=True)

            clustering = Pipeline(
                [
                    ("scaler", StandardScaler()),
                    ("cluster", Birch(n_clusters=None, threshold=0.95)),
                ]
            )
            clusters = clustering.fit_predict(X_local[self.cluster_metrics])
            cluster_generator = range(clusters.max() + 1)

            in_cluster = clusters == clustering.predict([x[self.cluster_metrics]])

            X_filtered = X_local[in_cluster]
            X_filtered.drop(X_filtered.tail(1).index, inplace=True)
            y_filtered = self.Y[in_cluster[:-1]]

            # no data points like this one
            if len(X_filtered) == 0:
                ys.append(0)
                continue

            model = Pipeline(
                [
                    ("scaler", StandardScaler()),
                    (
                        "ridge",
                        RandomForestRegressor(
                            n_estimators=100,
                            max_depth=3,
                            max_features=4,
                            criterion="friedman_mse",
                        ),
                    ),
                ]
            )
            model.fit(X_filtered[self.model_metrics], y_filtered)
            ys.append(model.predict([x[self.model_metrics]])[0])
        return ys

    def dump(self, filepath: str):
        self.X.to_csv(f"{filepath}_X.csv")
        self.Y.to_csv(f"{filepath}_Y.csv")
