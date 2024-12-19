# Fast Diff Py

This is a reimplementation of the original FastDiffPy (`fast-diff-py 0.2.3`) project. However, since first 
implementation was barely any faster than the naive approach, this one is made with the focus of _actually_ being fast. 

At this moment, the `dif.py` provides an almost perfect replica of [Duplicate-Image-Finder](https://github.com/elisemercury/Duplicate-Image-Finder). 
The functionality of searching duplicates, is matched completely. Because of the reimplementation, some auxiliary 
features aren't implemented (for example it doesn't make sense storing a start and end datetime if the process can be 
interrupted)

Built with Python3.12


### Contributing
If you run into bugs or want to request features. Please open an issue. If you want to contribute to the source code, 
fork the repo, make your modifications and create a pull request. 

### Differences to the original dif.py:
- The `mse` is computed per pixel. The original also considers the color channels.
- difpy allows you to pass both `-d` and `-mv` and encounters an error if both is passed. This implementation allows 
either or and raises a `ValueError` if both are passed.
- This implementation warns you in case you pass `-sd` and not `-d` (Silent delete but not deleting)
- `-la` Lazy performs first hashes of the images. If the hash matches, images are considered to be identical, only the 
vertical and horizontal size are considered. The original `difpy` also checks the number of color channels.
- `-ch` Chunksize only overrides the `batch_size` of the second loop in FastDifPy not the `batch_size` of the first loop.
- `-p` Show Progress is used to show debug information.
- The `duration:start` and `duration:end` values in the `stats.json` are None since it doesn't make sense recording 
those with an interruptible implementation.
- The `invalid_files:logs` contain both the errors encountered while compressing all the files to a predefined size 
and errors encountered while comparing.

