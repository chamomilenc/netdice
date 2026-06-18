import argparse
import csv
import json
import os
import statistics
import time

from netdice.my_logging import log
from netdice.util import get_relative_to_working_directory, project_root_dir


IDICE_REPETITIONS = 10
DETAIL_MODE = "netdice"
DETAIL_COLUMNS = [
    "network_name",
    "mode",
    "property_index",
    "explored_states",
    "imprecision",
]
IDICE_DETAIL_COLUMNS = [
    "detail_states",
    "detail_imprecisions",
]
IDICE_COLUMNS = [
    "network_name",
    "nodes",
    "links",
    "property_count",
    "status",
    "max_time_ms",
    "median_time_ms",
    "avg_time_ms",
    "times_ms",
    "explored_states",
    "p_lows",
    "p_highs",
    "imprecisions",
] + IDICE_DETAIL_COLUMNS


def _format_precision_for_filename(precision: float) -> str:
    text = "{:.15g}".format(precision)
    if "e" not in text and "E" not in text:
        return text

    fixed = "{:.15f}".format(precision).rstrip("0").rstrip(".")
    return fixed if fixed else "0"


def _json_for_csv(value):
    return json.dumps(value, separators=(",", ":"))


def _get_idice_output_file(dataset_label: str, precision: float):
    results_dir = os.path.join(project_root_dir, "results")
    if not os.path.exists(results_dir):
        os.makedirs(results_dir)

    precision_label = _format_precision_for_filename(precision)
    return os.path.join(results_dir, "exp-{}-p{}-orinetdice.csv".format(dataset_label, precision_label))


def _detail_network_name(input_file: str) -> str:
    experiments_dir = os.path.join(project_root_dir, "experiments")
    try:
        relpath = os.path.relpath(input_file, experiments_dir)
        if not relpath.startswith(".."):
            return relpath
    except ValueError:
        pass
    return os.path.basename(input_file)


def _get_detail_output_file(input_file: str, precision: float):
    results_dir = os.path.join(project_root_dir, "results")
    if not os.path.exists(results_dir):
        os.makedirs(results_dir)

    stem = os.path.splitext(os.path.basename(input_file))[0]
    precision_label = _format_precision_for_filename(precision)
    return os.path.join(
        results_dir,
        "detail-{}-p{}-{}-ori.csv".format(stem, precision_label, DETAIL_MODE),
    )


def _empty_idice_row(network_name: str):
    return {
        "network_name": network_name,
        "nodes": 0,
        "links": 0,
        "property_count": 0,
        "status": "OK",
        "max_time_ms": "",
        "median_time_ms": "",
        "avg_time_ms": "",
        "times_ms": _json_for_csv([]),
        "explored_states": _json_for_csv([]),
        "p_lows": _json_for_csv([]),
        "p_highs": _json_for_csv([]),
        "imprecisions": _json_for_csv([]),
        "detail_states": _json_for_csv([]),
        "detail_imprecisions": _json_for_csv([]),
    }


def _resolve_idice_dataset(dataset: str):
    experiments_dir = os.path.join(project_root_dir, "experiments")

    if os.path.isabs(dataset):
        dataset_dir = dataset
    else:
        dataset_dir = os.path.join(experiments_dir, dataset)
        if not os.path.isdir(dataset_dir):
            dataset_dir = get_relative_to_working_directory(dataset)

    dataset_dir = os.path.abspath(dataset_dir)
    if not os.path.isdir(dataset_dir):
        raise ValueError("could not find dataset directory '{}'".format(dataset))

    try:
        dataset_label = os.path.relpath(dataset_dir, experiments_dir)
        if dataset_label.startswith(".."):
            dataset_label = os.path.basename(dataset_dir)
    except ValueError:
        dataset_label = os.path.basename(dataset_dir)

    return dataset_dir, dataset_label.replace(os.sep, "-")


def _find_idice_inputs(dataset_dir: str):
    input_files = []
    for root, _, files in os.walk(dataset_dir):
        for filename in files:
            if filename.endswith(".json"):
                input_files.append(os.path.join(root, filename))
    return sorted(input_files)


def _idice_network_name(input_file: str) -> str:
    experiments_dir = os.path.join(project_root_dir, "experiments")
    try:
        relpath = os.path.relpath(input_file, experiments_dir)
        if relpath.startswith(".."):
            relpath = os.path.relpath(input_file, project_root_dir)
    except ValueError:
        relpath = os.path.relpath(input_file, project_root_dir)
    return relpath


