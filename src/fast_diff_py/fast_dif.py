import datetime
import itertools
import logging
import multiprocessing as mp
import os.path
import shutil
import time
import pickle
from logging.handlers import QueueListener
from typing import List, Union, Callable, Dict, Optional, Tuple

import numpy as np
import fast_diff_py.img_processing as imgp
from fast_diff_py.base_process import GracefulWorker
from fast_diff_py.cache import ImageCache, BatchCache
from fast_diff_py.child_processes import FirstLoopWorker, SecondLoopWorker
from fast_diff_py.config import Config, Progress, FirstLoopConfig, SecondLoopConfig, SecondLoopRuntimeConfig, \
    FirstLoopRuntimeConfig
from fast_diff_py.datatransfer import (PreprocessResult, SecondLoopArgs, SecondLoopResults)
from fast_diff_py.sqlite_db import SQLiteDB
from fast_diff_py.utils import sizeof_fmt, BlockProgress, build_start_blocks_a, build_start_blocks_ab


class FastDifPy(GracefulWorker):
    db: SQLiteDB = None
    config: Config = None
    logger: logging.Logger

    handles: Union[List[mp.Process], None] = None
    exit_counter: int = 0

    # Child process perspective
    cmd_queue: Optional[mp.Queue] = None
    result_queue: Optional[mp.Queue] = None
    logging_queue: mp.Queue = mp.Queue()
    ql: logging.handlers.QueueListener = None

    # Used for logging
    _enqueue_counter: int = 0
    _dequeue_counter: int = 0
    _last_dequeue_counter: int = 0

    # Attrs related to running the loop
    manager: mp.Manager = mp.Manager()
    ram_cache: Optional[Dict[int, bytes]] = None

    # The key in the first dict is the same as the ram_cache key
    # The second dict contains a key for each row in the block. The 'key' int is the key_a of the dif_table
    #
    # If they have, we move to the next block, drop the current cache index, and decrement the progress_counter by the
    # number of keys in the dict we're about to delete
    blocks: List[BlockProgress] = []
    block_progress_dict: Dict[int, Dict[int, bool]] = {}
    dir_a_count: Optional[int] = None
    dir_b_count: Optional[int] = None

    hash_fn: Optional[Callable[[str], str] | Callable[[np.ndarray[np.uint8]], str]] = None
    cpu_diff: Optional[Callable[[np.ndarray[np.uint8], np.ndarray[np.uint8], bool], float]] = None
    gpu_diff: Optional[Callable[[np.ndarray[np.uint8], np.ndarray[np.uint8], bool], float]] = None

    # ==================================================================================================================
    # Util
    # ==================================================================================================================

    def commit(self):
        """
        Commit the db and the config
        """
        self.db.commit()
        cfg = self.config.model_dump_json()

        if not self.config.retain_progress:
            return

        assert self.config.config_path is not None, "Config Path needs to be set before writing config"

        path = self.config.config_path

        with open(path, "w") as file:
            file.write(cfg)

    def cleanup(self):
        """
        Clean up the FastDifPy object, stopping the logging queue,
        """
        if self.config.delete_db:
            self.logger.info(f"Closing DB and deleting DB at {self.config.db_path}")
            self.db.close()
            os.remove(self.config.db_path)

        if self.config.delete_thumb:
            self.logger.info(f"Deleting Thumbnail Directory at {self.config.thumb_dir}")
            shutil.rmtree(self.config.thumb_dir)

        if not self.config.retain_progress:
            if os.path.exists(self.config.config_path):
                self.logger.info("Removing Task File")
                os.remove(self.config.config_path)

        if self.ql is not None:
            self.ql.stop()

    def test_cleanup(self):
        """
        Handle the cleanup in case
        """
        if self.db is not None:
            self.db.cleanup()

        if self.config.thumb_dir is not None:
            if os.path.exists(self.config.thumb_dir):
                shutil.rmtree(self.config.thumb_dir)

        if self.config.config_path is not None:
            if os.path.exists(self.config.config_path):
                os.remove(self.config.config_path)

        if self.ql is not None:
            self.ql.stop()

    def start_logging(self):
        """
        Start the logging process. This is done by starting the QueueListener
        """
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.ql = QueueListener(self.logging_queue, handler, respect_handler_level=True)
        self.ql.start()

    # ==================================================================================================================
    # Database Wrappers
    # ==================================================================================================================

    def get_diff_pairs(self, delta: float = None, matching_hash: bool = False) -> List[Tuple[str, str, float]]:
        """
        Get the diff pairs from the database. Wrapper for db.get_duplicate_pairs.

        :param delta: The threshold for the difference
        :param matching_hash: Whether to include pairs with diff = 0 because their hashes matched

        INFO: Needs the db to exist and be connected

        :return: A list of tuples of the form (file_a, file_b, diff)
        """
        if delta is not None and delta > self.config.second_loop.diff_threshold:
            self.logger.warning("Delta is greater than the threshold. Result may not include all pairs")

        if delta is None:
            delta = self.config.second_loop.diff_threshold

        for p in self.db.get_duplicate_pairs(delta, include_hash_match=matching_hash):
            yield p

    def get_diff_clusters(self, delta: float = None, dir_a: bool = True, matching_hash: bool = False) \
            -> Tuple[str, Dict[str, float]]:
        """
        Get a Cluster of Duplicates. Wrapper for db.get_cluster.

        A Cluster is characterized by a common image in either dir_a or dir_b.

        :param delta: The threshold for the difference
        :param dir_a: Whether to get the cluster for dir_a or dir_b
        :param matching_hash: Whether to include pairs with diff = 0 because their hashes matched

        INFO: Needs the db to exist and be connected

        :return: A list of tuples of the form (common_file, {file: diff})
            where common_file is either always in dir_a or dir_b and the files in the dict are in the opposite directory
        """
        if delta is not None and delta is not None and delta > self.config.second_loop.diff_threshold:
            self.logger.warning("Delta is greater than the threshold. Result may not include all pairs")

        if delta is None:
            delta = self.config.second_loop.diff_threshold

        for h, d in self.db.get_cluster(delta, dir_a, matching_hash):
            yield h, d

    def reduce_diff(self, threshold: float):
        """
        Reduce the diff table based on the threshold provided. All pairs with a higher threshold are removed.

        Wrapper for db.drop_diff

        :param threshold: The threshold for the difference
        """
        self.db.drop_diff(threshold)

    def populate_partition(self, paths: List[str], part_a: bool = True, check_ext: bool = False):
        """
        Populate the directory table. If the integrated file discovery methods with root_dir_a and root_dir_b are not
        sufficient, the two partitions can be populated manually.

        The function checks if the file exists in the file system. Correct extension can be verified as well if needed.

        :param paths: List of File Paths
        :param part_a: Whether to populate partition A or B
        :param check_ext: Whether to check the extension of the files, (useful for debugging)

        :return: The number of files added
        """
        count = 0

        fpaths = []
        allowed = []
        fsize = []
        create = []

        for f in paths:
            # File doesn't exist
            if not os.path.exists(f):
                self.logger.warning(f"File {f} does not exist")

                fpaths.append(f)
                allowed.append(0)
                fsize.append(-1)
                create.append(-1)
                continue

            # Get the stats
            stats = os.stat(f)
            fpaths.append(f)
            fsize.append(stats.st_size)
            create.append(stats.st_ctime)

            # Precondition: File Exists
            if check_ext and os.path.splitext(f)[1].lower() not in self.config.allowed_file_extensions:
                self.logger.warning(f"File {f} has an unsupported extension")
                allowed.append(0)
            else:
                allowed.append(1)

            # Write to db
            if len(fpaths) > self.config.batch_size_dir:
                self.db.bulk_insert_file_external(fpaths, allowed, fsize, create, part_a)
                count += len(fpaths)

                fpaths = []
                allowed = []
                fsize = []
                create = []

        if len(fpaths) > 0:
            self.db.bulk_insert_file_external(fpaths, allowed, fsize, create, part_a)
            count += len(fpaths)

        return count

    def purge_preexisting_directory_table(self):
        """
        Purge the preexisting directory table.

        Wrapper around db.drop_directory_table

        Function is needed for recovering the progress already made (when the process was halted mid indexing)
        """
        if self.db.dir_table_exists():
            self.logger.info("Purging Preexisting Directory Table")
            self.db.drop_directory_table()

    # ==================================================================================================================
    # INIT
    # ==================================================================================================================

    def __init__(self, dir_a: str = None, dir_b: str = None, config: Config = None,
                 default_cfg_path: str = None, purge: bool = False, test_mode: bool = False, **kwargs):
        """
        Initialize the FastDifPy object.

        Initialization follows the following structure:
        - First source of truth is the config parameter. If it is provided, the object is initialized with the config.
        - Second source of truth is the default_cfg_path. If it is provided, the object is initialized with the config
        - Third source of truth is the .task.json file in the 'a root' directory. If it is present, the object is
        initialized with the config.

        :param dir_a: The first directory to compare (if no config and default_cfg_path is provided,
            task is searched there)
        :param dir_b: The second directory to compare
        :param config: The config override in case we want to use a specific config
        :param default_cfg_path: The path to the config if it's supposed to be loaded from a file
        :param purge: Whether to purge the existing progress and start anew (has only effect for first and third source)
        :param test_mode: expects a config to be passed, sets up loging and sets the config. Everything else is ignored.

        :kwargs: Additional arguments to be passed to the Config object. Check out the config objects for more details.

        # TODO docs about kwargs
        """
        super().__init__(0)
        self.logger = logging.getLogger("FastDiffPy_Main")
        self.logger.setLevel(logging.DEBUG)

        qh = logging.handlers.QueueHandler(self.logging_queue)
        self.logger.addHandler(qh)
        self.start_logging()

        # Exit if we're in test mode
        if test_mode:
            if config is None:
                raise ValueError("Test Mode requires a config to be passed")
            self.config = config
            return

        # First Source of Truth - config
        if config is not None:
            self.config = config

            self.logger.info("Using Provided Config")

            # Populate on empty
            self.add_defaults_to_config()

            if purge:
                self.logger.info("Purging any preexisting progress and using provided config")
                self.clean_and_init()

            else:
                self.logger.info("Connecting to existing progress and using provided config")
                self.reconnect_to_existing()

        # Second Source of Truth - default_cfg_path
        elif default_cfg_path is not None:
            self.logger.info("Using provided Default Config Path")
            if not os.path.exists(default_cfg_path):
                raise FileNotFoundError(f"Config Path {default_cfg_path} does not exist")

            with open(default_cfg_path, "r") as file:
                self.config = Config.model_validate_json(file.read())

            self.config.config_path = default_cfg_path

            self.add_defaults_to_config()

            self.reconnect_to_existing()

        # Third Source of Truth - .task.json in the directory
        elif dir_a is not None:
            config_path = os.path.join(dir_a, ".task.json")

            if os.path.exists(config_path) and not purge:
                self.logger.info("Using Existing Config File in dir_a")
                with open(config_path, "r") as file:
                    self.config = Config.model_validate_json(file.read())

                self.config.config_path = config_path
                self.add_defaults_to_config()
                self.reconnect_to_existing()

            else:
                if dir_b is None:
                    dir_b = []
                self.config = Config(part_a=dir_a, part_b=dir_b, **kwargs)
                self.add_defaults_to_config()
                self.clean_and_init()

        else:
            raise ValueError("Not enough arguments are provided to initialize the FastDifPy object")

        self.logger.setLevel(self.config.log_level)

        self.register_interrupts()

    def add_defaults_to_config(self):
        """
        Add default paths to config if they are not provided. Those being:
        - db_path
        - thumb_dir
        - config_path
        """
        rp = self.config.part_a if isinstance(self.config.part_a, str) else self.config.part_a[0]

        if self.config.db_path is None:
            self.config.db_path = os.path.join(rp, ".fast_diff.db")
            self.logger.info(f"DB Path not provided. Using {self.config.db_path}")

        if self.config.thumb_dir is None:
            self.config.thumb_dir = os.path.join(rp, ".temp_thumb")
            self.logger.info(f"Thumbnail Directory not provided. Using {self.config.thumb_dir}")

        if self.config.config_path is None:
            self.config.config_path = os.path.join(rp, ".task.json")
            self.logger.info(f"Config Path not provided. Using {self.config.config_path}")

    def clean_and_init(self):
        """
        Cleanly instantiates everything needed for the FastDifPy object
        """
        # DB Path
        if os.path.exists(self.config.db_path):
            self.logger.info("Removing preexisting DB")
            os.remove(self.config.db_path)

        self.db = SQLiteDB(self.config.db_path, debug=__debug__)

        # Config Path
        if os.path.exists(self.config.config_path):
            self.logger.info("Removing preexisting Config File")
            os.remove(self.config.config_path)

        self.commit()

        # Thumbnail Directory
        if os.path.exists(self.config.thumb_dir):
            self.logger.info("Removing preexisting Thumbnail Directory")
            shutil.rmtree(self.config.thumb_dir)

        os.makedirs(self.config.thumb_dir)

    def reconnect_to_existing(self):
        """
        Reconnect to existing progress, config, db, etc.

        Verifies:
        - dir_a
        - dir_b if provided
        - db_path
        - thumb_dir

        :raises FileNotFoundError: If any of the paths do not exist
        """
        a = [self.config.part_a] if isinstance(self.config.part_a, str) else self.config.part_a
        b = [self.config.part_b] if isinstance(self.config.part_b, str) else self.config.part_b

        all_paths = a + b

        # Check all paths
        for p in all_paths:
            if not os.path.exists(p):
                raise FileNotFoundError(f"Directory {self.config.part_a} does not exist")

        if not os.path.exists(self.config.db_path):
            raise FileNotFoundError(f"DB Path {self.config.db_path} does not exist")
        else:
            self.db = SQLiteDB(self.config.db_path, debug=__debug__)

        if not os.path.exists(self.config.thumb_dir):
            raise FileNotFoundError(f"Thumbnail Directory {self.config.thumb_dir} does not exist")

    # ==================================================================================================================
    # Indexing
    # ==================================================================================================================

    def index_preamble(self):
        """
        Setting up everything to be able to index the directories
        """
        # Create the table
        self.db.create_directory_table_and_index()

    def index_epilogue(self):
        """
        Finish indexing operation - checkin partition sizes and switching partitions if necessary, and writing to disk.
        """
        self.db.repopulate_directory_table()

        # When run is set, we're done indexing
        if self.run:
            self.config.state = Progress.INDEXED_DIRS
            self.logger.info("Done Indexing Directories")

        self.commit()

    def full_index(self):
        """
        Full index performs all actions associated with indexing the files
        """
        self.index_preamble()

        # Index the directories
        self.perform_index()

        if not self.run:
            return

        self.index_epilogue()

    def check_directories(self) -> bool:
        """
        Check directories aren't subdirectories of each other
        """
        a = self.config.part_a if isinstance(self.config.part_a, list)  else [self.config.part_a]
        b = self.config.part_b if isinstance(self.config.part_b, list)  else [self.config.part_b]

        idx_a = [i for i in range(len(a))]
        idx_b = [i for i in range(len(b))]

        # checking within dir_a
        if len(a) > 1:
            for ix_a, ix_b in itertools.product(idx_a, idx_a):

                # Only check upper triangular matrix of combinations of directories
                if ix_a < ix_b and self.check_dir_pair(a[ix_a], a[ix_b]):
                    return True

        if len(b) > 0:
            if len(b) > 1:
                # checking within dir_b
                for ix_a, ix_b in itertools.product(idx_b, idx_b):

                    # Only check upper triangular matrix of combinations of directories
                    if ix_a < ix_b and self.check_dir_pair(b[ix_a], b[ix_b]):
                        return True

            # Checking between dir_b and dir_a
            for ix_a, ix_b in itertools.product(idx_a, idx_b):
                if self.check_dir_pair(a[ix_a], b[ix_b]):
                    return True

            return False

    def check_dir_pair(self, dir_a: str, dir_b: str) -> bool:
        """
        Check they if they are subdirectories of each other.

        :return: True if they are subdirectories of each other
        """
        # Take absolute paths just to be sure
        abs_a = os.path.abspath(dir_a)
        abs_b = os.path.abspath(dir_b)

        p_dir_a = os.path.dirname(abs_a)
        p_dir_b = os.path.dirname(abs_b)

        # Same directory, make sure we don't have the same name
        if p_dir_a == p_dir_b and os.path.basename(abs_a) == os.path.basename(abs_b):
            self.logger.error(f"Found identical directories in set of directories: {dir_a}, {dir_b}")
            return True

        # Otherwise check the prefixes if we do recurse
        if self.config.recurse:
            if abs_a.startswith(abs_b):
                self.logger.error(f"Found directory which is subdirectory of another. "
                                  f"Parent Directory: {dir_b}, child: {dir_a}")
                return True

            if abs_b.startswith(abs_a):
                self.logger.error(f"Found directory which is subdirectory of another. "
                                  f"Parent Directory: {dir_a}, child: {dir_b}")
                return True


    def perform_index(self, ignore_thumbs: bool = True):
        """
        Perform the indexing of the directories provided

        :param ignore_thumbs: Ignore thumbnail directory (any dir with name '.temp_thumb')
        """
        # Check if the directories are subdirectories of each other
        if self.check_directories():

            self.cleanup()
            raise ValueError("The two provided subdirectories are subdirectories of each other. Cannot proceed")

        self._enqueue_counter = 0
        self._dequeue_counter = 0
        self._last_dequeue_counter = 0

        self.logger.debug("Beginning indexing")

        # Fetching the list of dirs
        pa = self.config.part_a if isinstance(self.config.part_a, list) else [self.config.part_a]
        pb = self.config.part_b if isinstance(self.config.part_b, list) else [self.config.part_b]

        all_parts = pa + pb
        for i in range(len(all_parts)):
            # Exit on stop
            if not self.run:
                break

            p = os.path.abspath(all_parts[i])
            self.logger.info(f"Indexing Directory: {p}")
            part_a = i < len(pa)

            self.__recursive_index(p, part_a=part_a, dir_index=i, ignore_thumbnail=ignore_thumbs)

    def __recursive_index(self, path: str,
                          part_a: bool = True,
                          ignore_thumbnail: bool = True,
                          dir_count: int = 0,
                          dir_index: int = -1):
        """
        Recursively index the directories. This function is called by the index_the_dirs function.

        For speed improvements, the function will store up to `batch_size` files in ram before writing to db.
        Similarly, the function will store up to `batch_size` directories in ram before recursing.

        If the number of directories in ram is greater than `batch_size`, the function will start recursing early.
        If the number of files in ram is greater than `batch_size`, the function will write to the db early.

        :param ignore_thumbnail: If any directory at any level, starting with .temp_thumb should be ignored.
        :param part_a: True -> Index dir A. False -> Index dir B
        :param dir_count: The number of directories in all upper stages of the recursion.
        :param path: The path to index
        :param dir_index: The index of the directory in the list of directories (maybe need for reconstruction,
        available in the db

        :return:
        """
        if not self.run:
            return

        dirs = []
        files = []

        for file_name in os.listdir(path):
            full_path = os.path.join(path, file_name)

            # ignore a path if given
            if full_path in self.config.ignore_paths:
                continue

            # ignoring based only on name
            if file_name in self.config.ignore_names:
                continue

            # Thumbnail directory is called .temp_thumbnails
            if file_name.startswith(".temp_thumb") and ignore_thumbnail:
                continue

            # for directories, continue the recursion
            if os.path.isdir(full_path) and self.config.recurse:
                dirs.append(full_path)

            if os.path.isfile(full_path):
                allowed = 1 if os.path.splitext(full_path)[1].lower() in self.config.allowed_file_extensions else 0
                stats = os.stat(full_path)
                size = stats.st_size
                create = stats.st_ctime
                files.append((file_name, allowed, size, create))

            # let the number of files grow to a batch size
            if len(files) > self.config.batch_size_dir:
                # Store files in the db
                self.db.bulk_insert_file_internal(path, files, part_b=not part_a, index=dir_index)
                self._enqueue_counter += len(files)
                self.logger.info(f"Indexed {self._enqueue_counter} files")
                files = []

            # Start recursion early, if there is too much in RAM
            if len(dirs) + dir_count > self.config.batch_size_dir:
                # Dump the files
                self._enqueue_counter += len(files)
                self.logger.info(f"Indexed {self._enqueue_counter} files")
                self.db.bulk_insert_file_internal(path, files, part_b=not part_a, index=dir_index)
                files = []

                # Recurse through the directories
                while len(dirs) > 0:
                    d = dirs.pop()
                    self.__recursive_index(path=d,
                                           part_a=part_a,
                                           ignore_thumbnail=ignore_thumbnail,
                                           dir_count=dir_count + len(dirs))

        # Store files in the db
        self._enqueue_counter += len(files)
        self.logger.info(f"Indexed {self._enqueue_counter} files")
        self.db.bulk_insert_file_internal(path, files, part_b=not part_a, index=dir_index)

        # Recurse through the directories
        while len(dirs) > 0:
            d = dirs.pop()
            self.__recursive_index(path=d,
                                   part_a=part_a,
                                   ignore_thumbnail=ignore_thumbnail,
                                   dir_count=dir_count + len(dirs))

    # ==================================================================================================================
    # Multiprocessing Common
    # ==================================================================================================================

    def multiprocessing_preamble(self, prefill: Callable, first_loop: bool = False):
        """
        Set up the multiprocessing environment
        """
        # reset counters
        self.exit_counter = 0
        if first_loop:
            self.cmd_queue = mp.Queue(maxsize=self.config.batch_size_max_fl)
        else:
            self.cmd_queue = mp.Queue()

        self.result_queue = mp.Queue()

        # Prefill the command queue
        prefill()

        # Create Worker Objects
        if first_loop:
            workers = []
            for i in range(self.config.first_loop.cpu_proc):
                workers.append(FirstLoopWorker(
                    identifier=i,
                    compress=self.config.first_loop.compress,
                    do_hash=self.config.first_loop.compute_hash,
                    target_size=(self.config.compression_target, self.config.compression_target),
                    cmd_queue=self.cmd_queue,
                    res_queue=self.result_queue,
                    log_queue=self.logging_queue,
                    shift_amount=self.config.first_loop.shift_amount,
                    log_level=self.config.log_level_children,
                    hash_fn=self.hash_fn,
                    thumb_dir=self.config.thumb_dir,
                    timeout=self.config.child_proc_timeout,
                    do_rot=self.config.rotate))

            self.handles = [mp.Process(target=w.main) for w in workers]
        else:
            workers = []
            if self.cpu_diff is None:
                self.cpu_diff = lambda ia, ib, dr: imgp.compute_image_diff(image_a=ia,
                                                                           image_b=ib,
                                                                           use_gpu=False,
                                                                           do_rot=dr)

            if self.config.second_loop.gpu_proc > 0 and self.gpu_diff is None:
                self.cpu_diff = lambda ia, ib, dr: imgp.compute_image_diff(image_a=ia,
                                                                           image_b=ib,
                                                                           use_gpu=True,
                                                                           do_rot=dr)
            for i in range(self.config.second_loop.cpu_proc + self.config.second_loop.gpu_proc):
                workers.append(SecondLoopWorker(
                    identifier=i,
                    cmd_queue=self.cmd_queue,
                    res_queue=self.result_queue,
                    log_queue=self.logging_queue,
                    hash_short_circuit=self.config.second_loop.skip_matching_hash,
                    match_aspect_by=self.config.second_loop.match_aspect_by,
                    compare_fn=self.cpu_diff if i < self.config.second_loop.cpu_proc else self.gpu_diff,
                    target_size=(self.config.compression_target, self.config.compression_target),
                    log_level=self.config.log_level_children,
                    timeout=self.config.child_proc_timeout,
                    has_dir_b=len(self.config.part_b) > 0,
                    plot_dir=self.config.second_loop.plot_output_dir,
                    ram_cache=self.ram_cache,
                    plot_threshold=self.config.second_loop.plot_threshold,
                    make_plots=self.config.second_loop.make_diff_plots,
                    do_rot=self.config.rotate))

            self.handles = [mp.Process(target=w.main) for w in workers]

        # Start the processes
        for h in self.handles:
            h.start()

    def send_stop_signal(self):
        """
        Send the stop signal to the child processes
        """
        for _ in self.handles:
            self.cmd_queue.put(None)

    def multiprocessing_epilogue(self):
        """
        Wait for the child processes to stop and join them
        """
        one_alive = True
        timeout = 30

        # Waiting for processes to finish
        while one_alive:

            # Check liveliness of the processes
            one_alive = False
            for h in self.handles:
                if h.is_alive():
                    one_alive = True
                    break

            # Skip waiting
            if not one_alive:
                break

            # Wait until timeout
            time.sleep(1)
            timeout -= 1

            # Timeout - break out
            if timeout <= 0:
                break

        # Join the processes and kill them on timeout
        for h in self.handles:
            if timeout > 0:
                h.join()
            else:
                h.kill()
                h.join()

        # Reset the handles
        self.handles = None
        self.cmd_queue = None
        self.result_queue = None

    def generic_mp_loop(self, first_iteration: bool = True, benchmark: bool = False):
        """
        Generic Loop using multiprocessing.
        """
        enqueue_time = 0
        dequeue_time = 0
        task = "Images" if first_iteration else "Stripes"

        if first_iteration:
            bs = self.config.first_loop.batch_size \
                if self.config.first_loop.batch_size is not None else self.config.batch_size_max_fl
        else:
            bs = self.config.second_loop.batch_size

        self._enqueue_counter = 0
        self._dequeue_counter = 0
        self._last_dequeue_counter = 0

        # defining the two main functions for the loop
        submit_fn = self.submit_batch_first_loop if first_iteration else self.enqueue_batch_second_loop
        dequeue_fn = self.dequeue_results_first_loop if first_iteration else self.dequeue_second_loop_batch
        can_submit_fn = self.can_submit_first_loop if first_iteration else self.can_submit_second_loop

        # Set up the multiprocessing environment
        self.multiprocessing_preamble(submit_fn, first_loop=first_iteration)

        # ==============================================================================================================
        # Benchmarking implementation
        # ==============================================================================================================
        if benchmark:
            start = datetime.datetime.now(datetime.UTC)
            while self.run:
                # Nothing left to submit
                if can_submit_fn():
                    s = datetime.datetime.now(datetime.UTC)
                    if not submit_fn():
                        break
                    enqueue_time += (datetime.datetime.now(datetime.UTC) - s).total_seconds()

                if self._dequeue_counter > self._last_dequeue_counter + bs / 4:
                    self.logger.info(f"Enqueued: {self._enqueue_counter} {task}")
                    self.logger.info(f"Done with {self._dequeue_counter} {task}")
                    self._last_dequeue_counter = self._dequeue_counter

                # Precondition -> Two times batch-size has been submitted to the queue
                s = datetime.datetime.now(datetime.UTC)
                dequeue_fn()
                dequeue_time += (datetime.datetime.now(datetime.UTC) - s).total_seconds()
                self.commit()

            # Send the stop signal
            self.send_stop_signal()

            # waiting for pipeline to empty
            while self.exit_counter < len(self.handles):
                s = datetime.datetime.now(datetime.UTC)
                dequeue_fn(drain=True)
                dequeue_time += (datetime.datetime.now(datetime.UTC) - s).total_seconds()

                if self._dequeue_counter > self._last_dequeue_counter + bs / 4:
                    self.logger.info(f"Enqueued: {self._enqueue_counter} {task}")
                    self.logger.info(f"Done with {self._dequeue_counter} {task}")
                    self._last_dequeue_counter = self._dequeue_counter

                self.commit()

            self.commit()
            self.multiprocessing_epilogue()

            end = datetime.datetime.now(datetime.UTC)
            tsk_str = "First Loop" if first_iteration else "Second Loop"
            self.logger.debug(f"Statistics for {tsk_str}")
            self.logger.debug(f"Time Taken: {(end - start).total_seconds()}", )
            self.logger.debug(f"Enqueue Time: {enqueue_time}")
            self.logger.debug(f"Dequeue Time: {dequeue_time}", )

            return

        # ==============================================================================================================
        # Normal implementation
        # ==============================================================================================================
        while self.run:
            if can_submit_fn():
                if not submit_fn():
                    break

            if self._dequeue_counter > self._last_dequeue_counter + bs / 4:
                self.logger.info(f"Enqueued: {self._enqueue_counter} {task}")
                self.logger.info(f"Done with {self._dequeue_counter} {task}")
                self._last_dequeue_counter = self._dequeue_counter

            # Precondition -> Two times batch-size has been submitted to the queue
            dequeue_fn()
            self.commit()

        # Send the stop signal
        self.send_stop_signal()

        # waiting for pipeline to empty
        while self.exit_counter < len(self.handles):
            dequeue_fn(drain=True)

            if self._dequeue_counter > self._last_dequeue_counter + bs / 4:
                self.logger.info(f"Enqueued: {self._enqueue_counter} {task}")
                self.logger.info(f"Done with {self._dequeue_counter} {task}")
                self._last_dequeue_counter = self._dequeue_counter

            self.commit()

        self.commit()
        self.multiprocessing_epilogue()

    # ==================================================================================================================
    # First Loop
    # ==================================================================================================================

    def build_first_loop_runtime_config(self, cfg: FirstLoopConfig):
        """
        Check the configuration for the first loop

        :param cfg: The configuration to check

        :return: True if the configuration is valid and the first loop can run
        """
        if cfg.compute_hash and cfg.shift_amount == 0:
            self.logger.warning("Shift amount is 0, but hash computation is requested. "
                                "Only exact Matches will be found")

        todo = self.db.get_partition_entry_count(False) + self.db.get_partition_entry_count(True)
        rtc = FirstLoopRuntimeConfig.model_validate(cfg.model_dump())

        # We are in a case where we have less than the number of CPUs
        if todo < os.cpu_count():
            self.logger.debug("Less than the number of CPUs available. Running sequentially")
            rtc.parallel = False

        # We have less than a significant amount of batches, submission done separately
        if todo / os.cpu_count() < 40:
            self.logger.debug("Less than 40 images / cpu available. No batching")
            rtc.batch_size = None

        else:
            rtc.batch_size = min(self.config.batch_size_max_fl, int(todo / 4 / os.cpu_count()))
            self.logger.debug(f"Batch size set to: {rtc.batch_size}")

        return rtc

    def print_fs_usage(self, do_print: bool = True, verbose: bool = False) -> int:
        """
        Function used to print the amount storage used by the thumbnails.

        :param do_print: Whether to print the results to log
        :param verbose: Whether to print also info per directory
        """
        if verbose:
            a = [self.config.part_a] if isinstance(self.config.part_a, str) else self.config.part_a
            b = [self.config.part_b] if isinstance(self.config.part_b, str) else self.config.part_b
            all_dirs  = a + b

            for i in range(len(all_dirs)):
                self.logger.info("Directory: " + all_dirs[i])

                allowed = self.db.get_directory_stats(i, True)
                disallowed = self.db.get_directory_stats(i, False)
                self.logger.info(f"Allowed Files: {allowed}")
                self.logger.info(f"Disallowed Files: {disallowed}")

                dfp = allowed * self.config.compression_target * self.config.compression_target * 3
                self.logger.info(f"Disk Footprint of Directory: {sizeof_fmt(dfp)}")

        dir_a_count = self.db.get_partition_entry_count(part_b=False, only_allowed=False)
        dir_a_allowed = self.db.get_partition_entry_count(part_b=False, only_allowed=True)
        dir_b_count = self.db.get_partition_entry_count(part_b=True, only_allowed=False)
        dir_b_allowed = self.db.get_partition_entry_count(part_b=True, only_allowed=True)

        if do_print:
            self.logger.info(f"Entries in Partition A: {dir_a_count}")
            self.logger.info(f"Allowed Entries in Partition A: {dir_a_allowed}")

        if dir_b_count > 0 and do_print:
            self.logger.info(f"Entries in Partition B: {dir_b_count}")
            self.logger.info(f"Allowed Entries in Partition B: {dir_b_allowed}")
            self.logger.info(f"Total Entries: {dir_a_count + dir_b_count}")
            self.logger.info(f"Total Allowed Entries: {dir_a_allowed + dir_b_allowed}")

        total = (dir_a_allowed + dir_b_allowed) * self.config.compression_target * self.config.compression_target * 3
        if do_print:
            self.logger.info(f"Total Storage Usage: {sizeof_fmt(total)}")

        return total

    def sequential_first_loop(self):
        """
        Run the first loop sequentially
        """
        # Update the state
        self.cmd_queue = mp.Queue()
        self.result_queue = mp.Queue()
        self.config.state = Progress.FIRST_LOOP_IN_PROGRESS
        self._enqueue_counter = 0
        self._dequeue_counter = 0
        self._last_dequeue_counter = 0

        processor = FirstLoopWorker(
            identifier=-1,
            compress=self.config.first_loop.compress,
            do_hash=self.config.first_loop.compute_hash,
            target_size=(self.config.compression_target, self.config.compression_target),
            cmd_queue=self.cmd_queue,
            res_queue=self.result_queue,
            log_queue=self.logging_queue,
            shift_amount=self.config.first_loop.shift_amount,
            log_level=self.config.log_level_children,
            hash_fn=self.hash_fn,
            thumb_dir=self.config.thumb_dir,
            timeout=self.config.child_proc_timeout)

        while self.run:
            # Get the next batch
            bs = self.config.first_loop.batch_size \
                if self.config.first_loop.batch_size is not None else self.config.batch_size_max_fl
            args = self.db.batch_of_preprocessing_args(batch_size=bs)

            # No more arguments
            if len(args) == 0:
                break

            # Process the batch
            results = []
            for a in args:
                # Process the arguments
                if self.config.first_loop.compress and self.config.first_loop.compute_hash:
                    r = processor.compress_and_hash(a)
                elif self.config.first_loop.compress:
                    r = processor.compress_only(a)
                elif self.config.first_loop.compute_hash:
                    r = processor.compute_hash(a)
                else:
                    raise ValueError("No computation requested")

                results.append(r)

            # Store the results
            self.store_batch_first_loop(results)
            self.commit()

        self.cmd_queue = None
        self.result_queue = None

        if self.run:
            self.config.state = Progress.FIRST_LOOP_DONE

            # Reset the config
            self.config.first_loop = FirstLoopRuntimeConfig.model_validate(self.config.first_loop.model_dump())
            self.commit()
            self.logger.info("Done with First Loop")
            return

        self.logger.info("Exiting First Loop after Interrupt")

    def first_loop(self, config: Union[FirstLoopConfig, FirstLoopRuntimeConfig] = None):
        """
        Run the first loop

        :param config: The configuration for the first loop
        """
        self.logger.info("Beginning First Loop")
        if not self.run:
            return

        # Set the config
        if config is not None:
            self.config.first_loop = config

        # Build runtime config if necessary
        if not isinstance(self.config.first_loop, FirstLoopRuntimeConfig):
            self.config.first_loop = self.build_first_loop_runtime_config(self.config.first_loop)

        # No computation required. Skip it.
        if not (self.config.first_loop.compress or self.config.first_loop.compute_hash):
            self.logger.info("No computation required. Skipping first loop")
            return

        # Create hash table if necessary
        if self.config.first_loop.compute_hash:
            self.db.create_hash_table_and_index()

        if self.config.state == Progress.FIRST_LOOP_IN_PROGRESS:
            self.logger.info("Resetting in progress pictures")
            self.db.reset_preprocessing()

        # Sequential First Loop requested
        if not self.config.first_loop.parallel:
            self.sequential_first_loop()
            return

        # Update the state
        self.config.state = Progress.FIRST_LOOP_IN_PROGRESS

        self.generic_mp_loop(first_iteration=True, benchmark=False)

        # Set the state if self.run is still true
        if self.run:
            self.config.state = Progress.FIRST_LOOP_DONE

            # Reset the config
            self.config.first_loop = FirstLoopConfig.model_validate(self.config.first_loop.model_dump())
            self.logger.info("Done with First Loop")
            return

        self.logger.info("Exiting First Loop after Interrupt")

    def submit_batch_first_loop(self) -> bool:
        """
        Submit up to a batch of files to the first loop
        """
        if self.config.first_loop.batch_size is not None:
            args = self.db.batch_of_preprocessing_args(batch_size=self.config.first_loop.batch_size)
        else:
            args = self.db.batch_of_preprocessing_args(batch_size=self.config.batch_size_max_fl)

        # Submit the arguments
        if self.config.first_loop.batch_size is not None:
            if len(args) == self.config.first_loop.batch_size:
                self.cmd_queue.put(args)
            else:
                for a in args:
                    self.cmd_queue.put(a)
        else:
            for a in args:
                self.cmd_queue.put(a)
        self._enqueue_counter += len(args)

        # Return whether there are more batches to submit
        return len(args) > 0

    def dequeue_results_first_loop(self, drain: bool = False):
        """
        Dequeue the results of the first loop
        """
        results = []

        while (not self.result_queue.empty()
               and (self._dequeue_counter + self.config.batch_size_max_fl * 2 < self._enqueue_counter or drain)):
            res = self.result_queue.get()

            # Handle the cases, when result is None -> indicating a process is exiting
            if res is None:
                self.exit_counter += 1
                continue

            if isinstance(res, list):
                results.extend(res)
                self._dequeue_counter += len(res)
            else:
                results.append(res)
                self._dequeue_counter += 1

        self.store_batch_first_loop(results)

    def store_batch_first_loop(self, results: List[PreprocessResult]):
        """
        Store the results of the first loop in the database
        """
        # Check the hashes, if they should be computed
        if self.config.first_loop.compute_hash:
            # Extract all hashes from the results
            hashes = []
            for res in results:
                hashes.append(res.hash_0)
                hashes.append(res.hash_90)
                hashes.append(res.hash_180)
                hashes.append(res.hash_270)

            # Put the hashes into the db
            self.db.bulk_insert_hashes(hashes)
            lookup = self.db.get_bulk_hash_lookup(set(hashes))

            # Update the hashes from string to int (based on the hash key in the db
            for res in results:
                res.hash_0 = lookup[res.hash_0]
                res.hash_90 = lookup[res.hash_90]
                res.hash_180 = lookup[res.hash_180]
                res.hash_270 = lookup[res.hash_270]

        self.db.batch_of_first_loop_results(results, has_hash=self.config.first_loop.compute_hash)

    @staticmethod
    def can_submit_first_loop():
        """
        Function determines if we can submit for first loop. Is True, because we have limited Queue Size
        """
        return True

    # ==================================================================================================================
    # Second Loop
    # ==================================================================================================================

    def can_submit_second_loop(self):
        """
        Check if we moved along far enough for us to submit more in the first loop queue.
        """
        offset = self.config.second_loop.batch_size * self.config.second_loop.preload_count
        val = self._dequeue_counter + offset >= self._enqueue_counter
        return val

    def second_loop(self, **kwargs):
        """
        Run the second loop

        # TODO docs on kwargs
        """
        self.logger.info("Beginning Second Loop")

        if not self.run:
            return

        if not isinstance(self.config.second_loop, SecondLoopRuntimeConfig):
            # Set the configuration
            if "config" in kwargs:
                self.config.second_loop = SecondLoopRuntimeConfig.model_validate(kwargs["config"])
            else:
                self.config.second_loop = self.second_loop_arg(**kwargs)

        # Check the configuration
        if not self.check_second_loop_config(self.config.second_loop):
            return

        # Need to populate the cache before the second loop workers are instantiated
        self.ram_cache = self.manager.dict()

        # Run the second loop
        self.internal_second_loop()

    def check_second_loop_config(self, cfg: Union[SecondLoopConfig, SecondLoopRuntimeConfig]):
        """
        Check if the configured parameters are actually compatible
        """
        if not isinstance(cfg, SecondLoopRuntimeConfig):
            cfg = SecondLoopRuntimeConfig.model_validate(cfg.model_dump())

        if not self.config.do_second_loop:
            return False

        if self.config.second_loop.skip_matching_hash and not self.config.first_loop.compute_hash:
            self.logger.error("Cannot skip matching hash without computing hash")
            return False

        if cfg.make_diff_plots:
            if cfg.plot_output_dir is None or cfg.plot_threshold is None:
                self.logger.error("Need plot output directory and diff threshold to make diff plots")
                return False

        if cfg.cpu_proc + cfg.gpu_proc < 1:
            self.logger.error("Need at least one process to run the second loop")
            return False

        if self.config.first_loop.compress is False:
            self.logger.error("Cannot run the second loop without compression")
            return False

        # Create the plot output directory
        if self.config.second_loop.make_diff_plots:
            if not os.path.exists(cfg.plot_output_dir):
                os.makedirs(cfg.plot_output_dir)

        return True

    def second_loop_arg(self,
                        cpu_proc: int = None,
                        gpu_proc: int = None,
                        batch_size: int = None,
                        skip_matching_hash: bool = None,
                        match_aspect_by: float = None,
                        make_diff_plots: bool = None,
                        plot_output_dir: str = None,
                        diff_threshold: float = None,
                        plot_threshold: float = None,
                        parallel: bool = None,
                        ) -> SecondLoopRuntimeConfig:
        set_plot_threshold = False

        if not self.config.first_loop.compress:
            raise ValueError("SecondLoop relies on pre compressed images from first loop")

        if make_diff_plots is not None:
            if plot_output_dir is None:
                raise ValueError("Need plot output directory and diff threshold to make diff plots")
            if plot_threshold is None:
                self.logger.info("Plot Threshold not provided, defaulting to diff_threshold")
                set_plot_threshold = True

        if cpu_proc is None:
            cpu_proc = os.cpu_count()
        if gpu_proc is None:
            gpu_proc = 0

        # One direction is constrained beyond the other
        if batch_size is None:
            if self.db.get_partition_entry_count(False) < cpu_proc + gpu_proc:
                # Very small case, we don't need full speed.
                if self.db.get_partition_entry_count(True) < cpu_proc + gpu_proc:
                    parallel = False

                batch_size = min(self.db.get_partition_entry_count(part_b=True, only_allowed=True) // 4,
                                 self.config.batch_size_max_sl)
            else:
                if len(self.config.part_b) > 0:
                    batch_size = min(self.db.get_partition_entry_count(part_b=True, only_allowed=True),
                                     self.db.get_partition_entry_count(part_b=False, only_allowed=True),
                                     self.config.batch_size_max_sl)
                else:
                    batch_size = min(self.db.get_partition_entry_count(part_b=False, only_allowed=True),
                                     self.config.batch_size_max_sl)

        args = {"cpu_proc": cpu_proc,
                "gpu_proc": gpu_proc,
                "skip_matching_hash": skip_matching_hash,
                "match_aspect_by": match_aspect_by,
                "make_diff_plots": make_diff_plots,
                "plot_output_dir": plot_output_dir,
                "diff_threshold": diff_threshold,
                "batch_size": batch_size,
                "plot_threshold": plot_threshold,
                "parallel": parallel}

        non_empty = {k: v for k, v in args.items() if v is not None}
        r = SecondLoopRuntimeConfig.model_validate(non_empty)
        if set_plot_threshold:
            r.plot_threshold = r.diff_threshold

        return r

    def internal_second_loop(self):
        """
        Set up the second loop
        """
        # Instantiate new Config
        assert isinstance(self.config.second_loop, SecondLoopRuntimeConfig), ("second loop config should be runtime "
                                                                              "config for internal_second_loop")

        # Prepare the blocks according to the config
        if len(self.config.part_b) > 0:
            self.dir_a_count = self.db.get_partition_entry_count(False)
            self.dir_b_count = self.db.get_partition_entry_count(True)
            self.blocks = build_start_blocks_ab(self.dir_a_count, self.dir_b_count, self.config.second_loop.batch_size)
            self.logger.info(f"Created Blocks for A and B, number of blocks: {len(self.blocks)}")
        else:
            self.dir_a_count = self.db.get_partition_entry_count(False)
            self.blocks = build_start_blocks_a(self.dir_a_count, self.config.second_loop.batch_size)
            self.logger.info(f"Created Blocks for A , number of blocks: {len(self.blocks)}")


        # Reset the progress if we're coming from a in progress loop.
        if self.config.state == Progress.SECOND_LOOP_IN_PROGRESS:
            self.config.second_loop.cache_index = self.config.second_loop.finished_cache_index + 1

        # We're coming regular
        if self.config.state == Progress.FIRST_LOOP_DONE:

            # Create a db backup
            self.db.create_diff_table_and_index()
            self.commit()

        if self.config.second_loop.parallel is False:
            self.sequential_second_loop()
            return

        self.config.state = Progress.SECOND_LOOP_IN_PROGRESS

        # Run the second loop
        self.generic_mp_loop(first_iteration=False, benchmark=False)

        self.ram_cache = None

        if self.run:
            self.config.state = Progress.SECOND_LOOP_DONE
            self.config.second_loop = SecondLoopConfig.model_validate(self.config.second_loop.model_dump())
            self.logger.info("Done with Second Loop")
            return

        self.logger.info("Exiting Second Loop after Interrupt")

    def sequential_second_loop(self):
        """
        Sequential implementation of the second loop
        """
        # Set the MSE function
        if self.cpu_diff is None:
            import fast_diff_py.img_processing as imgp
            self.cpu_diff = imgp.mse

        self.config.state = Progress.SECOND_LOOP_IN_PROGRESS

        # Set the counters
        self._enqueue_counter = 0
        self._dequeue_counter = 0
        self._last_dequeue_counter = 0

        # Set up the worker
        self.cmd_queue = mp.Queue()
        self.result_queue = mp.Queue()
        self.ram_cache = {}

        slw = SecondLoopWorker(
            identifier=1,
            cmd_queue=self.cmd_queue,
            res_queue=self.result_queue,
            log_queue=self.logging_queue,
            compare_fn=self.cpu_diff,
            target_size=(self.config.compression_target, self.config.compression_target),
            has_dir_b=len(self.config.part_b) > 0,
            ram_cache=self.ram_cache,
            plot_dir=self.config.second_loop.plot_output_dir,
            hash_short_circuit=self.config.second_loop.skip_matching_hash,
            match_aspect_by=self.config.second_loop.match_aspect_by,
            plot_threshold=self.config.second_loop.plot_threshold,
            log_level=self.config.log_level_children,
            timeout=self.config.child_proc_timeout,
            make_plots=self.config.second_loop.make_diff_plots)

        while self.run:
            # Get the next batch
            args = self.enqueue_batch_second_loop(submit=False)

            # Done?
            if not args or len(args) == 0:
                break

            # Process the batch
            results = [slw.process_batch_thumb(a) for a in args]

            # Update count
            self._enqueue_counter += len(args)
            self._dequeue_counter += len(args)

            # Update info
            self.logger.info(f"Done with {self._dequeue_counter} Pairs")

            # Store the results
            # Update the progress dict
            success = []
            error = []

            for res in results:
                self.block_progress_dict[res.cache_key][res.x] = True

                self._dequeue_counter += 1
                success.extend(res.success)
                error.extend(res.errors)

            success = list(filter(lambda x: x[3] < self.config.second_loop.diff_threshold, success))

            if not self.config.second_loop.keep_non_matching_aspects:
                success = list(filter(lambda x: x[2] != 3, success))

            self.db.bulk_insert_diff_success(success)
            self.db.bulk_insert_diff_error(error)

            self.prune_cache_batch()
            self.commit()

        if self.run:
            self.config.state = Progress.SECOND_LOOP_DONE
            self.config.second_loop = SecondLoopConfig.model_validate(self.config.second_loop.model_dump())
            self.logger.info("Done with Second Loop")
        else:
            self.logger.info("Exiting Second Loop after Interrupt")

        self.cmd_queue = None
        self.result_queue = None
        self.ram_cache = None
        self.commit()

    # ==================================================================================================================
    # Second Loop Cache Functions
    # ==================================================================================================================

    def __build_thumb_cache(self, l_x: int, l_y: int, s_x: int, s_y: int):
        """
        Build the thumbnail cache for cases when we're using ram cache
        """
        # Using ram cache, we need to prepare the caches
        assert self.config.first_loop.compress, "Precondition for building thumbnail cache not met"

        # check we're on the diagonal
        if l_x == l_y:

            # Perform sanity check
            if not s_x == s_y:
                raise ValueError("The block is not a square")

            cache = ImageCache(offset=l_x,
                               size=s_x,
                               img_shape=(self.config.compression_target, self.config.compression_target, 3))

            # Load the cache
            cache.logger = self.logger
            cache.fill_thumbnails(thumbnail_dir=self.config.thumb_dir)
            cache.logger = None

            # Create the x-y cache object
            bc = BatchCache(x=cache, y=cache)

        else:
            # We're not on the diagonal
            x = ImageCache(offset=l_x,
                           size=s_x,
                           img_shape=(self.config.compression_target, self.config.compression_target, 3))

            y = ImageCache(offset=l_y,
                           size=s_y,
                           img_shape=(self.config.compression_target, self.config.compression_target, 3))

            y.logger = x.logger = self.logger

            # Load the cache
            x.fill_thumbnails(thumbnail_dir=self.config.thumb_dir)
            y.fill_thumbnails(thumbnail_dir=self.config.thumb_dir)

            y.logger = x.logger = None

            # Create the x-y cache object
            bc = BatchCache(x=x, y=y)

        # Prep the block progress dict
        bp = {i + l_x: False for i in range(s_x)}
        self.block_progress_dict[self.config.second_loop.cache_index] = bp

        self.logger.info(f"Created Cache with key: {self.config.second_loop.cache_index}")

        ci = self.config.second_loop.cache_index
        self.ram_cache[ci] = pickle.dumps(bc)
        print("Added cache")

    def prune_cache_batch(self):
        """
        Go through the ram cache and remove the cache who's results are complete.
        """
        # Guard since we're min doesn't like empty lists
        if len(self.ram_cache.keys()) == 0:
            return

        lowest_key = min(self.ram_cache.keys())

        # Check if all keys in the block progress dict are True
        if all(self.block_progress_dict[lowest_key].values()):
            self.logger.info(f"Pruning cache key: {lowest_key}")
            self.ram_cache.pop(lowest_key)
            self.block_progress_dict.pop(lowest_key)
            self.config.second_loop.finished_cache_index = lowest_key

    # ==================================================================================================================
    # Build Second Loop Args
    # ==================================================================================================================

    def enqueue_batch_second_loop(self, submit: bool = True):
        """
        Enqueue a batch of second loop arguments
        """
        # Get the start key for the cache block we need to look at
        start_key = self.config.second_loop.cache_index

        if len(self.blocks) <= start_key:
            return False

        block = self.blocks[start_key]

        # Case when we have a dir_b
        px, hx, ax, kx = self.db.get_rows_directory(start=block.x,
                                                    batch_size=self.config.second_loop.batch_size,
                                                    part_b=False,
                                                    do_hash=self.config.second_loop.skip_matching_hash,
                                                    aspect=self.config.second_loop.match_aspect_by is not None,
                                                    path=self.config.second_loop.make_diff_plots)

        py, hy, ay, ky = self.db.get_rows_directory(start=block.y,
                                                    batch_size=self.config.second_loop.batch_size,
                                                    part_b=len(self.config.part_b) > 0,
                                                    do_hash=self.config.second_loop.skip_matching_hash,
                                                    aspect=self.config.second_loop.match_aspect_by is not None,
                                                    path=self.config.second_loop.make_diff_plots)

        # Build the ram_cache
        self.__build_thumb_cache(l_x=kx[0], l_y=ky[0], s_x=len(kx), s_y=len(ky))

        # Submit the block
        args = []
        for i in range(len(kx)):
            tfo = SecondLoopArgs(x=kx[i],
                                 y=ky[0],
                                 y_batch=len(ky),
                                 x_path=px[i] if len(px) == len(kx) else None,
                                 y_path=py if len(py) > 0 else None,
                                 x_hashes=hx[i] if len(hx) == len(kx) else None,
                                 y_hashes=hy if len(hy) > 0 else None,
                                 x_size=ax[i] if len(ax) == len(kx) else None,
                                 y_size=ay if len(ay) > 0 else None,
                                 cache_key=self.config.second_loop.cache_index
                                 )
            if not submit:
                args.append(tfo)
            else:
                self.cmd_queue.put(tfo)

        # Update variables
        self._enqueue_counter += len(kx)
        self.config.second_loop.cache_index = start_key + 1

        # Handle the return value
        if not submit:
            return args

        return True

    def dequeue_second_loop_batch(self, drain: bool = False):
        """
        Dequeue the results of second loop.

        :param drain: Whether to drain the queue (disregard the diff between the enqueue and dequeue counters)

        """
        success: List[Tuple[int, int, int, float]] = []
        error: List[Tuple[int, int, str]] = []

        offset = self.config.second_loop.batch_size * self.config.second_loop.preload_count

        while (not self.result_queue.empty()
               and (self._dequeue_counter + offset < self._enqueue_counter
                    or drain)):
            res: Union[SecondLoopResults, None] = self.result_queue.get()

            # Handle the cases, when result is None -> indicating a process is exiting
            if res is None:
                self.exit_counter += 1
                continue

            # Update the progress dict
            self.block_progress_dict[res.cache_key][res.x] = True

            self._dequeue_counter += 1
            success.extend(res.success)
            error.extend(res.errors)

        success = list(filter(lambda x: x[3] < self.config.second_loop.diff_threshold, success))

        if not self.config.second_loop.keep_non_matching_aspects:
            success = list(filter(lambda x: x[2] != 3, success))

        self.db.bulk_insert_diff_success(success)
        self.db.bulk_insert_diff_error(error)

        self.prune_cache_batch()