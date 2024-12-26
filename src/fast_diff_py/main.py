import logging
import os
import shutil

import fast_diff_py.config as cfg
from fast_diff_py.fast_dif import FastDifPy
import argparse


def recover(path: str):
    """
    Recover computation from a given config or a given directory.

    :param path: Path to config or directory.
    """
    if os.path.isdir(path):
        local_fdo = FastDifPy(part_a=path)
    else:
        local_fdo = FastDifPy(part_a=os.path.dirname(path))

    execute(local_fdo)

def execute(_fdo: FastDifPy):
    """
    Run FastDiffPy and finally copy the database to the output path
    """
    # Keep progress, we're not done
    _fdo.config.retain_progress = True
    _fdo.config.delete_db = False
    _fdo.config.delete_thumb = False

    # Run the index
    if _fdo.config.state == cfg.Progress.INIT:
        if _fdo.db.dir_table_exists():
            _fdo.db.drop_directory_table()

        _fdo.full_index()

    # Exit in sigint
    if not _fdo.run:
        _fdo.commit()
        _fdo.cleanup()
        return

    # Run the first loop
    if _fdo.config.state in (cfg.Progress.INDEXED_DIRS, cfg.Progress.FIRST_LOOP_IN_PROGRESS):
        _fdo.first_loop()

    # Exit on sigint
    if not _fdo.run:
        print("First Loop Exited")
        _fdo.commit()
        _fdo.cleanup()
        return

    # Run the second loop
    if _fdo.config.state in (cfg.Progress.SECOND_LOOP_IN_PROGRESS, cfg.Progress.FIRST_LOOP_DONE):
        _fdo.second_loop()

    if not _fdo.run:
        _fdo.commit()
        _fdo.cleanup()
        return

    # We're done, clean up
    _fdo.commit()

    # Getting possible output dir from config
    cli_args = _fdo.config.cli_args if _fdo.config.cli_args is not None else {}
    output = cli_args.get("output_dir")

    if output is not None:
        if os.path.isdir(output):
            tgt = os.path.join(output, "fast_diff_py.db")
            print(f"Moving Finished Database to {tgt}")
            shutil.copy(_fdo.config.db_path, tgt)
        else:
            print(f"Moving Finished Database to {output}")
            shutil.copy(_fdo.config.db_path, output)
    else:
        print(f"Renaming Database in work dir to fast_diff_py.db")
        name = "fast_diff_py.db"
        shutil.copy(_fdo.config.db_path, os.path.join(os.path.dirname(_fdo.config.db_path), name))

    _fdo.config.retain_progress = False
    _fdo.config.delete_db = True
    _fdo.config.delete_thumb = True

    _fdo.commit()
    _fdo.cleanup()


