"""
Use this file to generate test cases for duplicates. Two modes are supported:
- Partition
- Copy

## Partition Mode.
Partition mode is used to test for dir_a and dir_b. It has a probability to duplicate a file in both directories
and a probability with which a file is moved to the dir_b.
probability of duplication = 0.001 (is evaluated first)
probability of moving to dir_b = 0.5
The files can be moved or symlinked.

## Copy Mode
In Copy Mode, the files are copied with a probability to a secondary directory. The files in the initial directory are
always left. leading to a directory of duplicates and a directory of originals.
"""

import os
import random
import warnings
from typing import Tuple
import shutil
import argparse


def remove_prefix(text, prefix):
    """
    Remove a prefix from a string
    """
    if text.startswith(prefix):
        return text[len(prefix):]
    return text


def partition(source: str,
              dir_a: str,
              dir_b: str,
              pd: float = 0.001,
              pb: float = 0.5,
              op: str = "MOVE",
              limit: int = 40000) -> Tuple[int, int, int]:
    """
    Partition mode to generate duplicates. Uses Symlinks in dir_a and dir_b to link to the files in the src directory

    :param source: The source directory
    :param dir_a: The first directory
    :param dir_b: The second directory
    :param pd: The probability of duplication
    :param pb: The probability of moving to dir_b
    :param op: The operation to perform (MOVE, COPY, LINK)
    :param limit: The limit of files to process (scanning not duplicating)

    :return: Number of files in dir a, number of files in dir b, number of duplicates
    """
    op = op.upper()
    if op not in ["MOVE", "COPY", "LINK"]:
        raise ValueError(f"Operation {op} not supported")

    def partition_internal(_src: str,
                           _cur: str,
                           _dir_a: str,
                           _dir_b: str,
                           _pd: float,
                           _pb: float,
                           _op: str,
                           _ca: int, _cb: int, _cd: int, _limit: int = None) -> Tuple[int, int, int]:
        """
        Internal partition function

        :param _src: The source directory
        :param _cur: The current directory prefix within the source directory
        :param _dir_a: Partition Directory A
        :param _dir_b: Partition Directory B
        :param _pd: Probability of duplication during the partition. Duplicating iff random.random() < _pd
        :param _pb: Probability of moving to Partition B. Move to Partition if random.random() < _pb
        :param _limit: Number of files to process (scanning)
        :param _op: Operation to perform (MOVE, COPY, LINK)
        :param _ca: Current number of files in partition a
        :param _cb: Current number of files in partition b.
        :param _cd: Current number of files in both partitions.

        :return: Number of files in dir a, number of files in dir b, number of duplicates
        """

        a, b, d = _ca, _cb, _cd
        abs_src = os.path.abspath(_src)
        abs_a = os.path.abspath(_dir_a)
        abs_b = os.path.abspath(_dir_b)
        cp = os.path.join(abs_src, _cur)
        _ca = os.path.join(abs_a, _cur)
        _cb = os.path.join(abs_b, _cur)

        for f in os.listdir(cp):
            if _limit is not None and (a > _limit or b > _limit):
                return a, b, d

            # If it's a directory, we need to recurse
            if os.path.isdir(os.path.join(cp, f)):
                a, b, c = partition_internal(_src, os.path.join(_cur, f),
                                             _dir_a, _dir_b, _pd, _pb, _op, a, b, d, _limit)

            # If it's a file, we need to copy it
            elif os.path.isfile(os.path.join(cp, f)):
                # Duplicate the file
                if random.random() < _pd:
                    # Create directory in dir_a
                    if not os.path.exists(_ca):
                        os.makedirs(_ca)

                    # Create directory in dir_b
                    if not os.path.exists(_cb):
                        os.makedirs(_cb)

                    if _op == "LINK":
                        os.symlink(os.path.join(cp, f), os.path.join(_ca, f))
                        os.symlink(os.path.join(cp, f), os.path.join(_cb, f))
                    elif _op == "MOVE":
                        shutil.move(os.path.join(cp, f), os.path.join(_ca, f))
                        shutil.copy(os.path.join(_ca, f), os.path.join(_cb, f))
                    elif _op == "COPY":
                        shutil.copy(os.path.join(cp, f), os.path.join(_ca, f))
                        shutil.copy(os.path.join(cp, f), os.path.join(_cb, f))
                    a, b, d = a + 1, b + 1, d + 1

                # Symlink to either or
                else:
                    # Symlink to dir_b
                    if random.random() < _pb:
                        if not os.path.exists(_cb):
                            os.makedirs(_cb)
                        if _op == "LINK":
                            os.symlink(os.path.join(cp, f), os.path.join(_cb, f))
                        elif _op == "MOVE":
                            shutil.move(os.path.join(cp, f), os.path.join(_cb, f))
                        elif _op == "COPY":
                            shutil.copy(os.path.join(cp, f), os.path.join(_cb, f))
                        b += 1

                    # Symlink to dir_a
                    else:
                        if not os.path.exists(_ca):
                            os.makedirs(_ca)
                        if _op == "LINK":
                            os.symlink(os.path.join(cp, f), os.path.join(_ca, f))
                        elif _op == "MOVE":
                            shutil.move(os.path.join(cp, f), os.path.join(_ca, f))
                        elif _op == "COPY":
                            shutil.copy(os.path.join(cp, f), os.path.join(_ca, f))
                        a += 1
            else:
                print(f"Skipping {f}")

        return a, b, d

    return partition_internal(source, "", dir_a, dir_b, pd, pb, _op=op, _limit=limit, _ca=0, _cb=0, _cd=0)


