import os
import shutil
import string

import numpy as np
import pandas as pd

import dask
import dask.dataframe as dd

from benchmarks.common import DaskSuite, rnd


def mkdf(rows=1000, files=50, n_floats=4, n_ints=4, n_strs=4):
    N = 1000
    r = rnd()
    floats = pd.DataFrame(r.randn(N, n_floats))
    ints = pd.DataFrame(
        r.randint(0, 100, size=(N, n_ints)),
        columns=np.arange(n_floats, n_floats + n_ints),
    )
    strs = pd.DataFrame(
        r.choice(list(string.ascii_letters), (N, n_strs)),
        columns=np.arange(n_floats + n_ints, n_floats + n_ints + n_strs),
    )

    df = pd.concat([floats, ints, strs], axis=1).rename(columns=lambda x: "c_" + str(x))
    return df


class CSV(DaskSuite):
    params = ["single-threaded", "processes", "threads"]
    data_dir = "benchmark_data"
    n_files = 30

    def setup_cache(self):
        df = mkdf()
        if not os.path.exists(self.data_dir):
            os.mkdir(self.data_dir)

        for i in range(self.n_files):
            df.to_csv(f"{self.data_dir}/{i}.csv", index=False)

    def teardown_cache(self):
        shutil.rmtree(self.data_dir)

    def time_read_csv_meta(self, scheduler):
        return dd.read_csv(f"{self.data_dir}/*.csv")

    def time_read_csv(self, scheduler):
        return dd.read_csv(f"{self.data_dir}/*.csv").compute(scheduler=scheduler)


class HDF5(DaskSuite):
    params = ["single-threaded", "processes", "threads"]
    data_dir = "benchmark_data"
    n_files = 10

    def setup_cache(self):
        df = mkdf()
        if not os.path.exists(self.data_dir):
            os.mkdir(self.data_dir)

        for i in range(self.n_files):
            df.index += i * len(df)  # for unique index
            df.to_hdf(f"{self.data_dir}/{i}.hdf5", "key", format="table")

    def setup(self, scheduler):
        if scheduler == "processes":
            raise NotImplementedError()

    def teardown_cache(self):
        shutil.rmtree(self.data_dir)

    def time_read_hdf5_meta(self, scheduler):
        dd.read_hdf(f"{self.data_dir}/*.hdf5", "key")

    def time_read_hdf5(self, scheduler):
        (dd.read_hdf(f"{self.data_dir}/*.hdf5", "key").compute(scheduler=scheduler))


class Parquet(DaskSuite):
    def setup_cache(self):
        ts = dask.datasets.timeseries()
        ts.to_parquet("data.parquet", engine="pyarrow")

    def time_optimize_getitem(self):
        df = dd.read_parquet("data.parquet", engine="pyarrow")
        dask.optimize(df)

    def time_read_getitem_projection(self):
        df = dd.read_parquet("data.parquet", engine="pyarrow")
        result = df[["x", "y"]]
        result.compute()

    def teardown_cache(self):
        try:
            shutil.rmtree("data.parquet")
        except Exception as e:
            print("ignoring exception", e)
            pass
