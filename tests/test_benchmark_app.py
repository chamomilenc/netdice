import csv
import importlib
import os
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch


def _install_probpy_stub():
    probpy = types.ModuleType("ProbPy")

    class RandVar:
        def __init__(self, *args, **kwargs):
            pass

    class Factor:
        def __init__(self, *args, **kwargs):
            pass

    class Event:
        pass

    class BayesianNetwork:
        pass

    class BayesianNetworkNode:
        def __init__(self, *args, **kwargs):
            pass

    probpy.RandVar = RandVar
    probpy.Factor = Factor
    probpy.Event = Event
    probpy.BayesianNetwork = BayesianNetwork
    probpy.BayesianNetworkNode = BayesianNetworkNode
    sys.modules["ProbPy"] = probpy


def _load_app():
    try:
        importlib.import_module("ProbPy")
        stubbed = False
    except ModuleNotFoundError:
        _install_probpy_stub()
        stubbed = True
    return importlib.import_module("netdice.app.__main__"), stubbed


def _cleanup_probpy_stub():
    for module in [
            "netdice.app.__main__",
            "netdice.explorer",
            "netdice.problem",
            "netdice.failures",
            "netdice.bayesian_network",
            "ProbPy"]:
        sys.modules.pop(module, None)


class BenchmarkAppTest(unittest.TestCase):

    def test_run_benchmark_skips_networks_already_in_output_csv(self):
        app, stubbed = _load_app()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                for group in ["mrinfo", "mrinfo-ext", "zoo"]:
                    os.makedirs(os.path.join(tmpdir, group))
                group_dir = os.path.join(tmpdir, "mrinfo")
                for network in ["toy", "zed"]:
                    with open(os.path.join(group_dir, "{}.json".format(network)), "w"):
                        pass
                out_path = os.path.join(tmpdir, "benchmark_netdice.csv")
                header = ["group", "network", "nodes", "links", "runs", "timed_out", "states",
                          "states_sequence", "time_max_ms", "time_median_ms",
                          "run1_ms", "run1_imprecision", "run1_prob_low", "run1_prob_high",
                          "run2_ms", "run2_imprecision", "run2_prob_low", "run2_prob_high"]
                old_row = ["mrinfo", "toy", "1", "2", "1", "False", "3", "3", "4", "4",
                           "4", "1.000000e-03", "0.000000e+00", "1.000000e-03",
                           "", "", "", ""]
                with open(out_path, "w", newline="") as fout:
                    writer = csv.writer(fout)
                    writer.writerow(header)
                    writer.writerow(old_row)

                args = SimpleNamespace(
                    benchmark_dir=tmpdir,
                    benchmark_limit=0,
                    benchmark_out=out_path,
                    benchmark_runs=2,
                    benchmark_timeout=60)
                problem = SimpleNamespace(nof_nodes=7, nof_links=9)
                results = [
                    app.BenchmarkRunResult(10, 12, 0.001, 0.2, 0.201, False),
                    app.BenchmarkRunResult(30, 14, 0.002, 0.4, 0.402, False),
                ]

                with patch.object(app, "InputParser") as input_parser, \
                        patch.object(app, "run_once", side_effect=results) as run_once:
                    input_parser.return_value.get_problems.return_value = [problem]

                    app.run_benchmark(args)

                with open(out_path, newline="") as fin:
                    rows = list(csv.reader(fin))
        finally:
            if stubbed:
                _cleanup_probpy_stub()

        self.assertEqual(rows[0], header)
        self.assertEqual(rows[1], old_row)
        self.assertEqual(
            rows[2],
            ["mrinfo", "zed", "7", "9", "2", "False", "14", "12;14", "30", "20",
             "10", "1.000000e-03", "2.000000e-01", "2.010000e-01",
             "30", "2.000000e-03", "4.000000e-01", "4.020000e-01"])
        self.assertEqual(len(rows), 3)
        self.assertEqual(input_parser.call_count, 1)
        self.assertTrue(input_parser.call_args[0][0].endswith(os.path.join("mrinfo", "zed.json")))
        self.assertEqual(run_once.call_count, 2)

    def test_run_benchmark_writes_extended_csv_columns(self):
        app, stubbed = _load_app()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                for group in ["mrinfo", "mrinfo-ext", "zoo"]:
                    os.makedirs(os.path.join(tmpdir, group))
                group_dir = os.path.join(tmpdir, "mrinfo")
                scenario = os.path.join(group_dir, "toy.json")
                with open(scenario, "w"):
                    pass
                out_path = os.path.join(tmpdir, "benchmark_netdice.csv")

                args = SimpleNamespace(
                    benchmark_dir=tmpdir,
                    benchmark_limit=1,
                    benchmark_out=out_path,
                    benchmark_runs=2,
                    benchmark_timeout=60)
                problem = SimpleNamespace(nof_nodes=7, nof_links=9)
                results = [
                    app.BenchmarkRunResult(10, 12, 0.001, 0.2, 0.201, False),
                    app.BenchmarkRunResult(30, 14, 0.002, 0.4, 0.402, False),
                ]

                with patch.object(app, "InputParser") as input_parser, \
                        patch.object(app, "run_once", side_effect=results) as run_once:
                    input_parser.return_value.get_problems.return_value = [problem]

                    app.run_benchmark(args)

                with open(out_path, newline="") as fin:
                    rows = list(csv.reader(fin))
        finally:
            if stubbed:
                _cleanup_probpy_stub()

        self.assertEqual(
            rows[0],
            ["group", "network", "nodes", "links", "runs", "timed_out", "states",
             "states_sequence", "time_max_ms", "time_median_ms",
             "run1_ms", "run1_imprecision", "run1_prob_low", "run1_prob_high",
             "run2_ms", "run2_imprecision", "run2_prob_low", "run2_prob_high"])
        self.assertEqual(
            rows[1],
            ["mrinfo", "toy", "7", "9", "2", "False", "14", "12;14", "30", "20",
             "10", "1.000000e-03", "2.000000e-01", "2.010000e-01",
             "30", "2.000000e-03", "4.000000e-01", "4.020000e-01"])
        self.assertEqual(run_once.call_count, 2)


if __name__ == "__main__":
    unittest.main()
