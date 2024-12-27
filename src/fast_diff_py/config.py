import datetime
import logging
import os
from enum import Enum
from typing import Optional, List, Union, Literal, Annotated, Dict

from annotated_types import Ge
from pydantic import BaseModel, Field


class Progress(str, Enum):
    """
    Enum for progress
    """
    INIT = "init"
    INDEXED_DIRS = "indexed_dirs"
    FIRST_LOOP_IN_PROGRESS = "first_loop_in_progress"
    FIRST_LOOP_DONE = "first_loop_done"
    SECOND_LOOP_IN_PROGRESS = "second_loop_in_progress"
    SECOND_LOOP_DONE = "second_loop_done"


class FirstLoopConfig(BaseModel):
    """
    Config for the first loop computing. This loops computes hashes and thumbnails. It runs in O(n) time.
    """
    compress: bool = Field(True,
                           description="Whether to compress the images to a target size during the first loop")
    compute_hash: bool = Field(False,
                               description="Whether to compute the hash of the images during the first loop")
    shift_amount: int = Field(4,
                              le=7,
                              ge=-7,
                              description="The amount to shift the image before computing the hash")
    parallel: bool = Field(True,
                            description="Whether to run the first loop in parallel")
    elapsed_seconds: float = Field(0,
                                 description="The number of seconds the first loop has taken. "
                                             "Set on exit of first loop")
    cpu_proc: int = Field(default_factory=lambda: os.cpu_count(),
                            description="The number of CPU processes to use for the first loop")

class FirstLoopRuntimeConfig(FirstLoopConfig):
    """
    Runtime config for the first loop
    """
    batch_size: Optional[int] = Field(None,
                                        description="The batch size for the first loop")
    start_dt: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC),
                                        description="Datetime at which the first loop started")
    total: int = Field(0,
                       description="Total number of files to process.")
    done: int = Field(0,
                      description="Number of files processed.")

class SecondLoopConfig(BaseModel):
    # Because of batching this doesn't make much sense.
    skip_matching_hash: bool = Field(False,
                                     description="whether to skip the comparison if the hash matches\n"
                                                 "This forces the second loop algorithm to run with item submission"
                                                 " instead of batch submission")
    match_aspect_by: Optional[Union[Annotated[float, Ge(1.0)], Literal[0]]] = (
        Field(None,
              description="Matches the aspect ratio of the image. Either pixel by pixel in case of 0.0 or "
                          "the aspect ratio needs to be in  the interval a * factor > b > a / factor "))
    make_diff_plots: bool = Field(False,
                                  description="whether to make diff plots and store them in the output directory\n"
                                              "This forces the second loop algorithm to run with item submission")
    plot_output_dir: Optional[str] = Field(None,
                                           description="the directory to store the diff plots"
                                                       "\n Must be set in conjunction with the make_diff_plots flag")

    plot_threshold: Optional[float] = Field(None,
                                            description="Threshold for generating a plot, defaults to diff_threshold")

    parallel: bool = Field(True,
                           description="Whether to run the second loop in parallel")

    batch_size: Optional[int] = Field(None,
                                        description="The batch size for the second loop")

    diff_threshold: float = Field(200.0,
                                    description="The threshold for similarity between images")
    gpu_proc: int = Field(0,
                          description="The number of GPU processes to use for the second loop")
    cpu_proc: int = Field(default_factory=lambda: os.cpu_count(),
                            description="The number of CPU processes to use for the second loop")
    keep_non_matching_aspects: bool = Field(False,
                                            description="Whether to keep non matching aspects in the database for "
                                                        "the diffs. This is useful for debugging purposes")
    preload_count: int = Field(4,
                               gt=1,
                               description="Number of caches to prepare in advance. Tune this variable to ensure "
                                           "you don't run into a memory overflow")
    elapsed_seconds: float = Field(0,
                                 description="The number of seconds the second loop has taken. "
                                             "Set on exit of second loop")

class SecondLoopRuntimeConfig(SecondLoopConfig):
    cache_index: int = Field(0,
                                description="The index of the cache")
    finished_cache_index: Optional[int] = Field(None,
                                                description="Index of the cache field we're done with")
    start_dt: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC),
                                        description="Datetime at which the second loop started")
    total: int = Field(0,
                       description="Total number of files to process.")
    done: int = Field(0,
                      description="Number of files processed.")

