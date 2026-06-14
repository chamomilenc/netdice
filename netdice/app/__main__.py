import argparse
import csv
import glob
import os
import time
from dataclasses import dataclass

from netdice.explorer import Explorer
from netdice.input_parser import InputParser
from netdice.my_logging import log
from netdice.util import get_relative_to_working_directory


@dataclass
class BenchmarkRunResult:
    elapsed_ms: int
    states: int
    imprecision: float
    prob_low: float
    prob_high: float
    timed_out: bool


def _median_ms(values):
    if not values:
        return 0
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return int(round((s[n // 2 - 1] + s[n // 2]) / 2.0))


def run_once(problems, timeout_s, target=1.0e-4):
    """Run one NetDice exploration pass over all problems of a network.

    Time excludes file loading.
    """
    t = time.time()
    states = 0
    worst_imprecision = 0.0
    prob_lows = []
    prob_highs = []
    for problem in problems:
        problem.target_precision = target
        sol = Explorer(problem).explore_all(timeout_s)
        states += sol.num_explored
        imprecision = sol.p_explored.invert().val()
        prob_low = sol.p_property.val()
        prob_high = prob_low + imprecision
        worst_imprecision = max(worst_imprecision, imprecision)
        prob_lows.append(prob_low)
        prob_highs.append(prob_high)
    elapsed = time.time() - t
    return BenchmarkRunResult(
        int(round(elapsed * 1000)),
        states,
        worst_imprecision,
        min(prob_lows) if prob_lows else 0.0,
        max(prob_highs) if prob_highs else 0.0,
        elapsed >= timeout_s)


def benchmark_one(group, path, args, writer):
    network = os.path.splitext(os.path.basename(path))[0]
    try:
        parser = InputParser(path, None)
        problems = parser.get_problems()  # load once (excluded from timing)
    except Exception as e:  # noqa: BLE001 - report and continue on malformed input
        log.warning("load failed for %s/%s: %s", group, network, e)
        return
    nodes = problems[0].nof_nodes
    links = problems[0].nof_links
    log.info("--- %s/%s (nodes=%d, links=%d) ---", group, network, nodes, links)

    results = []
    states = 0
    timed_out = False
    for run in range(args.benchmark_runs):
        result = run_once(problems, args.benchmark_timeout)
        results.append(result)
        states = result.states
        log.info("    run %d: %d ms, states=%d, imprecision=%.3e%s",
                 run + 1, result.elapsed_ms, result.states, result.imprecision,
                 " (TIMEOUT)" if result.timed_out else "")
        if result.timed_out:
            timed_out = True
            break  # stop remaining runs

    times = [r.elapsed_ms for r in results]
    time_max = max(times) if times else 0
    time_median = _median_ms(times)
    states_sequence = ";".join(str(r.states) for r in results)
    cells = [group, network, nodes, links, len(results), timed_out, states,
             states_sequence, time_max, time_median]
    for i in range(args.benchmark_runs):
        if i < len(results):
            result = results[i]
            cells.append(result.elapsed_ms)
            cells.append("{:.6e}".format(result.imprecision))
            cells.append("{:.6e}".format(result.prob_low))
            cells.append("{:.6e}".format(result.prob_high))
        else:
            cells.append("")
            cells.append("")
            cells.append("")
            cells.append("")
    writer.writerow(cells)


def run_benchmark(args):
    out_path = args.benchmark_out
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    fresh = not os.path.exists(out_path)

    log.info("=== netdice benchmark ===")
    log.info("  output: %s", os.path.abspath(out_path))
    log.info("  timeout/run: %d s, runs: %d, limit/group: %s",
             args.benchmark_timeout, args.benchmark_runs,
             "all" if args.benchmark_limit == 0 else args.benchmark_limit)

    with open(out_path, "a", newline="") as fout:
        writer = csv.writer(fout)
        if fresh:
            header = ["group", "network", "nodes", "links", "runs", "timed_out", "states",
                      "states_sequence", "time_max_ms", "time_median_ms"]
            for i in range(1, args.benchmark_runs + 1):
                header.append("run{}_ms".format(i))
                header.append("run{}_imprecision".format(i))
                header.append("run{}_prob_low".format(i))
                header.append("run{}_prob_high".format(i))
            writer.writerow(header)
            fout.flush()

        for group in ["mrinfo", "mrinfo-ext", "zoo"]:
            group_dir = os.path.join(args.benchmark_dir, group)
            if not os.path.isdir(group_dir):
                log.warning("  skip missing group dir: %s", group_dir)
                continue
            files = sorted(glob.glob(os.path.join(group_dir, "*.json")))
            if args.benchmark_limit > 0:
                files = files[:args.benchmark_limit]
            for path in files:
                benchmark_one(group, path, args, writer)
                fout.flush()
    log.info("=== benchmark complete ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser("netdice.app")
    parser.add_argument("input_file", nargs='?', default=None,
                        help='file name of input file (.json format)', type=str)
    parser.add_argument('-q', '--query', help='file name of query file (.json format)', type=str)
    parser.add_argument('-p', '--precision', default=1.0E-5, help='target precision of result (default: 1.0E-5)', type=float)
    parser.add_argument('--quiet', action="store_true", help='only print results to console, no logs')
    parser.add_argument('--debug', action="store_true", help='print debug log to console')
    parser.add_argument('--colt-figure', action="store_true",
                        help='run the given input at fixed precision 1e-6 and write '
                             'results/colt_netdice.csv (states,imprecision); ignores -p')
    parser.add_argument('--benchmark', action="store_true",
                        help='run NetDice over experiment/generated/{mrinfo,mrinfo-ext,zoo} and '
                             'write results/benchmark_netdice.csv; ignores input_file/-p')
    parser.add_argument('--benchmark-dir', default=os.path.join("experiment", "generated"),
                        help='root dir of generated scenarios (default: experiment/generated)')
    parser.add_argument('--benchmark-timeout', default=3600, type=int,
                        help='per-run timeout in seconds for --benchmark (default: 3600)')
    parser.add_argument('--benchmark-runs', default=5, type=int,
                        help='runs per network for --benchmark (default: 5)')
    parser.add_argument('--benchmark-limit', default=0, type=int,
                        help='max networks per group for --benchmark (0=all)')
    parser.add_argument('--benchmark-out', default=os.path.join("results", "benchmark_netdice.csv"),
                        help='output CSV for --benchmark')
    args = parser.parse_args()

    if args.debug:
        log.initialize('DEBUG')
    elif args.quiet:
        log.initialize('WARNING')
    else:
        log.initialize('INFO')

    if args.benchmark:
        run_benchmark(args)
        exit(0)

    if args.input_file is None:
        parser.error("input_file is required unless --benchmark is given")

    input_file = get_relative_to_working_directory(args.input_file)
    query_file = None
    if args.query:
        query_file = get_relative_to_working_directory(args.query)

    parser = InputParser(input_file, query_file)

    if args.colt_figure:
        problems = parser.get_problems()
        problem = problems[0]
        problem.target_precision = 1.0E-6
        explorer = Explorer(problem, stat_prec=True)
        sol = explorer.explore_all()

        out_dir = "results"
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "colt_netdice.csv")
        with open(out_path, 'w') as f:
            f.write("states,imprecision\n")
            f.write("0,1.0\n")  # before any state is explored, all mass is unexplored
            for states, imprecision in explorer.prec_trace:
                f.write("{},{}\n".format(states, imprecision))

        p_low = sol.p_property.val()
        p_up = sol.p_property.val() + sol.p_explored.invert().val()
        log.info("colt figure csv: {}".format(os.path.abspath(out_path)))
        log.info("explored states: {}".format(sol.num_explored))
        log.info("precision: {}".format(sol.p_explored.invert().val()))
        print("P({}) ∈ [{:8.8f}, {:8.8f}]".format(
            problem.property.get_human_readable(parser.name_resolver), p_low, p_up))
        exit(0)

    problems = parser.get_problems()
    for problem in problems:
        problem.target_precision = args.precision
        explorer = Explorer(problem)
        sol = explorer.explore_all()

        log.info("explored states: {}".format(sol.num_explored))
        log.info("precision: {}".format(sol.p_explored.invert().val()))

        p_low = sol.p_property.val()
        p_up = sol.p_property.val() + sol.p_explored.invert().val()

        print("P({}) ∈ [{:8.8f}, {:8.8f}]".format(
            problem.property.get_human_readable(parser.name_resolver), p_low, p_up))
