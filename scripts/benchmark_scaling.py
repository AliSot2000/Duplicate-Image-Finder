"""
This Benchmark looks at the performance of the dif.py command file. Due to the enormous size, we're not considering
less than full cpu usage.
"""
import argparse
import json
import os
import datetime
import shutil
import subprocess


number_of_processes = [16]
target_size = 64
retries = 3

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Benchmark for Duplicate Image Finder Implementations FastDiffPy and DifPy;'
                    ' run deduplication benchmark')

    parser.add_argument("-p", "--processes",
                        help="List of process numbers to use",
                        nargs="+", type=int, default=number_of_processes, required=False)
    parser.add_argument("-s", "--size",
                        help="Size of image to use", type=int, default=target_size)
    parser.add_argument("-a", "--attempts",
                        help="Number of times to attempt to do for each number of process",
                        type=int, default=retries)
    parser.add_argument("-u", "--partition_a", help="Directory to be used for partition_a",
                        nargs="+", type=str, required=True)
    parser.add_argument("-t", "--target",
                        help="Target File, where the statistics of the benchmark are stored, "
                             "defaults to {PWD}/benchmark_all_to_all_stats_YYYY-MM-DD_HH-MM-SS.json",
                        required=False)

    # optional
    parser.add_argument("-v", "--partition_b",type=str, required=False,
                        help="Directory to be used for partition_b, can be left empty",
                        nargs="+")
    parser.add_argument("-r", "--rotate",
                        help="Disable rotation of the image",
                        action="store_false")
    parser.add_argument("-l", "--lazy",
                        help="Enable lazy mode",
                        action="store_true")
    parser.add_argument("-d", "--delta", type=float,
                        help="Delta between images to be achieved for them to be considered duplicated", default=200.0)

    parser.add_argument("-f", "--fast_diff_py", type=str, required=False,
                        help="Path to fast-diff-py executable")
    parser.add_argument("-e", "--diff_py", type=str, required=False,
                        help="Path to diff-py executable")

    args = parser.parse_args()

    python = shutil.which("python3")
    source_dir = os.path.abspath(os.path.join(__file__, "..", "..", "src"))

    # Getting target file
    if args.fast_diff_py is not None:
        fast_diff_file = args.fast_diff_py
    else:
        fast_diff_file = os.path.join(source_dir, "fast_diff_py", "dif.py")

    # Getting target file
    if args.diff_py is not None:
        dif_py_file = args.dif_py_file
    else:
        dif_py_file = os.path.abspath(
            os.path.join(__file__, "..", "..", "lin_venv", "lib", "python3.12", "site-packages", "difPy", "dif.py"))

    if not len(args.partition_a) == len(args.partition_b):
        raise ValueError("Number of partitions must match")

    if not 10 < args.size < 5000:
        raise ValueError("Size must be between 1 and 5000")

    if args.attempts < 1:
        raise ValueError("Attempts must be greater than 0")

    if args.delta < 0:
        raise ValueError("Delta must be greater than 0")

    # Setting stats file
    dts = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    if args.target is None:
        target = os.path.join(os.getcwd(),
                              f"benchmark_all_stats_{dts}.json")
    else:
        target = args.target

    stats = {
        "difpy": {},
        "fast_diff_py": {}
    }

    # Go through all partitions
    for i in range(len(args.partition_a)):
        stats["difpy"][args.partition_a[i]] = {}
        stats["fast_diff_py"][args.partition_a[i]] = {}
        for process in args.processes:
            stats["difpy"][args.partition_a[i]][process] = []
            stats["fast_diff_py"][args.partition_a[i]][process] = []
            for attempt in range(args.attempts):

                cmd_a = [python, dif_py_file]
                cmd_b = [python, fast_diff_file]

                # Setting directories
                if args.partition_b is not None and  len(args.partition_b) > 0:
                    difpy_str = (f"Running difpy on {args.partition_b[i]} and {args.partition_a[i]}, "
                                 f"attempt {attempt+1} of {args.attempts} with {process} processes")
                    fast_diff_py_str = (f"Running fastdiffpy on {args.partition_b[i]} and {args.partition_a[i]}, "
                                 f"attempt {attempt+1} of {args.attempts} with {process} processes")
                    cmd_a.extend(["-D", args.partition_b[i], args.partition_a[i]])
                    cmd_b.extend(["-D", args.partition_b[i], args.partition_a[i]])

                else:
                    difpy_str = (f"Running difpy on {args.partition_b[i]}, "
                                 f"attempt {attempt+1} of {args.attempts} with {process} processes")
                    fast_diff_py_str = (f"Running fastdiffpy on {args.partition_b[i]}, "
                                 f"attempt {attempt+1} of {args.attempts} with {process} processes")
                    cmd_a.extend(["-D", args.partition_a[i]])
                    cmd_b.extend(["-D", args.partition_a[i]])

                # Adding size
                cmd_a.extend(["-s", str(args.size / 3)])
                cmd_b.extend(["-s", str(args.size)])

                # Adding lazy
                cmd_a.extend(["-la", str(args.lazy)])
                cmd_b.extend(["-la", str(args.lazy)])

                # Setting rotation
                cmd_a.extend(["-ro", str(args.rotate)])
                cmd_b.extend(["-ro", str(args.rotate)])

                # Adding storage directory
                cmd_a.extend(["-Z", os.path.dirname(target)])
                cmd_b.extend(["-Z", os.path.dirname(target)])

                print(difpy_str)
                start = datetime.datetime.now(datetime.UTC)
                proc = subprocess.Popen(
                    cmd_a,
                    env={"PYTHONPATH": source_dir},
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, universal_newlines=True)

                # Read the output
                for line in iter(proc.stdout.readline, ""):
                    print(f"{line.strip()}")

                # Read the stderr
                for line in iter(proc.stderr.readline, ""):
                    print(f"{line.strip()}")

                return_code = proc.poll()
                if return_code is not None:
                    print(f'RETURN CODE', return_code)
                end = datetime.datetime.now(datetime.UTC)

                stats["difpy"][args.partition_a[i]][process].append((end-start).total_seconds())

                print(fast_diff_py_str)
                start = datetime.datetime.now(datetime.UTC)
                proc = subprocess.Popen(
                    cmd_b,
                    env={"PYTHONPATH": source_dir},
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, universal_newlines=True
                )

                # Read the output
                for line in iter(proc.stdout.readline, ""):
                    print(f"{line.strip()}")

                # Read the stderr
                for line in iter(proc.stderr.readline, ""):
                    print(f"{line.strip()}")

                return_code = proc.poll()
                if return_code is not None:
                    print(f'RETURN CODE', return_code)

                end = datetime.datetime.now(datetime.UTC)

                stats["fast_diff_py"][args.partition_a[i]][process].append((end-start).total_seconds())

                with open(target, "w") as tgt:
                    json.dump(stats, tgt)