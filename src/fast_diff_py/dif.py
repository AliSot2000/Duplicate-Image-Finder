import argparse
import json
import logging
import os
import warnings
from datetime import datetime
from typing import List, Tuple, Optional, Union, Dict

import fast_diff_py
import fast_diff_py.config as cfg
from fast_diff_py.fast_dif import FastDifPy

"""
This file contains a drop in replacement for the dif.py file from https://github.com/elisemercury/Duplicate-Image-Finder

Currently the code is made to imitate v4.1.3.
"""

def recover(dir_a: str) -> Optional[FastDifPy]:
    """
    Recover progress from a given directory.

    Run the computation and return the finished object
    """
    fdo = FastDifPy(part_a=dir_a)

    return compute(fdo)


def dif(_part_a: List[str],
        _part_b: List[str],
        cli_args: Dict,
        recursive: bool,
        limit_ext: bool,
        px_size: int,
        _similarity: float,
        rotate: bool,
        lazy: bool,
        chunk: int = None,
        processes: int = None,
        debug: bool = False,
        tgt_dir: str = None
        ) -> Optional[FastDifPy]:
    """
    Set up a new object of FastDifPy and run the computation and return the finished object

    :param cli_args: Dict of Cli Arguments needed for process recovery.
    :param _part_a: The first partition of directories to compare
    :param _part_b: The second partition of directories to compare
    :param recursive: Recursively search within the partitions provided
    :param limit_ext: Limit the size of the files to compare
    :param px_size: The size to which to scale all images
    :param _similarity: The similarity metric to use
    :param rotate: Rotate the image during comparisons
    :param lazy: Lazy comparison (compute hashes, skip if hash matches or images don't have same size)
    :param chunk: batching size for second loop. Used as an override.
    :param processes: Number of processes to use. Used as an override.
    :param debug: log at debug level
    :param tgt_dir: Override for the config, db and thumb paths.

    :return: FastDifPy object
    """
    if tgt_dir is not None:
        fdo = FastDifPy(part_a=_part_a,
                        part_b=_part_b,
                        purge=True,
                        cli_args=cli_args,
                        thumb_dir=os.path.join(tgt_dir, FastDifPy.default_thumb_dir),
                        db_path=os.path.join(tgt_dir, FastDifPy.default_db_file),
                        config_path=os.path.join(tgt_dir, FastDifPy.default_config_file))
    else:
        fdo = FastDifPy(part_a=_part_a,
                        part_b=_part_b,
                        purge=True,
                        cli_args=cli_args)



    if debug:
        fdo.config.log_level = logging.DEBUG
        fdo.config.log_level_children = logging.DEBUG

    # Setting recurse
    fdo.config.recurse = recursive

    # Setting the target size
    fdo.config.compression_target = px_size

    # Setting similarity
    fdo.config.second_loop.diff_threshold = _similarity

    # Setting rotation
    fdo.config.rotate = rotate

    # Setting the process count if it is provided
    if processes is not None:
        fdo.config.first_loop.cpu_proc = processes
        fdo.config.second_loop.cpu_proc = processes

    # Setting the chunk size for the second loop
    if chunk is not None:
        fdo.config.second_loop.batch_size = chunk

    # Setting all acceleration options.
    if lazy:
        fdo.config.first_loop.compute_hash = True
        fdo.config.first_loop.shift_amount = 0
        fdo.config.second_loop.match_aspect_by = 0
        fdo.config.second_loop.skip_matching_hash = True

    # Finally running the computation on the object.
    return compute(fdo, limit_ext=limit_ext)