def _resolve_detail_input(input_file: str):
    input_file = os.path.abspath(input_file)
    if not os.path.isfile(input_file):
        raise ValueError("could not find network file '{}'".format(input_file))

    experiments_dir = os.path.join(project_root_dir, "experiments")
    try:
        relpath = os.path.relpath(input_file, experiments_dir)
    except ValueError:
        relpath = None

    if relpath is None or relpath == ".." or relpath.startswith(".." + os.sep):
        raise ValueError("--detail expects a network file under experiments/<dataset>/")

    parts = relpath.split(os.sep)
    if len(parts) < 1:
        raise ValueError("--detail expects a network file under experiments/<dataset>/")

    if len(parts) == 1:
        dataset_label = os.path.splitext(parts[0])[0]
    else:
        dataset_label = parts[0]

    return input_file, relpath, dataset_label


def _load_idice_metadata(input_file: str):
    from netdice.input_parser import InputParser

    parser = InputParser(input_file)
    problems = parser.get_problems()
    if len(problems) == 0:
        return 0, 0, 0
    return problems[0].nof_nodes, problems[0].nof_links, len(problems)


def _run_idice_repetition(input_file: str, precision: float):
    from netdice.explorer import Explorer
    from netdice.input_parser import InputParser

    parser = InputParser(input_file)
    problems = parser.get_problems()

    start = time.perf_counter()
    p_lows = []
    p_highs = []
    imprecisions = []
    explored_states = 0

    for problem in problems:
        problem.target_precision = precision
        explorer = Explorer(problem)
        sol = explorer.explore_all()

        imprecision = sol.p_explored.invert().val()
        p_low = sol.p_property.val()
        p_high = p_low + imprecision

        p_lows.append(p_low)
        p_highs.append(p_high)
        imprecisions.append(imprecision)
        explored_states += sol.num_explored

    elapsed_ms = (time.perf_counter() - start) * 1000
    return {
        "time_ms": elapsed_ms,
        "explored_states": explored_states,
        "p_lows": p_lows,
        "p_highs": p_highs,
        "imprecision": max(imprecisions) if len(imprecisions) > 0 else 0.0,
    }


