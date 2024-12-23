#!/bin/bash

echo "Running scaling benchmark"

source /home/alisot2000/Documents/01_ReposNCode/Fast-Image-Deduplicator/lin_venv/bin/activate
export PYTHONPATH="/home/alisot2000/Documents/01_ReposNCode/Fast-Image-Deduplicator/src"


/home/alisot2000/Documents/01_ReposNCode/Fast-Image-Deduplicator/lin_venv/bin/python3 benchmark_scaling.py \
    -a 1 \
    -u \
    /home/alisot2000/Desktop/workbench_2k/dir_a \
    /home/alisot2000/Desktop/workbench_4k/dir_a \
    /home/alisot2000/Desktop/workbench_8k/dir_a \
    /home/alisot2000/Desktop/workbench_16k/dir_a \
    /home/alisot2000/Desktop/workbench_32k/dir_a \
    -v \
    /home/alisot2000/Desktop/workbench_2k/dir_b \
    /home/alisot2000/Desktop/workbench_4k/dir_b \
    /home/alisot2000/Desktop/workbench_8k/dir_b \
    /home/alisot2000/Desktop/workbench_16k/dir_b \
    /home/alisot2000/Desktop/workbench_32k/dir_b