class Config(BaseModel):
    compression_target: int = Field(64,
                                    description="The target size of compressed images i.e. "
                                                "size = (compression_target * compression_target)")

    part_a: Union[List[str], str] = Field(...,
                                    min_length=1,
                                    description="Directory or List of Directories to be added to partition a")
    part_b: Union[List[str], str] = Field(default_factory=lambda: [],
                                              description="Directory or List of Directories to be added to partition b")

    dir_index_lookup: Optional[List[str]] = Field(None,
                                                    description="Lookup from directory given in partition a and "
                                                                "partition b to the index in the directory table")

    partition_swapped: bool = Field(False,
                                     description="If the partition names were swapped during table optimization")

    dir_index_elapsed: float = Field(0,
                                   description="The number of seconds the indexing has taken")

    recurse: bool = Field(True, 
                          description="Whether to recurse into directories that are in root_dir_a and root_dir_B")

    rotate: bool = Field(True,
                        description="Whether to rotate the images during the comparison process")

    thumb_dir: Optional[str] = Field(None,
                            description="The directory to store the thumbnails")

    ignore_names: List[str] = Field(default_factory=lambda: [],
                                    description="The names of the directories or files to ignore")
    ignore_paths: List[str] = Field(default_factory=lambda: [],
                                    description="The paths of the directories or files to ignore")
    allowed_file_extensions: List[str] = Field(
        default_factory=lambda : ['.apng', '.bw', '.cdf', '.cur', '.dcx', '.dds', '.dib', '.emf', '.eps', '.fli',
                                  '.flc', '.fpx', '.ftex', '.fits', '.gd', '.gd2', '.gif', '.gbr', '.icb', '.icns',
                                  '.iim', '.ico', '.im', '.imt', '.j2k', '.jfif', '.jfi', '.jif', '.jp2', '.jpe',
                                  '.jpeg', '.jpg', '.jpm', '.jpf', '.jpx', '.jpeg', '.mic', '.mpo', '.msp', '.nc',
                                  '.pbm', '.pcd', '.pcx', '.pgm', '.png', '.ppm', '.psd', '.pixar', '.ras', '.rgb',
                                  '.rgba', '.sgi', '.spi', '.spider', '.sun', '.tga', '.tif', '.tiff', '.vda', '.vst',
                                  '.wal', '.webp', '.xbm', '.xpm'],
        description="The allowed file extensions for the images")

    batch_size_dir: int = Field(1000,
                                description="The batch size for the directory processing. "
                                            "Once the batch size is reached, data is written to the db")

    batch_size_max_fl: int = Field(100,
                                description="Maximum Batch Size for the First Loop")

    batch_size_max_sl: int = Field(os.cpu_count() * 250,
                                   description="Maximum Batch Size for the Second Loop")

    db_path: Optional[str] = Field(None,
                                   description="Override for the path to the db file")
    config_path: Optional[str] = Field(None,
                                        description="Override for the path to the config file")
    log_level: int = Field(logging.INFO,
                          description="Whether to print verbose output")
    log_level_children: int = Field(logging.INFO,
                            description="Whether to print verbose output for the children")
    state: Progress = Field(Progress.INIT,
                            description="The current state of the progress")
    retain_progress: bool = Field(True,
                                  description="Whether to retain the progress from previous runs in config file")
    cli_args: Optional[Dict] = Field(None,
                                    description="The CLI arguments to use for the run")

    first_loop: Union[FirstLoopConfig, FirstLoopRuntimeConfig] = Field(default_factory= lambda: FirstLoopConfig(),
                                                                       description="The config for the first loop")
    second_loop: Union[SecondLoopConfig, SecondLoopRuntimeConfig] = Field(default_factory=lambda: SecondLoopConfig(),
                                                                          description="The config for the second loop")
    do_second_loop: bool = Field(True,
                                description="Whether to do the second loop")

    child_proc_timeout: int = Field(30,
                                    description="The timeout for the child processes")

    delete_db: bool = Field(True,
                            description="Whether to delete the db file after the process is done")

    delete_thumb: bool = Field(True,
                                description="Whether to delete the thumbnail directory after the process is done")
