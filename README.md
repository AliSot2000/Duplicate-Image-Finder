# Fast Diff Py

This is a reimplementation of the original FastDiffPy (`fast-diff-py 0.2.3`) project. However, since first 
implementation was barely any faster than the naive approach, this one is made with the focus of _actually_ being fast. 

At this moment, the `dif.py` provides an almost perfect replica of [Duplicate-Image-Finder](https://github.com/elisemercury/Duplicate-Image-Finder). 
The functionality of searching duplicates, is matched completely. Because of the reimplementation, some auxiliary 
features aren't implemented (for example it doesn't make sense storing a start and end datetime if the process can be 
interrupted)

Built with `Python3.12`


### Contributing
If you run into bugs or want to request features. Please open an issue.    
If you want to contribute to the source code:
- Fork the repo, 
- make your modifications and 
- create a pull request. 

### Differences to the original difPy:
- The `mse` is computed per pixel. The original also considers the color channels. So for the threshold of FastDiffPy 
is equal to 3x the threshold of difPy.
- difPy allows you to pass both `-d` and `-mv` and encounters an error if both is passed. This implementation allows 
either or and raises a `ValueError` if both are passed.
- This implementation warns you in case you pass `-sd` and not `-d` (Silent delete but not deleting)
- `-la` Lazy performs first hashes of the images. If the hash matches, images are considered to be identical. 
Afterward, only the x and y size are considered and not the number of color channels like difPy. If the size doesn't 
match, images won't be considered for a match.
- `-ch` Chunksize only overrides the `batch_size` of the second loop in FastDifPy not the `batch_size` of the first loop.
- `-p` Show Progress is used to show debug information.
- The `*.duration.start` and `*duration.end` values in the `stats.json` are `None` since it doesn't make sense recording 
those with an interruptible implementation.
- The `invalid_files.logs` contain both the errors encountered while compressing all the files to a predefined size 
and errors encountered while comparing.