def compute(fdo: FastDifPy, limit_ext: bool = False) -> Optional[FastDifPy]:
    """
    Perform the main computation (index, compress and compare)

    :returns: the object after the computation is done.
    """
    # Keep progress, we're not done
    fdo.config.retain_progress = True
    fdo.config.delete_db = False
    fdo.config.delete_thumb = False

    # We're already done, return immediately
    if fdo.config.state == cfg.Progress.SECOND_LOOP_DONE:
        return fdo

    # Run the index
    if fdo.config.state == cfg.Progress.INIT:
        fdo.purge_preexisting_directory_table()

        fdo.full_index()

    # Not limit_ext. Changing in DB all files to be allowed.
    # INFO: Allowing myself to have one piece of spaghetti code.
    if not limit_ext:
        fdo.db.debug_execute("UPDATE directory SET allowed = 1 WHERE allowed = 0")

    # Exit in sigint
    if not fdo.run:
        fdo.commit()
        fdo.cleanup()
        return None

    # Run the first loop
    if fdo.config.state in (cfg.Progress.INDEXED_DIRS, cfg.Progress.FIRST_LOOP_IN_PROGRESS):
        fdo.first_loop()

    # Exit on sigint
    if not fdo.run:
        print("First Loop Exited")
        fdo.commit()
        fdo.cleanup()
        return None

    # Run the second loop
    if fdo.config.state in (cfg.Progress.SECOND_LOOP_IN_PROGRESS, cfg.Progress.FIRST_LOOP_DONE):
        fdo.second_loop()

    if not fdo.run:
        fdo.commit()
        fdo.cleanup()
        return None

    return fdo


# ======================================================================================================================
# Util functions needed to convert from difpy to fast_diff_py
# ======================================================================================================================


def construct_stats(fdo: fast_diff_py.FastDifPy) -> Dict:
    """
    Construct the stats.json dictionary from the given FastDifPy object

    :param fdo: FastDifPy object for which to construct the stats.
    """
    c = fdo.config
    db = fdo.db
    file_count = (db.get_partition_entry_count(part_b=True, only_allowed=True)
                  + db.get_partition_entry_count(part_b=True, only_allowed=True))

    files_total = (db.get_partition_entry_count(part_b=True, only_allowed=False)
                  + db.get_partition_entry_count(part_b=True, only_allowed=False))

    dups = db.get_cluster_count(delta=0,
                                      include_hash_match=True,
                                      part_a=not c.partition_swapped)
    dup_and_sim = db.get_cluster_count(delta=c.second_loop.diff_threshold,
                                       include_hash_match=True,
                                       part_a=not c.partition_swapped)
    similar = dup_and_sim - dups

    file_errors = [f"{res[0]}: {res[1]}" for res in db.get_directory_errors()]
    file_errors.extend([f"{res}: Not Allowed" for res in db.get_directory_disallowed()])
    error_count = len(file_errors)

    for pa, pb, error in db.get_dif_errors():
        if pb is None:
            file_errors.append(f"Error Loading Thumbnail of {pa}: {error}")
        else:
            file_errors.append(f"Error Processing Tuple {pa}, {pb}: {error}")

    return {
        "directory": c.part_b + c.part_a if c.partition_swapped else c.part_a + c.part_b,
        "process": {
            "build": {
                "duration": {
                    "start": None,
                    "end": None,
                    "seconds_elapsed": c.dir_index_elapsed + c.first_loop.elapsed_seconds
                },
                "parameters": {
                    "recursive": c.recurse,
                    "in_folder": len(c.part_b) == 0, # INFO: If we have in_folder, there will be no part be, so no swap
                    "limit_extensions": c.cli_args["limit_extensions"],
                    "px_size": c.compression_target,
                    "processes": c.cli_args["processes"] if c.cli_args["processes"] is not None else os.cpu_count()
                }
            },
            "search": {
                "duration": {
                    "start": None,
                    "end": None,
                    "seconds_elapsed": c.second_loop.elapsed_seconds
                },
                "parameters": {
                    "similarity_mse": c.second_loop.diff_threshold,
                    "rotate": c.rotate,
                    "lazy": c.cli_args["lazy"],
                    "processes": c.cli_args["processes"] if c.cli_args["processes"] is not None else os.cpu_count(),
                    "chunksize": c.cli_args["chunksize"]
                },
                "files_searched": file_count,
                "matches_found":{
                    "duplicates": dups,
                    "similar": similar,
                }
            }
        },
        "total_files": files_total,
        "invalid_files": {
            "count": error_count,
            "logs": file_errors
        }
    }