def main():
    """
    Everything necessary in the main function to be exposed in the package
    """
    parser = argparse.ArgumentParser(description='''
        Find Duplicates and output a DB for the User - https://github.com/AliSot2000/Fast-Image-Deduplicator.''')

    # General Arguments
    parser.add_argument("-R", "--recover", type=str, required=False,
                        help="Provide either a directory or the path to a config file from which to recover. "
                             "(Can be achieved implicitly by providing -a /path/to/dir, not providing -p and "
                             "subsequently confirming the continuation of the progress.")

    parser.add_argument("-a", "--part_a", type=str, required=True, nargs="+",
                        help="Provide a list of directories which form partition a")
    parser.add_argument("-b", "--part_b", type=str, required=False, nargs="*",
                        help="Provide a list of directories which form partition b. If empty, "
                             "deduplicate within partition a")
    parser.add_argument("-r", "--no_recursive", action="store_false",
                        help="Disable recursive search in the directories provided in partition a and partition b")
    parser.add_argument("-c", "--compression_target", type=int, required=False,
                        help="Size target to which the images should be compressed. Default from Config")
    parser.add_argument("-p", "--purge", action="store_true",
                        help="Delete any existing progress should it exist in the first directory of partition a")
    parser.add_argument("-C", "--cpu_proc", type=int, required=False,
                        help="Number of CPU cores to use. Default number of CPU cores available.")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable Logging at Debug Level")

    # Arguments for the first loop
    parser.add_argument("-H", "--hash", action="store_true",
                        help="Compute Hashes in First Loop")
    parser.add_argument("-S", "--shift_amount", required=False, type=int,
                        help="Shift amount by which bytes of the images should be shifted. Default from Config")
    parser.add_argument("-f", "--no_compress", action="store_true",
                        help="Disable the storing of the compressed images in the first loop.")

    # Arguments for second loop
    parser.add_argument("-d", "--no_second_loop", action="store_true",
                        help="Disable the execution of the second loop. (All to all image comparison)")
    parser.add_argument("-m", "--skip_matching_hash", action="store_true",
                        help="Images with matching hashes are deemed duplicates. Requires -H / --hash")
    parser.add_argument("-M", "--match_aspect", type=float, required=False,
                        help=f"Either match size of image (set to 0) or match aspect ratio of images within a degree")
    parser.add_argument("-T", "--threshold", type=float, required=False,
                        help="Threshold below which images are considered duplicates. Default 200.0")
    parser.add_argument("-l", "--cache_preload", type=int, required=False,
                        help="Number of Caches in RAM at any point in time.")

    # Process arguments
    parser.add_argument("-t", "--temp_dir", type=str, required=False,
                        help="Temp directory where progress, db and thumbnails are stored.")

    parser.add_argument("-o", "--output_dir", type=str, required=False,
                        help="Output directory where db moved to once the process is done..")

    args = parser.parse_args()

    # Short circuit if we get a recover argument
    if args.recover:
        recover(args.recover)
        exit(0)

    # Verifying progress first
    if args.temp_dir is not None:
        cfgp = os.path.join(args.temp_dir, FastDifPy.default_config_file)
        db = os.path.join(args.temp_dir, FastDifPy.default_db_file)
    else:
        cfgp = os.path.join(args.part_a[0], FastDifPy.default_config_file)
        db = os.path.join(args.part_a[0], FastDifPy.default_db_file)

    dbe = os.path.exists(db)
    cfge = os.path.exists(cfgp)

    if dbe or cfge:
        print("Progress from a previous attempt exists")
        if cfge:
            print(f"A Config File was found at {cfgp}")
        if dbe:
            print(f"A Database was found at {db}")

        if input("Do you want to override the existing progress? [y/n] ").lower() == "y":
            args.purge = True
        else:
            recover(args.temp_dir if args.temp_dir is not None else args.part_a[0])
            exit(0)

    # Validating args
    if args.skip_matching_hash and not args.hash:
        raise ValueError("--skip_matching_hash requires --hash")

    if args.cpu_proc is not None and args.cpu_proc < 1:
        raise ValueError("Number of CPUs needs to be used must be >= 1")

    if args.no_compress and not args.no_second_loop:
        raise ValueError("second loop requires compressed images. add --no_second_loop or remove --no_compress")

    # Make directory if not exists
    if args.temp_dir is not None and not os.path.exists(args.temp_dir):
        os.makedirs(args.temp_dir)

    fdo = FastDifPy(part_a=args.part_a, part_b=args.part_b, purge=args.purge, workdir=args.temp_dir)

    # Setting the arguments
    if args.verbose:
        fdo.handler.setLevel(logging.DEBUG)

    # Setting the recursive
    fdo.config.recurse = not args.no_recursive

    # Setting the compression target
    if args.compression_target is not None:
        if args.compression_target < 16 or args.compression_target > 4096:
            raise ValueError("Compression target must be between 16 and 4096")

        fdo.config.compression_target = args.compression_target

    # Setting cpu processes
    if args.cpu_proc is not None:
        fdo.config.first_loop.cpu_proc = args.cpu_proc
        fdo.config.second_loop.cpu_proc = args.cpu_proc

    # Setting the first loop config
    fdo.config.first_loop.compute_hash = args.hash
    if args.shift_amount is not None:
        fdo.config.first_loop.shift_amount = args.shift_amount
    fdo.config.first_loop.compress = not args.no_compress

    # Setting second loop arguments
    if args.no_second_loop:
        fdo.config.do_second_loop = False

    # Set the hash
    fdo.config.second_loop.skip_matching_hash = args.skip_matching_hash

    # Setting aspect match aspect ratio
    if args.match_aspect is not None:
        fdo.config.second_loop.match_aspect_by = args.match_aspect

    # Setting threshold
    if args.threshold is not None:
        if args.threshold < 0:
            raise ValueError("Threshold must be >= 0")

        fdo.config.second_loop.diff_threshold = args.threshold

    # Set the preload count
    if args.cache_preload is not None:
        if args.cache_preload < 1:
            raise ValueError("Caches preload must be > 1")

        fdo.config.second_loop.preload_count = args.cache_preload

    fdo.config.cli_args = args.__dict__

    execute(fdo)


if __name__ == "__main__":
    main()