### Features of FastDifPy:
- `Progress recovery` - The process can be interrupted and resumed at a later time. Also, the reimplementation of 
`dif.py` is capable of that.
- `Limited RAM Footprint` - The images are first compressed and stored onto the file system. The main process then 
subsequently loads all the images within a block and then schedules them to be compared by the worker processes
- `DB Backend` - An `SQLite` DB is used to store all things. This helps with the small memory footprint as well as 
allows the storing of enormous datasets.
- `Extendable with user defined functions` - The hash function as well as the two compare functions can be overwritten 
by the user. It is also possible to circumvent the integrated indexer and pass `FastDiffPy` a list of files directly. 
Refer to the [User Extension Section](#User Extensions)
- `GPU Support` - The GPU can be used. For now, only the mse computation is done on GPU. 
`FEATURE`: Later Implementation will also move the image cache entirely onto the gpu leading to reduced memory traffic.
- `Highly Customizable with Tunables` - FastDifPy has extensive configuration options. 
Refer to the [Configuration Section](#Configuration).
- `Samll DB Queries` - All DB Queries which return large responses are implemented with Iterators to reduce the 
Memory Footprint.


### Usage:
As a quick start, you can also use the `main.py` which contains the basics to compute the dif of partitions. 

A Real Usage Example:

```python
from fast_diff_py import FastDifPy, FirstLoopConfig, SecondLoopConfig, Config

# Build the configuration.
flc = FirstLoopConfig(compute_hash=True)
slc = SecondLoopConfig(skip_matching_hash=True, match_aspect_by=0, keep_non_matching_aspects=False)
a = "/home/alisot2000/Desktop/test-dirs/dir_a/"
b = "/home/alisot2000/Desktop/test-dirs/dir_c/"
cfg = Config(part_a=[a], part_b=b, second_loop=slc, first_loop=flc)

# Run the program
fdo = FastDifPy(config=cfg, purge=True)
fdo.full_index()
fdo.first_loop()
fdo.second_loop()
fdo.commit()

print("="*120)
for c in fdo.get_diff_clusters(matching_hash=True):
    print(c)
print("="*120)
for c in fdo.get_diff_clusters(matching_hash=True, dir_a=False):
    print(c)

# Remove the intermediates but retain the db for later inspection.
fdo.config.delete_thumb = False
fdo.config.retain_progress = False
fdo.commit()
fdo.cleanup()
```

If you're not happy with the way the indexing is handled, you can use the `FastDiffPy.populate_partition`

**Database Functions:**
- The Database contains functions to get the numbers of clusters of duplicates 
(both from the hash table and the diff table)`get_hash_cluster_count` and `get_cluster_count`.
- To get all clusters, use the `get_all_cluster` or `get_all_hash_clusters`
- To get a specific cluster use `get_ith_diff_cluster` or `get_ith_hash_cluster`
- If the db is too large, you can remove paris which have a diff greater than some threshold with `drop_diff`. 
- The size of the `dif` table can be retrieved using `get_pair_count_diff`.
- You can get the errors from the `dif` and `directory` using `get_directory_errors` and `get_dif_errors` or the 
disallowed files from the directory table with `get_directory_disallowed`
- Lastly to get the paris of paths with a delta, use the `get_duplicate_pairs`


### Configuration
`FastDiffPy` can be configured using five different objects: 
`Config`, `FirstLoopConfig`, `FirstLoopRuntimeConfig`, `SecondLoopConfig`, `SecondLoopRuntimeConfig`
The Configuration is implemented using Pydantic. 
The `config.py` contains extensive documentation in the description fields.

##### Config
- `part_a` - The first partition of directories. If no `part_b` is provided. The comparison is performed within the `part_a`
- `part_b` - The second partition. If it is provided all files from `part_a` are compared to the files within `part_b`
- `recursive` - All paths provided in the two partitions are searched recursively by default.
Otherwise only that directory is searched.
- `rotate` - Images are rotated for both the comparison and for hashing. Can be disabled with this option.
- `ignore_names` - Names of files or directories to be ignored. 
- `ignore_paths` - All filepaths that have a prefix defined in this list will be ignored
- `allowed_file_extensions` - Override if you want only a specific set of file extensions to be indexed. Keep the dot so `.png`
- `db_path` - File Path to the associated DB
- `config_path` - Path to where this config object should be stored
- `thumb_dir` - Path to where the compressed images are stored. 
- `first_loop` - Config specific for the first loop. Can be a `FirstLoopConfig` or a `FirstLoopRuntimeConfig`
- `second_loop` - Config specific for the second loop. Can be a `SecondLoopConfig` or a `SecondLoopRuntimeConfig`
- `do_second_loop` - Only run the first loop. Don't execute the second loop.
- `retain_progress` - Store the Config to in the `config_path`. If set to `False`, `cleanup` will remove the config if 
it was written previously.
- `delete_db` - Delete the DB if the `cleanup` method of the `FastDiffPy` is called
- `delete_thumb` - Delete the thumbnail directory if the `cleanup` method of the `FastDiffPy` is called. 
**Config Tunables and State Attributes**: These attributes are needed to recover the progress or can be used to tune 
the performance of `FastDiffPy` 
- `compression_target` - Size to which all the images get compressed down.
- `dir_index_lookup` - The Database contains `dir_index` for each file. This index corresponds to the root path from 
which the index process discovered the file. The root path can be recovered using this lookup.
- `partition_swapped` - For performance reasons it must hold: `size(partition_a) < size(partition_b)` to achieve this, 
the db is reconstructed once the indexing is completed. If during that process, the partitions need to be exchanged, 
this flag is set.
- `dir_index_elapsed` - Once indexing is completed, this will contain the total number of seconds spent indexing.
- `batch_size_dir` - The indexed files are stored im RAM once more than this batch size of files are indexed, the files 
are written to the db.
- `batch_size_max_fl` - This is a tunable. It sets the number of images that are sent to a compressing child process. 
If this number is small, there's more stalling for child processes trying to acquire the read lock of the Task Queue 
to get a new task. The higher the number of processors you have, the higher this number should be. `100` was working 
nicely with `16` cores and a dataset of about `8k` images.
- `batch_size_max_sl` - Set the maximum block size of the second loop. A block in the second loop is up to 
`batch_size_max_sl` images from `partition_a` and another `batch_size_max_sl` from the second partition (partition_b 
if provided else partition_a). The higher this number, the higher the potential imbalance if you end up with towards 
the end of the process. The way the tasks are scheduled, the bigger tasks are scheduled first and the smaller ones 
later. This should ensure an even usage of the CPU resources if no short cuts are sued. 
- `log_level` - Set the log level of the FastDiffPy Object.
- `log_level_children` - Set the log level of the child processes.
- `state` - Contains an enum that keeps track of where the Process is currently at.
- `cli_args` - In case of progress recovery, the cli args are preserved in this attribute.
- `child_proc_timeout` - To prevent stalling processes, if a child process doesn't receive a new task within this 
amount of seconds, it will exit on its own.

##### FirstLoopConfig:
- `compress` - Option to disable the generation of thumbnails. Can be used if only hashes are supposed to be calculated. 
If this is set to False, the second loop will fail because not thumbnails were found.
- `compute_hash` - Option to compute hashes of the compressed images.
- `shift_amount` - In order to encompass a larger number of images, the RGB values in the image tensors can be right or 
left shifted. Leading either to a matching prefix or suffix that all images need to have. Can also be set to `0` for 
exact matches. Range [-7, 7]
- `parallel` - Go back to naive approach using a single cpu core.
**Config State Attributes**
- `elapsed_seconds` - Seconds used to execute the first loop.

##### FirstLoopRuntimeConfig:
Before the First Loop is executed, the `first_loop` config will be converted with defaults to a
`FirstLoopRuntimeConfig`. The `first_loop` function of the `FastDiffPy` object also provides an argument to overwrite 
the config.
- `batch_size` - Batch size used for the FirstLoop. Can be set to zero, then each image is submitted on it's own. 
- `cpu_proc` - Compressing relies on `open-cv`. Since a GPU support requires you to compile open-cv yourself, there's now GPU version at the moment.
**Config State Attributes**
- `start_dt` - Used to compute the `elapsed_seconds` once the first loop is done.

##### SecondLoopConfig:
- `skip_matching_hash` - Tunable: If one of the hashes between the two images to compare matches, the image are 
considered identical. 
- `match_aspect_by` - Either matches the image size in vertical and horizontal direction or uses computes the aspect 
ratio of each image (either w/h or h/w for the fraction to be `>= 1`). Images them must satisfy a * `match_aspect_by`
- `make_diff_plots` - For former `difpy` compatibility, a plot of two matching images can be made. If you set this 
variable, you must also set `plot_output_dir`
- `plot_output_dir`- Directory where plots are stored.
- `plot_threshold` - Threshold below which plots are made. Defaults to `diff_threshold`.
- `parallel` - Use naive sequential implementation.
- `batch_size` - The batch size is set as `min(size(part_a), size(part_b), batch_size_max_sl)` with `batch_size_max_sl`
defaulting to `os.cpu_count() * 250` this has proven to be a useful size so far. 
- `diff_threshold` - Threshold below a pair of images is considered to be a duplicate. To allow support for enormous 
datasets, only pairs which have a delta of less or equal than `diff_threshold` are stored in the db (besides errors.)
- `gpu_proc` - Number of GPU processes to spawn. Since this is experimental and not really that fast. It defaults to 0 
at the moment.
- `cpu_proc`- Number of CPU workers to spawn for computing the mse. Defaults to `os.cpu_count()`
- `keep_non_matching_aspects` - Used for debugging purposes - Retains the pairs of images deemed incomparable based on 
their size or aspect ratios.
- `preload_count` Number of Caches to prepare at any given time. At least 2 must be present at all times, More than 
4 will only increase the time it takes to drain the queue if you want to interrupt the process midway.
- `elapsed_seconds` - Once the second loop completes, it will contain the number of second the second loop took.

##### SecondLoopRuntimeConfig:
Before the Second Loop is executed, the `second_loopo` config will be converted with defaults to a
`SecondoLoopRuntimeConfig`. The `second_loop` function of the `FastDiffPy` object also provides an argument to overwrite 
the config.
- `cache_index` - Index of the next cache to be filled. (Uses the `blocks` attribute of the `FastDiffPy` object to 
determine which images to load)
- `finished_cache_index` - Highest cache key which was removed from RAM because all paris within that cache were computed.
- `start_dt` - Used to compute the `elapsed_seconds` once the second loop is done.


### User Extension:
You as the user have the ability to provide your own functions to the FastDiffPy object.
The functions you can provde are the following:
- `hash_fn` Can either be a function taking an `np.ndarray` and outputting a hash string or (for backwards 
compatibility - tho this will be deprecated soon) a function taking a `path` to a file for which it returns a hash string.
- `cpu_diff` - CPU implementation of delta computation between the images. The function should return a `float >= 0.0`.
The function takes two `np.ndarray` and a `bool`. If the bool is set to true rotations of the images _should_ be 
computed. Otherwise, the two image tensors are to be compared as is.
- `gpu_diff` - Function which computes the delta on a GPU. It should be obvious but if you provide the same function as 
for `cpu_diff` and instantiate also processes for the gpu, you won't see any performance improvements. 
- `gpu_worker_class` **NOT IMPLEMENTED**: If you provide a GPU worker, this will be favored over the `gpu_diff`. 
Providing a GPU Worker allows for more optimizations and computations to be made on the GPU, leading to higher
performance.

You can also provide your own subclass of the `SQLiteDB`. For that you need to overwrite the `db_inst` class variable of 
the FastDiffPy Object.

Additionally, if you do not set `delete_db` the db will remain after the `cleanup` of the FastDiffPy object, 
allowing you to connect to it later on to examine the duplicates you've found. This can be useful especially for large 
datasets.

### Appendix:
As I've already mentioned. Sometimes the problem is already solved. So before you start implementing a high performing 
deduplicator, consider looking at these two projects.

##### Utility Scripts:
In the repo in the `scripts/` directory, you find the [duplicate_generator.py](scripts/duplicate_generator.py). 
This allows you to generate duplicates from a given dataset. This script was used in conjunction with the 
[IMDB Dataset](https://data.vision.ee.ethz.ch/cvl/rrothe/imdb-wiki/?ref=hackernoon.com) to generate test cases for to 
benchmark different implementations and configurations of this Package.

All scripts in this file are available in the `scripts/` directory. 

##### Benchmarking:
TODO: Run the benchmarks.

##### Table Definitions:
**Directory Table**
```sqlite
CREATE TABLE directory (
    key INTEGER PRIMARY KEY AUTOINCREMENT, 
    path TEXT, --path including the filename
    filename TEXT, 
    error TEXT, 
    success INTEGER DEFAULT -1 CHECK (directory.success IN (-2, -1, 0, 1)), -- -1 not computed, -2 scheduled, 0 error, 1 success
    px INTEGER DEFAULT -1 CHECK (directory.px >= -1), 
    py INTEGER DEFAULT -1 CHECK (directory.py >= -1), 
    allowed INTEGER DEFAULT 0 CHECK (directory.allowed IN (0, 1)), -- allowed files <=> 1
    file_size INTEGER DEFAULT -1 CHECK (directory.file_size >= -1), 
    created REAL DEFAULT -1 CHECK (directory.created >= -1), -- unix timestamp 
    dir_index INTEGER DEFAULT -1 CHECK (directory.dir_index >= -1), -- refer  to dir_index_lookup in the config
    part_b INTEGER DEFAULT 0 CHECK (directory.part_b IN (0, 1)), -- whether the file belongs to partition b
    hash_0 INTEGER, -- key from hash table of the associated hash
    hash_90 INTEGER, -- dito
    hash_180 INTEGER, -- dito
    hash_270 INTEGER, -- dito
    deleted INTEGER DEFAULT 0 CHECK (directory.deleted IN (0, 1)), -- flag needed for gui 
    UNIQUE (path, part_b));
```

**Hash Table**
```sqlite
CREATE TABLE hash_table (
    key INTEGER PRIMARY KEY AUTOINCREMENT , 
    hash TEXT UNIQUE , -- hash string
    count INTEGER CHECK (hash_table.count >= 0)) -- number of occurrences of that hash
```

**Diff Table**
```sqlite
CREATE TABLE dif_table (
    key INTEGER PRIMARY KEY AUTOINCREMENT, 
    key_a INTEGER NOT NULL, 
    key_b INTEGER NOT NULL, 
    dif REAL CHECK (dif_table.dif >= -1) DEFAULT -1, -- -1 also an indication of error.
    success INT CHECK (dif_table.success IN (0, 1, 2, 3)) DEFAULT -1, -- 0 error, 1 success, 2, matching hash 3, matching aspect
    error TEXT, 
    UNIQUE (key_a, key_b)) 
```

##### Similar Projects:
- [Duplicate-Image-Finder](https://github.com/elisemercury/Duplicate-Image-Finder) (the project this is based on)
- [imagededup](https://github.com/idealo/imagededup)
- [Benchmark Dataset](https://data.vision.ee.ethz.ch/cvl/rrothe/imdb-wiki/?ref=hackernoon.com)