def move_duplicates(filepaths: List[str], target: str) -> int:
    """
    Moves the duplicates into a specified folder.

    :param filepaths: List of duplicate folders to move
    :param target: Target folder (will be created if not exists)

    :return: Number of moved files
    """
    tgt = os.path.abspath(target)
    if not os.path.exists(tgt):
        os.makedirs(tgt)

    count = 0

    # Moving the files
    for f in filepaths:
        if os.path.exists(os.path.abspath(f)):
            os.rename(os.path.abspath(f), os.path.join(tgt, os.path.basename(f)))
            count += 1

    return count

def delete_files(filepaths: List[str], silent: bool) -> int:
    """
    Delete all files which were deemed duplicates

    :parma duplicates: List of duplicate files to delete
    :param silent: Silent mode
    """
    count = 0
    if silent or input("Are you sure you want to delete all lower quality matched images? \n"
                       "This cannot be undone! (y/n)").lower() == "y":
        # Removing all files
        for f in filepaths:
            if os.path.exists(os.path.abspath(f)):
                os.remove(f)
                count += 1

    return count

def str_to_bool(arg: str) -> bool:
    """
    Convert a string from the commandline arguments to bool.
    The conversion is case-insensitive.

    Values converted to True are: y, yes, on, 1, true, t
    """
    val = arg.lower()
    if val in ("y", "yes", "on", "1", "true", "t"):
        return True

    return False


def parse_dirs(dirs: List[str], union: bool) -> Tuple[List[str], List[str]]:
    """
    Parse the commandline input into something that can be used by fast_diff_py.

    :param dirs: The list of directories to parse. Can be empty.
    :param union: If true, return a union of dirs.

    :returns: partition_a and partition_b for fast_diff_py
    """

    if len(dirs) == 0:
        # Nothing was provided, so we're taking cwd and search only in the dir
        return [os.path.basename(__file__)], []

    # If we're unioning, return everything to be put inside the partition a
    # (if only part a is present, search in union is performed)
    # Also, if we have exactly one dir, also perform search within that dir
    if union or len(dirs) == 1:
        return dirs, []

    # Partition a is the last directory provided, all other directories are unioned and then compared against the last.
    # This was the deduced semantic from analyzing dif.py
    return [dirs[-1]], dirs[:-1]


def parse_similarity(sim: Union[str, int]) -> float:
    """
    Convert commandline argument for similarity to a float.

    Allows for duplicates and similar as arguments to be converted to int
    Otherwise it returns the value caste to float

    Since fast_diff_py is using a different mse function than dif.py it must be multiplied by 3
    """
    if sim not in ['duplicates', 'similar']:
        try:
            sim = float(sim)
            if sim < 0:
              raise Exception('Invalid value for "similarity" parameter: must be >= 0.')
            else:
                return sim * 3
        except:
            raise Exception('Invalid value for "similarity" parameter: must be "duplicates", "similar" '
                            'or of type INT or FLOAT.')
    else:
        if sim == 'duplicates':
            # search for duplicate images
            sim = 0 * 3
        elif sim == 'similar':
            # search for similar images
            sim = 5 * 3
        return sim


