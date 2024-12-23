#!/bin/bash

echo "Performing Benchmarks for 8k images."
echo "For Performance reasons, we're only checking 4, 8 and 16 Processes"

source /home/alisot2000/Documents/01_ReposNCode/Fast-Image-Deduplicator/lin_venv/bin/activate
export PYTHONPATH="/home/alisot2000/Documents/01_ReposNCode/Fast-Image-Deduplicator/src"

/home/alisot2000/Documents/01_ReposNCode/Fast-Image-Deduplicator/lin_venv/bin/python3 benchmark_compression.py \
    -w /home/alisot2000/Desktop/workbench_8k/ \
    --do_hash \
    -p 4 8 16 \
    -t /home/alisot2000/Documents/01_ReposNCode/Fast-Image-Deduplicator/benchmark_compression_8k.json

/home/alisot2000/Documents/01_ReposNCode/Fast-Image-Deduplicator/lin_venv/bin/python3 benchmark_deduplicate.py \
    -u /home/alisot2000/Desktop/workbench_8k/dir_a/ \
    -v /home/alisot2000/Desktop/workbench_8k/dir_b/ \
    -p 4 8 16 \
    -g /home/alisot2000/Documents/01_ReposNCode/Fast-Image-Deduplicator/scripts \
    -t /home/alisot2000/Documents/01_ReposNCode/Fast-Image-Deduplicator/benchmark_deduplication_8k.json


echo "DONE"
