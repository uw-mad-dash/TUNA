import warnings

import pandas as pd

warnings.filterwarnings("ignore")


class PassthroughModel:
    def __init__(
        self,
        df: pd.DataFrame = None,
        X: pd.DataFrame = None,
        Y: pd.Series = None,
        empty: bool = False,
    ):
        pass

    def init_constants(self):
        pass

    def update_model(self, df):
        pass

    def predict(self, x):
        return [0 for _ in x]

    def dump(self, filepath: str):
        pass