def _run_idice_experiment(dataset: str, precision: float):
    dataset_dir, dataset_label = _resolve_idice_dataset(dataset)
    input_files = _find_idice_inputs(dataset_dir)
    if len(input_files) == 0:
        raise ValueError("could not find any .json inputs in '{}'".format(dataset_dir))

    output_file = _get_idice_output_file(dataset_label, precision)

    log.info("running iDice-style experiment on %d networks from %s", len(input_files), dataset_dir)
    with open(output_file, "w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=IDICE_COLUMNS)
        writer.writeheader()

        for input_file in input_files:
            network_name = _idice_network_name(input_file)
            row = _empty_idice_row(network_name)

            try:
                nodes, links, property_count = _load_idice_metadata(input_file)
                row["nodes"] = nodes
                row["links"] = links
                row["property_count"] = property_count

                times_ms = []
                explored_states = []
                p_lows = []
                p_highs = []
                imprecisions = []

                for repetition in range(0, IDICE_REPETITIONS):
                    log.info("running %s repetition %d/%d", network_name, repetition + 1, IDICE_REPETITIONS)
                    result = _run_idice_repetition(input_file, precision)
                    times_ms.append(result["time_ms"])
                    explored_states.append(result["explored_states"])
                    p_lows.append(result["p_lows"])
                    p_highs.append(result["p_highs"])
                    imprecisions.append(result["imprecision"])

                row["max_time_ms"] = max(times_ms)
                row["median_time_ms"] = statistics.median(times_ms)
                row["avg_time_ms"] = statistics.mean(times_ms)
                row["times_ms"] = _json_for_csv(times_ms)
                row["explored_states"] = _json_for_csv(explored_states)
                row["p_lows"] = _json_for_csv(p_lows)
                row["p_highs"] = _json_for_csv(p_highs)
                row["imprecisions"] = _json_for_csv(imprecisions)
            except (Exception, SystemExit) as err:
                row["status"] = "ERROR"
                log.error("failed to run %s: %s", network_name, err)

            writer.writerow(row)

    return output_file


def _write_detail_csv(output_file: str, network_name: str, property_traces):
    with open(output_file, "w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=DETAIL_COLUMNS)
        writer.writeheader()
        for property_index, trace_states, trace_imprecisions in property_traces:
            for explored_states, imprecision in zip(trace_states, trace_imprecisions):
                writer.writerow({
                    "network_name": network_name,
                    "mode": DETAIL_MODE,
                    "property_index": property_index,
                    "explored_states": explored_states,
                    "imprecision": imprecision,
                })


def _run_idice_detail(input_file: str, precision: float):
    from netdice.explorer import Explorer
    from netdice.input_parser import InputParser

    input_file, _, _ = _resolve_detail_input(input_file)
    network_name = _detail_network_name(input_file)
    output_file = _get_detail_output_file(input_file, precision)

    parser = InputParser(input_file)
    problems = parser.get_problems()
    property_traces = []

    for property_index, problem in enumerate(problems):
        problem.target_precision = precision
        explorer = Explorer(problem, stat_prec=True)
        sol = explorer.explore_all()
        property_traces.append((
            property_index,
            sol.precision_trace_states,
            sol.precision_trace_imprecisions,
        ))

    _write_detail_csv(output_file, network_name, property_traces)
    return output_file, network_name


def _run_single_input(input_file: str, query_file: str, precision: float):
    from netdice.explorer import Explorer
    from netdice.input_parser import InputParser

    parser = InputParser(input_file, query_file)
    problems = parser.get_problems()
    for problem in problems:
        problem.target_precision = precision
        explorer = Explorer(problem)
        sol = explorer.explore_all()

        log.info("explored states: {}".format(sol.num_explored))
        log.info("precision: {}".format(sol.p_explored.invert().val()))

        p_low = sol.p_property.val()
        p_up = sol.p_property.val() + sol.p_explored.invert().val()

        print("P({}) in [{:8.8f}, {:8.8f}]".format(
            problem.property.get_human_readable(parser.name_resolver), p_low, p_up))


if __name__ == "__main__":
    parser = argparse.ArgumentParser("netdice.app")
    parser.add_argument("input_file", nargs="?", help='file name of input file (.json format)', type=str)
    parser.add_argument('-q', '--query', help='file name of query file (.json format)', type=str)
    parser.add_argument('-p', '--precision', default=1.0E-4, help='target precision of result (default: 1.0E-4)', type=float)
    parser.add_argument('--expIdice', '--exp-idice', dest="exp_idice", action="store_true",
                        help='run all JSON inputs in experiments/<dataset> and emit an iDice-style CSV')
    parser.add_argument('--detail', help='run one experiments/<dataset> network and record precision by explored states')
    parser.add_argument('-d', '-dataset', '--dataset', help='dataset name or directory for --expIdice, e.g. exp1')
    parser.add_argument('--quiet', action="store_true", help='only print results to console, no logs')
    parser.add_argument('--debug', action="store_true", help='print debug log to console')
    args = parser.parse_args()

    if args.debug:
        log.initialize('DEBUG')
    elif args.quiet:
        log.initialize('WARNING')
    else:
        log.initialize('INFO')

    if args.detail:
        if args.exp_idice:
            parser.error("--detail cannot be combined with --expIdice")
        if args.dataset is not None:
            parser.error("--detail derives the dataset from the network path; do not pass -d/--dataset")
        if args.query is not None:
            parser.error("--detail does not support --query")
        if args.input_file is not None:
            parser.error("input_file is not used with --detail")

        try:
            detail_input_file = get_relative_to_working_directory(args.detail)
            output_file, network_name = _run_idice_detail(detail_input_file, args.precision)
        except ValueError as err:
            parser.error(str(err))
        print("wrote {} for {}".format(output_file, network_name))
        raise SystemExit(0)

    if args.exp_idice:
        if args.dataset is None:
            parser.error("--expIdice requires -d/--dataset")
        try:
            output_file = _run_idice_experiment(args.dataset, args.precision)
        except ValueError as err:
            parser.error(str(err))
        print("wrote {}".format(output_file))
        raise SystemExit(0)

    if args.input_file is None:
        parser.error("input_file is required unless --expIdice is specified")

    input_file = get_relative_to_working_directory(args.input_file)
    query_file = None
    if args.query:
        query_file = get_relative_to_working_directory(args.query)

    _run_single_input(input_file, query_file, args.precision)
