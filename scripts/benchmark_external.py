import argparse
import datetime
import os
import pickle

import difPy.dif as difpy

import fast_diff_py as fast_diff
from fast_diff_py import FastDifPy


"""
There's an issue with difpy. When exiting from the search step, it somehow triggers a sigint, leading to the process
running the benchmark to exit while some workers from the pool remain. 

For this purpose, the functino of the benchmark is moved into this file which can be started with subprocess.Popen
"""
def fast_diff_benchmark(dir: str, rotate: bool, lazy: bool, processes: int, similarity: float) -> float:
    """
    Perform the benchmark with fast_diff_py
    """
    fdo = FastDifPy(default_cfg_path=os.path.join(dir, FastDifPy.default_config_file))
    fdo.config.state = fast_diff.config.Progress.FIRST_LOOP_DONE
    fdo.db.debug_execute("DROP TABLE IF EXISTS dif_table")

    # Clearing the old second loop config
    fdo.config.second_loop = fast_diff.SecondLoopConfig()
    fdo.config.rotate = rotate
    fdo.config.second_loop.cpu_proc = processes
    fdo.config.second_loop.diff_threshold = similarity

    if lazy:
        fdo.config.second_loop.match_aspect_by = 0
        fdo.config.second_loop.skip_matching_hash = True
    else:
        fdo.config.second_loop.match_aspect_by = None
        fdo.config.second_loop.skip_matching_hash = False

    start = datetime.datetime.now(datetime.UTC)
    fdo.second_loop()

    fdo.config.retain_progress = True
    fdo.config.delete_db = False
    fdo.config.delete_thumb = False

    fdo.cleanup()
    end = datetime.datetime.now(datetime.UTC)
    return (end - start).total_seconds()


def difpy_benchmark(file: str, rotate: bool, lazy: bool, processes: int, similarity: float) -> float:
    """
    Difpy benchmark. Perform the search step. once completed, return the number of seconds taken
    """
    with open(file, "rb") as f:
        dif = pickle.load(f)


    start = datetime.datetime.now(datetime.timezone.utc)
    difpy.search(dif, similarity=similarity / 3, rotate=rotate, lazy=lazy, processes=processes)
    end = datetime.datetime.now(datetime.timezone.utc)
    return (end - start).total_seconds()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Benchmark for Duplicate Image Finder Implementations FastDiffPy and DifPy;'
                    ' run deduplication benchmark')

    parser.add_argument("-r", "--rotate", action="store_false",
                        help="Disable rotation of images")
    parser.add_argument("-l", "--lazy", action="store_true",
                        help="Enable lazy search")
    parser.add_argument("-p", "--processes", type=int, required=True,
                        help="Number of processes to use")
    parser.add_argument("-s", "--similarity", type=float, required=True,
                        help="Similarity threshold for DifPy")
    parser.add_argument("-f", "--file", type=str,
                        help="Difpy checkpoint file")
    parser.add_argument("-d", "--dir", type=str, help="FastDiffPy checkpoint directory" )
    parser.add_argument("mode", type=str, help="Benchmark either dipy or fastdiffpy",
                        choices=["DIFPY", "FAST_DIFF_PY"])

    args = parser.parse_args()

    if args.mode == "DIFPY" and args.file is None:
        raise ValueError("Difpy checkpoint file must be specified")

    if args.mode == "FAST_DIFF_PY" and args.dir is None:
        raise ValueError("Difpy checkpoint directory must be specified")

    if args.mode == "DIFPY":
        difpy_benchmark(file=args.file,
                        rotate=args.rotate,
                        lazy=args.lazy,
                        processes=args.processes,
                        similarity=args.similarity)

    elif args.mode == "FAST_DIFF_PY":
        fast_diff_benchmark(dir=args.dir,
                            rotate=args.rotate,
                            lazy=args.lazy,
                            processes=args.processes,
                            similarity=args.similarity)

    else:
        raise ValueError(f"Unknown mode: {args.mode}")

    print("benchmark finished")
