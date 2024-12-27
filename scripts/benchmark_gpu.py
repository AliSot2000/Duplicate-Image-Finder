"""
File used to benchmark the Second Loop Worker with a GPU Delta function against the GPU Worker.


It has shown, that the GPU worker is very slow compared to the CPU worker.
"""

import argparse
import datetime
import json
import os

import fast_diff_py as fast_diff
import fast_diff_py.img_processing_gpu as impgp
from fast_diff_py import FastDifPy
from fast_diff_py.config import Progress

# Defaults
number_of_processes = [2, 3, 4]
target_size = 64
retries = 3


def preamble(dir_a: str, size: int, dir_b: str = None) -> fast_diff.FastDifPy:
    """
    Prepare by compressing the images
    """
    if dir_b is None:
        fdo = fast_diff.FastDifPy(purge=True, part_a=dir_a, compression_target=size)
    else:
        fdo = fast_diff.FastDifPy(purge=True, part_a=dir_a, part_b=dir_b, compression_target=size)

    # Index the files
    fdo.full_index()
    fdo.first_loop()
    return fdo


def run_benchmark_gpu(fdo: FastDifPy, use_worker: bool, processes: int) -> float:
    """
    Run the gpu benchmark
    """

    # Remove Table
    fdo.db.debug_execute("DROP TABLE IF EXISTS dif_table")
    fdo.config.state = Progress.FIRST_LOOP_DONE

    # Setting the worker
    if use_worker:
        fdo.gpu_worker_class = impgp.SecondLoopGPUWorker
    else:
        fdo.gpu_worker_class = None

    start = datetime.datetime.now(datetime.UTC)
    fdo.second_loop(fast_diff.SecondLoopConfig(gpu_proc=processes, cpu_proc=0))
    end = datetime.datetime.now(datetime.UTC)
    return (end - start).total_seconds()


def epilogue(fdo: FastDifPy):
    """
    Clean up the Files needed for benchmark.
    """
    fdo.config.retain_progress = False
    fdo.config.delete_db = True
    fdo.config.delete_thumb = True
    fdo.cleanup()


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
    parser.add_argument("-u", "--source_a",
                        help="Source directory in which all images are to be compressed and provided as partition a",
                        type=str, required=True)
    parser.add_argument("-v", "--source_b",
                        help="Source directory in which all images are to be compressed and provided as partition b",
                        required=False)
    parser.add_argument("-t", "--target",
                        help="Target File, where the statistics of the benchmark are stored, "
                             "defaults to {PWD}/benchmark_gpu_stats_YYYY-MM-DD_HH-MM-SS.json",
                        required=False)

    # Set some stuff
    args = parser.parse_args()

    dts = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    if args.target is None:
        target = os.path.join(os.getcwd(),
                              f"benchmark_gpu_stats_{dts}.json")
    else:
        target = args.target

    obj = preamble(dir_a=args.source_a, size=args.size, dir_b=args.source_b)

    stats = {}
    worker = ["SecondLoopGPUWorker", "SecondLoopWorker"]
    # worker = ["SecondLoopGPUWorker"]
    # worker = ["SecondLoopWorker"]

    # Using not pretty but functional strategy
    for w in worker:
        stats[w] = {}
        for p in args.processes:
            stats[w][p] = []
            for r in range(args.attempts):
                slgpuw = w == "SecondLoopGPUWorker"
                print(f"Performing {p} processes attempt {r+1}/{args.attempts} with {w}")
                tt = run_benchmark_gpu(fdo=obj, use_worker=slgpuw, processes=p)

                stats[w][p].append(tt)

                # Writing progress to file
                with open(target, "w") as f:
                    json.dump(stats, f)

    epilogue(obj)