def main():
    """
    Everything necessary in the main function to be exposed in the package
    """
    # Parameters for when launching difPy via CLI
    parser = argparse.ArgumentParser(description='''
        Find duplicate or similar images with fast_diff_py - https://github.com/AliSot2000/Fast-Image-Deduplicator
        ''')
    parser.add_argument('-D', '--directory',
                        type=str,
                        nargs='+',
                        help='Paths of the directories to be searched. Default is working dir. If you provide multiple '
                             'directories with -D and you do not perform a union search with -i, the first n-1 '
                             'directories are unioned into one partition and subsequently checked against the n-th '
                             'directory for duplicates.',
                        required=False, default=[os.getcwd()])
    parser.add_argument('-r', '--recursive',
                        type=lambda x: str_to_bool(x),
                        help='Search recursively within the directories.',
                        required=False, choices=[True, False], default=True)
    parser.add_argument('-i', '--in_folder',
                        type=lambda x: str_to_bool(x),
                        help='Search for matches in the union of directories.',
                        required=False, choices=[True, False], default=False)
    parser.add_argument('-le', '--limit_extensions',
                        type=lambda x: str_to_bool(x), help='Limit search to known image file extensions.',
                        required=False, choices=[True, False], default=True)
    parser.add_argument('-px', '--px_size',
                        type=int,
                        help='Compression size of images in pixels.',
                        required=False, default=50)
    parser.add_argument('-s', '--similarity',
                        type=lambda x: parse_similarity(x),
                        help='Similarity grade (mse).',
                        required=False, default='duplicates')
    parser.add_argument('-ro', '--rotate',
                        type=lambda x: str_to_bool(x),
                        help='Rotate images during comparison process.',
                        required=False, choices=[True, False], default=True)
    parser.add_argument('-la', '--lazy',
                        type=lambda x: str_to_bool(x),
                        help="Compute hash of each image. If hashes match, images are considered a match with delta=0"
                             "Additionally, if images don't have the same pixel size, they aren't considered as "
                             "possible candidates",
                        required=False, choices=[True, False], default=True)
    parser.add_argument('-proc', '--processes',
                        type=int,
                        help='Number of worker processes for multiprocessing.',
                        required=False, default=None)
    parser.add_argument('-ch', '--chunksize',
                        type=int,
                        help='Only relevant when dataset > 5k images. Sets the batch size at which the job is '
                             'simultaneously processed when multiprocessing.',
                        required=False, default=None)

    # Args not for the dif method
    parser.add_argument('-Z', '--output_directory',
                        type=str,
                        help='Output directory path for the difPy result files. Default is working dir.',
                        required=False, default=None)
    parser.add_argument('-mv', '--move_to',
                        type=str,
                        help='Output directory path of lower quality images among matches.',
                        required=False, default=None)
    parser.add_argument('-d', '--delete',
                        type=lambda x: str_to_bool(x),
                        help='Delete lower quality images among matches.',
                        required=False, choices=[True, False], default=False)
    # INFO: Changed default to False and using it to set logging level to debug.
    parser.add_argument('-p', '--show_progress',
                        type=lambda x: str_to_bool(x),
                        help='Show the real-time progress of difPy. Sets the logging level to debug for fast_diff_py ',
                        required=False, choices=[True, False], default=False)
    parser.add_argument('-sd', '--silent_del',
                        type=lambda x: str_to_bool(x),
                        help='Suppress the user confirmation when deleting images.',
                        required=False, choices=[True, False], default=False)
    parser.add_argument('-l', '--logs',
                        type=lambda x: str_to_bool(x),
                        help='(Deprecated) Collect statistics during the process.',
                        required=False, choices=[True, False], default=None)
    args = parser.parse_args()

    # ==================================================================================================================
    # Validating args beyond the defaults
    # ==================================================================================================================

    # Need to raise warning. deprecated not implemented in python3.12
    if args.logs is not None:
        warnings.warn('Parameter "logs" was deprecated with difPy v4.1. '
                      'Using it might lead to an exception in future versions. Consider updating your script.',
                      FutureWarning, stacklevel=2)

    # Validate the pixel size
    if not 10 < args.px_size < 5000:
        raise ValueError("Invalid value for Pixel Size [10, 5000] ")

    if not isinstance(args.px_size, int):
        raise TypeError(f"Invalid Type of Pixel Size {type(args.px_size).__name__}")

    # validate move, delete and silent_delete, one without the other is useless.
    if args.silent_del and not args.delete:
        warnings.warn("Parameter 'silent_del' has no effect without 'delete'")

    # INFO: Handling inconsistency from dif.py by raising Error.
    if args.delete and args.move_to is not None:
        raise ValueError("Parameter 'move_to' conflicts with 'delete'. Specify either or. ")

    # Get the start_dir
    a_dir = args.directory[-1] if args.output_directory is None else args.output_directory

    # Get the partitions from the inputs.
    part_a, part_b = parse_dirs(args.directory, args.in_folder)

    # Convert the similarity to usable format.
    similarity = parse_similarity(args.similarity)

    # Subsequently using the dict in order to be able to recover the args from the config
    cli_args = args.__dict__

    # ==================================================================================================================
    # Progress recovery and fast_diff_py object generation
    # ==================================================================================================================
    if os.path.exists(os.path.join(a_dir, ".task.json")) \
            and input("A config from a previous iteration is present. Do you want to discard the progress? (y/n)\n") \
            .lower() == 'y':
        output = dif(
            _part_a=part_a,
            _part_b=part_b,
            _similarity=similarity,
            px_size=args.px_size,
            limit_ext=args.limit_extensions,
            processes=args.processes,
            chunk=args.chunksize,
            recursive=args.recursive,
            lazy=args.lazy,
            rotate=args.rotate,
            cli_args=cli_args,
            debug=args.show_progress
        )

    elif os.path.exists(os.path.join(a_dir, ".fast_diff.db")) \
            and input("A database from a previous iteration is present. Do you want overwrite that database? (y/n)\n") \
            .lower() == 'y':
        output = dif(
            _part_a=part_a,
            _part_b=part_b,
            _similarity=similarity,
            px_size=args.px_size,
            limit_ext=args.limit_extensions,
            processes=args.processes,
            chunk=args.chunksize,
            recursive=args.recursive,
            lazy=args.lazy,
            rotate=args.rotate,
            cli_args=cli_args,
            debug=args.show_progress
        )
    elif not os.path.exists(os.path.join(a_dir, ".task.json")) \
            and not os.path.exists(os.path.join(a_dir, ".fast_diff.db")):
        output = dif(
            _part_a=part_a,
            _part_b=part_b,
            _similarity=similarity,
            px_size=args.px_size,
            limit_ext=args.limit_extensions,
            processes=args.processes,
            chunk=args.chunksize,
            recursive=args.recursive,
            lazy=args.lazy,
            rotate=args.rotate,
            cli_args=cli_args,
            debug=args.show_progress
        )
    else:
        print("INFO: Recovering")
        output = recover(dir_a=a_dir)
        cli_args = output.config.cli_args
        similarity = output.config.second_loop.diff_threshold

    # Process interrupted
    if output is None:
        print("Process was interrupted before fast_diff_py could finish. Progress is saved. Exiting now")
        exit(0)

    # Get the clusters again.
    if output.config.partition_swapped:
        clusters = output.get_diff_clusters(matching_hash=True, dir_a=False)
    else:
        clusters = output.get_diff_clusters(matching_hash=True, dir_a=True)

    # Prepare the dict and list for lower_quality.txt and results.json
    results = {}
    lower_quality = []

    # Get the clusters from the
    for head, duplicates in clusters:
        results[head] = duplicates

        # Building the lower quality
        for elm in duplicates:
            lower_quality.append(elm[0])

    if cli_args["move_to"] is not None:
        res = move_duplicates(lower_quality, cli_args["move_to"])
        print(f"Moved {res} files")

    if cli_args["delete"]:
        res = delete_files(lower_quality, cli_args["silent_del"])
        print(f"Delete {res} files")

    # check if 'output_directory' parameter exists
    if cli_args["output_directory"] is not None:
        out_dir = cli_args["output_directory"]
        if not os.path.exists(out_dir):
            print(f"INFO: Creating output directory {out_dir}")
            os.makedirs(out_dir)
    else:
        out_dir = os.getcwd()

    # create filenames for the output files
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    result_file = f'difPy_{timestamp}_results.json'
    lq_file = f'difPy_{timestamp}_lower_quality.txt'
    stats_file = f'difPy_{timestamp}_stats.json'

    # INFO: using indentation to make files more readable.
    # Writing results
    with open(os.path.join(out_dir, result_file), 'w') as file:
        json.dump(results, file, indent=4)

    # Writing the lower quality files.
    with open(os.path.join(out_dir, lq_file), 'w') as file:
        json.dump(list(set(lower_quality)), file, indent=4)

    # And writing the stats.
    with open(os.path.join(out_dir, stats_file), 'w') as file:
        json.dump(construct_stats(output), file, indent=4)

    print(f'''\n{result_file}\n{lq_file}\n{stats_file}\n\nsaved in '{out_dir}'.''')

    # perform cleanup of fast-diff-py
    output.config.delete_db = True
    output.config.retain_progress = False
    output.config.delete_thumb = True
    output.commit()
    output.cleanup()


if __name__ == "__main__":
    main()