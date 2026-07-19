"""
File operations package (incremental extraction from file_operations_manager.py).

Available slices:
- duplicate_hash — MD5 hashing for exact duplicate detection
"""

from file_ops.duplicate_hash import (
    DUPLICATE_HASH_WORKER_MIN_PATHS,
    DuplicateHashWorker,
    build_hash_groups,
    compute_file_md5,
    run_duplicate_hash_ui,
)

__all__ = [
    "DUPLICATE_HASH_WORKER_MIN_PATHS",
    "DuplicateHashWorker",
    "build_hash_groups",
    "compute_file_md5",
    "run_duplicate_hash_ui",
]
