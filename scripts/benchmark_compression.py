import difPy.dif as difpy
import fast_diff_py as fast_diff
import datetime
import json
import argparse
import os

"""
This file is used to benchmark the speed of compression of the two implementations.

For difpy, we're performing the action of the "build" class. For FastDiffPy, we're performing the action of first loop
"""
# Defaults
# Different assignments for cpu count
number_of_processes = [1, 2, 4, 8, 16]


# How many times we're performing each experiment for variance statistic
retries = 3


# Scaling target
target_size = 64


def difpy_benchmark(directory: str, size: int, processes: int) -> float:
    """
    Performs the difpy build and returns the time taken.
    """
    start = datetime.datetime.now(datetime.UTC)
    difpy.build(directory, px_size=size, processes=processes)
    end = datetime.datetime.now(datetime.UTC)
    return (end - start).total_seconds()


def fast_diff_benchmark(directory: str, size: int, processes: int, do_hash: bool) -> float:
    """
    Performs the fast_diff index and first loop and returns the time taken.
    """
    start = datetime.datetime.now(datetime.UTC)
    fdo = fast_diff.FastDifPy(part_a=directory, purge=True, compression_target=size)
    fdo.full_index()
    flc = fdo.config.first_loop.model_dump()
    flc["compute_hash"] = do_hash
    flc["cpu_proc"] = processes
    fdo.first_loop(fast_diff.FirstLoopRuntimeConfig.model_validate(flc))
    fdo.config.retain_progress = False
    fdo.config.delete_db = True
    fdo.config.delete_thumb = True
    fdo.cleanup()
    end = datetime.datetime.now(datetime.UTC)
    return (end - start).total_seconds()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Benchmark for Duplicate Image Finder Implementations FastDiffPy and DifPy')

    parser.add_argument("-p", "--processes",
                        help="List of process numbers to use",
                        nargs="+", type=int, default=number_of_processes, required=False)
    parser.add_argument("-s", "--size",
                        help="Size of image to use", type=int, default=target_size)
    parser.add_argument("-a", "--attempts",
                        help="Number of times to attempt to do for each number of process",
                        type=int, default=retries)
    parser.add_argument("-d", "--do_hash",
                        help="Also check performance impact of computing hash in FastDiffPy",
                        action="store_true")
    parser.add_argument("-w", "--source", help="Source directory in which all images are to be compressed",
                        type=str, required=True)
    parser.add_argument("-t", "--target",
                        help="Target File, where the statistics of the benchmark are stored, "
                             "defaults to {PWD}/benchmark_compression_stats_YYYY-MM-DD_HH-MM-SS.json",
                        required=False)

    # Set some stuff 
    args = parser.parse_args()

    if not 10 < args.size < 5000:
        raise ValueError("Size must be between 1 and 5000")

    if not args.attempts < 1:
        raise ValueError("Attempts must be greater than 0")

    # Setting stats file
    dts = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    if args.target is None:
        target = os.path.join(os.getcwd(),
                              f"benchmark_compression_stats_{dts}.json")
    else:
        target = args.target

    stats = {}
    tp = ["difpy", "fast_diff"]
    if args.do_hash:
        tp.append("fast_diff_hash")
    for t in tp:
        # Need to init dict. Not nice but works
        stats[t] = {}

        for process in args.processes:

            # init dict again, not nice but works
            stats[t][process] = []
            for rt in range(args.attempts):
                print(f"Performing {process} on {rt+1}/{args.attempts} with {t}")

                time = 0
                if t == "difpy":
                    time = difpy_benchmark(directory=args.source, size=args.size, processes=process)
                elif t == "fast_diff":
                    time = fast_diff_benchmark(directory=args.source,
                                               size=args.size,
                                               processes=process,
                                               do_hash=False)
                elif t == "fast_diff_hash":
                    time = fast_diff_benchmark(directory=args.source,
                                               size=args.size,
                                               processes=process,
                                               do_hash=True)
                else:
                    raise ValueError(f"Unknown benchmark type: {tp}")

                stats[t][process].append(time)

                # Writing progress to file
                with open(target, "w") as f:
                    json.dump(stats, f)