### Features of FastDifPy:
- `Progress Recovery` - The process can be interrupted and resumed at a later time. Also, the reimplementation of the
`dif.py` script is capable of that.
- `Limited RAM Footprint` - The images are first compressed and stored on the file system. The main process then 
subsequently loads all the images within a block and then schedules them to be compared by the worker processes
- `DB Backend` - An `SQLite` database is used to store all things. This helps with the small memory footprint as well as 
allows the storing of enormous datasets.
- `Extendable With User Defined Functions` - The hash function as well as the two compare functions can be overwritten 
by the user. It is also possible to circumvent the integrated indexer and pass FastDiffPy a list of files directly. 
Refer to the [User Extension Section](#User-Extension)
- `GPU Support` - The GPU can be used. For now, only the mse computation is done on GPU. 
- `GPU Worker` - For even higher performance, you can implement a worker that is tailored to run fully on the gpu. 
- `Highly Customizable with Tunables` - FastDifPy has extensive configuration options. 
Refer to the [Configuration Section](#Configuration).
- `Samll DB Queries` - All DB Queries which return large responses are implemented with Iterators to reduce the 
memory footprint.
- `Hash` - FastDiffPy supports deduplication via Hashes. The default hash implementation allows you to hash either the
compressed image as is (setting the `shift_amount = 0`) or compute the hash of either the pixel prefixes or suffixes. 
This can be controlled with the `shift_amount`. It shifts the bytes to the right, padding with zeros using a positive 
value or, it shifts to the left using a negative value. 

### Usage:
FastDiffPy provides two scripts:
- `difpy` which implements the cli interface present in difPy with a few discrepancies. Refer to the 
[Differences to difPy Section](#differences-to-the-original-difpy)
- `fastdiffpy` which has its own cli interface to run the deduplication process and provide the user with a SQLite 
database as a result.

You can also write your own script to suit your needs like [this](scripts/Sample.py): 

```python
from fast_diff_py import FastDifPy, FirstLoopConfig, SecondLoopConfig, Config

# Build the configuration.
flc = FirstLoopConfig(compute_hash=True)
slc = SecondLoopConfig(skip_matching_hash=True, match_aspect_by=0)
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

**Database Functions:**
- The Database contains functions to get the numbers of clusters of duplicates 
(both from the hash table and the diff table)`get_hash_cluster_count` and `get_cluster_count`.
- To get all clusters, use the `get_all_cluster` or `get_all_hash_clusters`
- To get a specific cluster use `get_ith_diff_cluster` or `get_ith_hash_cluster`
- If the db is too large, you can remove paris which have a diff greater than some threshold with `drop_diff`. 
- The size of the `dif_table` can be retrieved using `get_pair_count_diff`.
- You can get the errors from the `dif_table` and `directory` table using `get_directory_errors` and `get_dif_errors` 
or the disallowed files from the directory table with `get_directory_disallowed`
- Lastly to get the paris of paths with a delta, use the `get_duplicate_pairs`


### Configuration
FastDiffPy can be configured using five different objects:     
`Config`, `FirstLoopConfig`, `FirstLoopRuntimeConfig`, `SecondLoopConfig`, `SecondLoopRuntimeConfig`.
The Configuration is implemented using `Pydantic`. 
The `config.py` contains extensive documentation in the `description` fields.

##### Config
- `part_a` - The first partition of directories. If no `part_b` is provided. 
The comparison is performed within the `part_a`
- `part_b` - The second partition. If it is provided all files from `part_a` are compared to the files within `part_b`
- `recursive` - All paths provided in the two partitions are searched recursively by default.
Otherwise, only that directory is searched.
- `rotate` - Images are rotated for both the comparison and for hashing. Can be disabled with this option.
- `ignore_names` - Names of files or directories to be ignored. 
- `ignore_paths` - Paths to be ignored, if the path is a directory, the subtree of this directory will be ignored.
- `allowed_file_extensions` - Override if you want only a specific set of file extensions to be indexed. The list of 
extensions must retain the dot. So to only allow PNG files, do `allowed_file_extensions = ['.png']`. 
- `db_path` - File Path to the associated DB
- `config_path` - Path to where this config file needed for progress retention should be stored
- `thumb_dir` - Path to where the compressed images are stored. 
- `first_loop` - Config specific for the first loop. Can be a `FirstLoopConfig` or a `FirstLoopRuntimeConfig`
- `second_loop` - Config specific for the second loop. Can be a `SecondLoopConfig` or a `SecondLoopRuntimeConfig`
- `do_second_loop` - Only run the first loop. Don't execute the second loop. Useful if you only need hashes.
- `retain_progress` - Store the Config to in the `config_path`. If set to `False`, the `cleanup` method will remove the 
config if it was written previously.
- `delete_db` - Delete the DB if the `cleanup` method of the `FastDiffPy` is called
- `delete_thumb` - Delete the thumbnail directory if the `cleanup` method of the `FastDiffPy` is called.

**Config Tunables and State Attributes**: These attributes are needed to recover the progress or can be used to tune 
the performance of `FastDiffPy` 
- `compression_target` - Size to which all the images get compressed down.
- `dir_index_lookup` - The Database contains `dir_index` for each file. This index corresponds to the root path from 
which the index process discovered the file. The root path can be recovered using this lookup.
- `partition_swapped` - For performance reasons it must hold `size(partition_a) < size(partition_b)`. To achieve this, 
the database is reconstructed once the indexing is completed. If during that process, the partitions need to be 
exchanged, this flag is set.
- `dir_index_elapsed` - Once indexing is completed, this will contain the total number of seconds spent indexing.
- `batch_size_dir` - The indexed files are stored im RAM once more than this batch size of files are indexed, the files 
are written to the db.
- `batch_size_max_fl` - This is a tunable. It sets the number of images that are sent to a compressing child process. 
If this number is small, there's more stalling for child processes trying to acquire the read lock of the Task Queue 
to get a new task. The higher the number of processors you have, the higher this number should be. `100` was working 
nicely with `16` cores and a dataset of about `8k` images.
- `batch_size_max_sl` - Set the maximum block size of the second loop. A block in the second loop is up to 
`batch_size_max_sl` images from `partition_a` and again up to `batch_size_max_sl` from the second partition (partition_b 
if provided else partition_a). The higher this number, the higher the potential imbalance in tasks per worker. The way 
the tasks are scheduled, the bigger tasks are scheduled first and the smaller ones later (this is why partition a needs
to be smaller than partition b). This should ensure an even usage of the compute resources if no short-circuits are 
used. 
- `log_level` - Set the log level of the FastDiffPy Object. Only has an effect, if passed as the `config` argument to 
the constructor of the FastDiffPy object at the moment.
- `log_level_children` - Set the log level of the child processes.
- `state` - Contains an enum that keeps track of where the process is currently at.
- `cli_args` - In case of progress recovery, the cli args are preserved in this attribute.
- `child_proc_timeout` - As a security precaution and to prevent the most basic zombies, the child processes exit if 
they cannot get a new task from the Task Queue within the number of seconds specified here.


##### FirstLoopConfig:
- `compress` - Option to disable the generation of thumbnails. Can be used if only hashes are supposed to be calculated. 
If this is set to False, the second loop will fail because no thumbnails were found.
- `compute_hash` - Option to compute hashes of the compressed images.
- `shift_amount` - In order to encompass a larger number of images, the RGB values in the image tensors can be right or 
left shifted. Leading either to a matching prefix or suffix that all images need to have. Can also be set to `0` for 
exact matches. Range [-7, 7]
- `parallel` - Go back to naive approach using a single cpu core.
- `cpu_proc` - Compressing relies on `open-cv`. Since a GPU support requires you to compile `open-cv` yourself, there's 
no GPU version at the moment.

**Config State Attributes**
- `elapsed_seconds` - Seconds used to execute the first loop.


##### FirstLoopRuntimeConfig:
Before the First Loop is executed, the `first_loop` config will be converted with defaults to a
`FirstLoopRuntimeConfig`. The `first_loop` function of the `FastDiffPy` object also provides an argument to overwrite 
the config.
- `batch_size` - Batch size used for the FirstLoop. Can be set to zero, then each image is submitted on its own. 
**Config State Attributes**
- `start_dt` - Used to compute the `elapsed_seconds` once the first loop is done. Will be set by the `first_loop` 
function and cannot be overwritten.
- `total` - Number of files to preprocess
- `done` - Number of files preprocessed


##### SecondLoopConfig:
- `skip_matching_hash` - Tunable: If one of the hashes between the two images to compare matches, the image are 
considered identical. 
- `match_aspect_by` - Either matches the image size in vertical and horizontal direction or uses the aspect 
ratio of each image (either w/h or h/w for the fraction to be `>= 1`). Images them must satisfy 
`a_aspect_ratio * match_aspect_by > b_aspect_ratio > a_aspect_ratio / match_aspect_by` to be considered possible 
duplicates. Otherwise, they won't be compared.
- `make_diff_plots` - For former difPy compatibility, a plot of two matching images can be made. If you set this 
variable, you must also set `plot_output_dir`
- `plot_output_dir`- Directory where plots are stored.
- `plot_threshold` - Threshold below which plots are made. Defaults to `diff_threshold`.
- `parallel` - Use naive sequential implementation.
- `batch_size` - The batch size is set as `min(size(part_a) // 4, size(part_b) // 4, batch_size_max_sl)` if 
partition b is present otherwise `min(size(part_a) // 4, batch_size_max_sl)`. `batch_size_max_sl` defaulting to 
`os.cpu_count() * 250` this has proven to be a useful size so far. 
- `diff_threshold` - Threshold below a pair of images is considered to be a duplicate. **Warning:** To allow support 
for enormous datasets, only pairs which with `delta <= diff_threshold` are stored in the database (besides errors.)
- `gpu_proc` - Number of GPU processes to spawn. Since this is experimental and not really that fast. It defaults to 0 
at the moment.
- `cpu_proc`- Number of CPU workers to spawn for computing the mse. Defaults to `os.cpu_count()`
- `keep_non_matching_aspects` - Used for debugging purposes - Retains the pairs of images deemed incomparable based on 
their size or aspect ratios.
- `preload_count` Number of Caches to prepare at any given time. At least 2 must be present at all times, More than 
4 will only increase the time it takes to drain the queue if you want to interrupt the process midway.
- `elapsed_seconds` - Once the second loop completes, it will contain the number of second the second loop took.

##### SecondLoopRuntimeConfig:
Before the Second Loop is executed, the `SecondLoopConfig` will be converted with defaults to a
`SecondoLoopRuntimeConfig`. The `second_loop` function of the `FastDiffPy` object also provides an argument to overwrite 
the config.
- `cache_index` - Index of the next cache to be filled. (Uses the `blocks` attribute of the `FastDiffPy` object to 
determine which images to load)
- `finished_cache_index` - Highest cache key which was removed from RAM because all paris within that cache were computed.
- `start_dt` - Used to compute the `elapsed_seconds` once the second loop is done. Will be set by the `second_loop` 
function and cannot be overwritten.
- `total` - Number of pairs to compare
- `done` - Number of paris compared

**INFO**: The reported `cache_index` in `Created Cache with key: ...` as well as `Pruning cache key: ...` is offset by 
one compared to the config.

### Logging
FastDiffPy logs using the python `logging` library and uses `QueueHandler` and `QueueListeners` to join all logs in one 
thread. All Workers get their own logger named like `FirstLoopWorker_XXX` or `SecondLoopWorker_XXX` with `XXX` 
replacing its id. The main process has itself the logger `FastDiffPy_Main`. The Handlers both of the workers and the 
main process are cleared with each instantiation of a worker process or with each instantiation of the main object. 
All logs are written to `stdout` using a `QueueListener` which resides in `FastDiffPy.ql` this listener is also 
instantiated a new with every call to the constructor of `FastDiffPy`. If you want to capture the logs, I suggest 
adding more handlers to the `QueueListener` once the `FastDiffPy` object is instantiated. 

In order to avoid errors on exit, call the `FastDiffPy.cleanup()` method which stops the `QueueListener` process. 
`FastDiffPy.test_cleanup` stops it as well. If you are doing something beyond the extent of the available functions, 
call `FastDiffPy.qh.stop()` separately.

### User Extension
You as the user have the ability to provide your own functions to the FastDiffPy.
The functions you can provide are the following:
- `hash_fn` Can either be a function taking an `np.ndarray` and outputting a hash string or (for backwards 
compatibility - tho this will be deprecated soon) a function taking a `path` to a file for which it returns a 
hash string.
- `cpu_diff` - CPU implementation of delta computation between the images. The function should return a `float >= 0.0`.
The function takes two `np.ndarray` and a `bool`. If the bool is set to true rotations of the images _should_ be 
computed. Otherwise, the two image tensors are to be compared as is.
- `gpu_diff` - Function which computes the delta on a GPU. It should be obvious but if you provide the same function as 
for `cpu_diff` and instantiate also processes for the gpu, you won't see any performance improvements. 
- `gpu_worker_class`: This worker will be instantiated in favor of a `SecondLoopWorker` with a function that computes 
the delta on the gpu. The default `SecondLoopGPUWorker` also moves the entire cache to the GPU to minimize data
movement. However, the `compare_fn` will still be set once the second loop is instantiating its workers. So put the 
delta function you want to use in your gpu worker into the `gpu_diff` attribute of the `FastDiffPy` object. At the 
point of writing a preliminary benchmark has shown that the GPU both with a custom worker and only with the mse computed 
on the GPU is slower than the implementation using numpy. The `compression_target` was `64`. Looking at the small 
benchmark I did, the GPU certainly outperforms my CPU at a `compression_target = 256` and by the trend also above. 
Look at the [GPU Performance Section](#gpu-performance)

If you're not happy with the way the indexing is handled, you can use the `FastDiffPy.populate_partition` to provide 
a list of files which are to be inserted into partition a and partition b. If you want to use `populate_partition`, call
`FastDiffPy.index_preamble` before and `FastDiffPy.index_epilogue` once you're done

You can also provide your own subclass of the `SQLiteDB`. For that you need to overwrite the `db_inst` class variable of 
the `FastDiffPy` object.

Additionally, if you do not set `delete_db` the db will remain after the `cleanup` of the `FastDiffPy` object, 
allowing you to connect to it later on to examine the duplicates you've found. This can be useful especially for large 
datasets.

### Benchmarking:
For benchmarking, I used my Laptop with:
- 16GB RAM, 4GB Swap
- Ryzen 9 5900HS 8 Core, 16 Threads
- 1TB NVME SSD
- Nvidia RTX 3050 TI Mobile (4Gb VRAM)

From the [IMDB Dataset](https://data.vision.ee.ethz.ch/cvl/rrothe/imdb-wiki/?ref=hackernoon.com), partitions were 
generated using the [duplicate_generator.py](scripts/duplicate_generator.py) in partition mode. Datasets with sizes of 
`2000`, `4000`, `8000`, `16000` and `32000` images per partition were created for the benchmark. 

To get some sense of the speeds present, I benchmarked the `build` and `search` operation of difPy against the 
`first_loop` and `second_loop` of FastDiffPy in an isolated manner.

To get a sense of the performance, I'm looking at worst case performance. That means, no optimizations using 
image shape or no rotation. The only performance optimization I'm doing is checking equality of the two tensors. 

#### Compression Benchmarks
Both difPy and FastDiffPy compress the images in a first step from their original size to a common thumbnail size.
Due to the time it takes to run the benchmarks, I start at a minimum of 4 processes and limit the partition size to 
8000 images in place of 32000.
The benchmarks were run with [benchmark_compression.py](scripts/benchmark_compression.py)
Each benchmark was run three times for some statistical relevance and the first loop of FastDiffPy was run both with 
the computation of the hashes of the thumbnails and without.

![Compression Time vs Processes](plots/comp_time_all_vs_proc.png)

![Speedup vs Processes](plots/comp_speedup_vs_proc.png)

As can see from the plots, FastDiffPy is faster than difPy. Quite notable in the plot of the speedup is the 
impact of hyper threading on performance:    
The speedup without hash increases between 8 and 16 processes. This indicates an IO bottleneck. This supports the 
intuition, that writing the compressed thumbnails to disk is a IO bound operation. It can also observe that the 
performance is dropping when computing hashes for the thumbnails. This supports the intuition that the computation of 
the hashes takes more time than compressing and storing the image to disk. And since the hash computation is a compute 
bound task,a negative impact of hyper threading on performance can be observed.

#### Deduplication Benchmarks
Deduplication is Benchmarked using the [benchmark_deduplication.py](scripts/benchmark_deduplicate.py)

![Performance Hit due to Cache Pruning](plots/Example_Cache_Prune.png)

In Deduplication, FastDiffPy doesn't live up to its name and runs slower than difPy. This is not entirely surprising
since FastDiffPy doesn't make the assumption of infinite RAM size. This causes overhead due to maintaining a subset of 
images in RAM which need to be loaded, unloaded and copied into each process. Sadly, the shared RAM Cache also takes a 
hefty performance penalty when adding and removing blocks of images because all process synchronize for that operation
(As can be seen in the image above, the repeated and simultanuous drops in performance).
Additionally, FastDiffPy also maintains only the paris of images which have a delta less than the one specified. 
This optimization is also made to be able to deduplicate massive datasets which surpass RAM size. But the operation of
filtering and writing to the SQLite database i.e. writing to disk also costs performance.

These graphs show a possible optimization that can be made in future iterations of the Framework. At the moment,
each process takes one image from partition a and compares it against a series of images from the other partition. 
This is not optimal in the sense of cache locality. Future implementations should schedule a block of multiple images 
of partition a and partition b to the child processes. Within these blocks, the child process is then able to optimize 
for cache locality which should speedup performance by some margin. 

![Deduplication Time vs Processes](plots/dedup_all_vs_proc.png)
![Speedup Deduplication vs Processes](plots/dedup_speedup_vs_proc.png)

It is noteworthy that the performance penalty incurred by FastDiffPy is less substantial at with larger datasets. This 
points again to the strength of FastDiffPy in cases of massive datasets where the cost of maintaining a RAM cache makes 
sense.

#### Overall Performance
In a last step, I benchmarked the two `dif.py` scripts provided by difPy and FastDiffPy. The benchmark was performed
using [benchmark_scaling.py](scripts/benchmark_scaling.py). Because the last benchmark with two partitions of 32000 
images takes 6h to run, these benchmarks were only run once.

![Time Taken vs Partition Size](plots/script_size_vs_time.png)
![Time Delta vs Partition Size](plots/script_size_vs_delta.png)

Using the full scripts, a performance improvement with larger datasets can once again be observed in favor of 
FastDiffPy. It's also notable that the performance increases observed overall outstrip the ones observed in the 
[Compression Benchmark](#Compression-Benchmarks). This indicates that the already reduced number of pairs stored in the
db as well as the generation of the duplicate clusters using SQLite is more efficient than the pure python 
implementation of *difPy*. The last and most striking observation is the limits of *difPy*: 
At a size of 32000 images per partition, `difPy` runs into a RAM overflow. FastDiffPy handles that just fine because 
of the RAM cache. This being the last pointer to the strength of FastDiffPy for enormous datasets.

##### GPU Performance
The performance of the GPU wasn't explored in depth due to one benchmark with a partition size of 2000 already 
taking between an hour and two hours. The parameters of the benchmark were also changed during its execution, 
changing the number of gpu workers from 2 to 4 for the instance of a `compression_target = 256`. Additionally, 
the performance with the `SecondLoopGPUWorker` was also only measured for the `compression_target = 256`. At this size, 
the time taken to deduplicate went down from `4061.5s` to `3938.5s`. So only a very small improvement. 

![Benchmark GPU](plots/gpu_cpu_perf.png)


### Appendix:
With the previous implementation of the project, I found out later, that the goals I had were covered by other 
implementations, namely [imagededup](https://github.com/idealo/imagededup). In the meantime, 
[Duplicate-Image-Finder](https://github.com/elisemercury/Duplicate-Image-Finder) also uses multiprocessing for 
improved performance. The reason why I reimplemented FastDiffPy was because of the Database and the progress retention.

##### Utility Scripts:
In the repo in the `scripts/` directory, you find the [duplicate_generator.py](scripts/duplicate_generator.py). 
This allows you to generate duplicates from a given dataset. This script was used in conjunction with the 
[IMDB Dataset](https://data.vision.ee.ethz.ch/cvl/rrothe/imdb-wiki/?ref=hackernoon.com) to generate test cases for to 
benchmark different implementations and configurations of this Package.

All scripts mentioned in this README are available in the `scripts/` directory.

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

##### Links:
- [Duplicate-Image-Finder](https://github.com/elisemercury/Duplicate-Image-Finder) (the project this is based on)
- [imagededup](https://github.com/idealo/imagededup)
- [Benchmark Dataset](https://data.vision.ee.ethz.ch/cvl/rrothe/imdb-wiki/?ref=hackernoon.com)