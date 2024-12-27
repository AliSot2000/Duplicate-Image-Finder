#!/bin/bash

source /home/alisot2000/Documents/05_Programms/python_envs/poetry_env/bin/activate

export PYTHONPATH="/home/alisot2000/Documents/01_ReposNCode/Fast-Image-Deduplicator/src"
export LD_LIBRARY_PATH="/usr/local/cuda/lib64"

## 64 gpu
poetry run python3 benchmark_gpu.py \
    -p 2  \
    -a 1 \
    -u /home//alisot2000/Desktop/Datasets/workbench_2k/dir_a/ \
    -v /home/alisot2000/Desktop/Datasets/workbench_2k/dir_b/ \
    -s 64 \
    -t /home/alisot2000/Documents/01_ReposNCode/Fast-Image-Deduplicator/benchmark_gpu_64.json

# 64 cpu
poetry run python3 benchmark_deduplicate.py \
    -p 16 \
    -u /home//alisot2000/Desktop/Datasets/workbench_2k/dir_a/ \
    -v /home/alisot2000/Desktop/Datasets/workbench_2k/dir_b/ \
    -a 1 \
    -s 64 \
    -t /home/alisot2000/Documents/01_ReposNCode/Fast-Image-Deduplicator/benchmark_cpu_64.json

# 128 gpu
poetry run python3 benchmark_gpu.py \
    -p 2  \
    -u /home//alisot2000/Desktop/Datasets/workbench_2k/dir_a/ \
    -v /home/alisot2000/Desktop/Datasets/workbench_2k/dir_b/ \
    -s 128 \
    -a 1 \
    -t /home/alisot2000/Documents/01_ReposNCode/Fast-Image-Deduplicator/benchmark_gpu_128.json

# 128 cpu
poetry run python3 benchmark_deduplicate.py \
    -p 16 \
    -u /home//alisot2000/Desktop/Datasets/workbench_2k/dir_a/ \
    -v /home/alisot2000/Desktop/Datasets/workbench_2k/dir_b/ \
    -a 1 \
    -s 128 \
    -t /home/alisot2000/Documents/01_ReposNCode/Fast-Image-Deduplicator/benchmark_cpu_128.json

# 256 gpu
poetry run python3 benchmark_gpu.py \
    -p 4 \
    -u /home//alisot2000/Desktop/Datasets/workbench_2k/dir_a/ \
    -v /home/alisot2000/Desktop/Datasets/workbench_2k/dir_b/ \
    -s 256 \
    -a 1 \
    -t /home/alisot2000/Documents/01_ReposNCode/Fast-Image-Deduplicator/benchmark_gpu_256.json

# 256 cpu
poetry run python3 benchmark_deduplicate.py \
    -p 16 \
    -u /home//alisot2000/Desktop/Datasets/workbench_2k/dir_a/ \
    -v /home/alisot2000/Desktop/Datasets/workbench_2k/dir_b/ \
    -a 1 \
    -s 256 \
    -t /home/alisot2000/Documents/01_ReposNCode/Fast-Image-Deduplicator/benchmark_cpu_256.json

# 256 gpu (test with SecondLoopGPUWorker)
poetry run python3 benchmark_gpu.py \
    -p 4 \
    -u /home//alisot2000/Desktop/Datasets/workbench_2k/dir_a/ \
    -v /home/alisot2000/Desktop/Datasets/workbench_2k/dir_b/ \
    -s 256 \
    -a 1 \
    -t /home/alisot2000/Documents/01_ReposNCode/Fast-Image-Deduplicator/benchmark_gpu_256_worker.json