def duplicate(src: str,
              dst: str,
              pc: float = 0.5,
              op: str = "COPY",
              limit: int = None) -> Tuple[int, int]:
    """
    Duplicate mode to generate duplicates.

    :param src: The first directory
    :param dst: The second directory
    :param pc: The probability of Duplicating. Duplicate iff random.random() < pc
    :param op: The operation to perform (COPY, LINK)
    :param limit: The limit of files to process (max number of duplicates)

    :return: Number of files in dir a, number of files in dir b
    """

    op = op.upper()
    if op not in ["COPY", "LINK"]:
        raise ValueError(f"Operation {op} not supported")

    def duplicate_internal(_src: str,
                           _dst: str,
                           _cur: str,
                           _pc: float,
                           _op: str,
                           _s: int,
                           _d: int,
                           _limit: int = None) -> Tuple[int, int]:
        """
        Internal function to generate duplicates.

        :param _src: The directory to get the images from
        :param _dst: The directory to copy all duplicates into
        :param _cur: The current suffix of the src directory to be replicated in the dst directory
        :param _pc: The probability of copying. Copy iff random.random() < pc
        :param _op: The operation to perform (COPY, LINK)
        :param _limit: The limit of files to process (max number of duplicates)
        :param _s: Number of files scanned
        :param _d: Number of files copied into dst

        :return: Number of files scanned, number of files duplicated
        """
        abs_src = os.path.abspath(_src)
        abs_dst = os.path.abspath(_dst)
        cp = os.path.join(abs_src, _cur)
        cd = os.path.join(abs_dst, _cur)

        for f in os.listdir(cp):
            if _limit is not None and _d > _limit:
                return _s, _d

            # If it's a directory, we need to recurse
            if os.path.isdir(os.path.join(cp, f)):
                _s, _d = duplicate_internal(_src, _dst, os.path.join(_cur, f), _pc, _op, _s, _d, _limit)

            # If it's a file, we need to copy it
            elif os.path.isfile(os.path.join(cp, f)):
                _s += 1
                if random.random() < _pc:
                    # Create directory in dst
                    if not os.path.exists(cd):
                        os.makedirs(cd)

                    if _op == "LINK":
                        os.symlink(os.path.join(cp, f), os.path.join(cd, f))
                    elif _op == "COPY":
                        shutil.copy(os.path.join(cp, f), os.path.join(cd, f))

                    _d += 1
            # We've got something we don't know.
            else:
                print(f"Skipping {f}")

    return duplicate_internal(src, dst, "", pc, op, limit, 0, 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate duplicate images")

    # Required
    parser.add_argument("mode", type=str, help="Directory to get images from",
                        choices=["PARTITION", "DUPLICATE"])
    parser.add_argument("-o", "--operation", type=str,
                        help="Operation to perform. Can be COPY, LINK and only for partition MOVE",
                        choices=["COPY", "LINK", "MOVE"],
                        default="COPY",
                        required=False)
    parser.add_argument("-s", "--source", type=str,
                        help="Directory to get images from",
                        required=True)
    parser.add_argument("-a", "--partition_a", type=str,
                        help="First Partition in PARTITION mode and destination for duplicates in DUPLICATE mode",
                        required=True)

    # Optionals
    parser.add_argument("-b", "--partition_b", type=str,
                        help="Second Partition in PARTITION")
    parser.add_argument("-d", "--duplication", type=float, default=0.001,
                        help="Probability to generate a duplicate. Uses a random float between 0 and 1. "
                             "A file is duplicated iff random.random() < pc")
    parser.add_argument("-l", "--limit", type=int,
                        help="Limit number of files to process, in PARTITION mode limits the number of files in either "
                             "partition (so if size(part_a) > limit or size(part_b) > limit stop), in DUPLICATE mode"
                             "it limits the number of duplicates generated!")
    parser.add_argument("-p", "--probability_b", type=float, default=0.5,
                        help="Probability of a file going into partition b in PARTITION mode. Goes into Partition B iff"
                             "random.random() < p. Has no effect on DUPLICATE mode")
    args = parser.parse_args()

    print(args)

    # Validate arguments
    if not 0 < args.duplication < 1:
        raise ValueError("Duplication value must be between 0 and 1")

    if not 0 < args.probability_b < 1:
        raise ValueError("Probability value must be between 0 and 1")

    if args.mode == "DUPLICATE":
        if args.operation == "MOVE":
            raise ValueError("Duplicate mode not supported for MOVE")

        if args.partition_b is not None:
            warnings.warn("Duplicate mode doesn't use partition_b, argument will be ignored")

    if args.mode == "PARTITION":
        if args.partition_b is None:
            raise ValueError("PARTITION mode needs partition_b")


    if args.mode == "DUPLICATE":
        res = duplicate(args.source, args.partition_a, args.duplication, args.operation, args.limit)
        print(f"Scanned {res[0]} files and duplicated {res[1]} files.")

    else:
        res = partition(args.source, args.partition_a, args.partition_b,
                        args.duplication, args.probability_b, args.operation, args.limit)
        print(f"Files in Partition A: {res[0]}, Files in Partition B: {res[1]}, Files in both Partitions: {res[2]}")