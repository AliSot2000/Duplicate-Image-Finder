import fast_diff_py.config as cfg
from fast_diff_py.fast_dif import FastDifPy


# TODO finish implementation of this code

def dif(dir_a: str, dir_b: str, purge: bool = False, **kwargs):
    """
    kwargs are all attributes of the Config class, except for root_dir_a and root_dir_b

    :param dir_a: The first directory to compare
    :param dir_b: The second directory to compare
    :param purge: Delete any existing progress should it exist

    :return: FastDifPy object
    """
    fdo = FastDifPy(part_a=dir_a, part_b=dir_b, purge=purge, **kwargs)

    # Keep progress, we're not done
    fdo.config.retain_progress = True
    fdo.config.delete_db = False
    fdo.config.delete_thumb = False

    # Run the index
    if fdo.config.state == cfg.Progress.INIT:
        if fdo.db.dir_table_exists():
            fdo.db.drop_directory_table()

        fdo.full_index()

    # Exit in sigint
    if not fdo.run:
        fdo.commit()
        fdo.cleanup()
        return

    # Run the first loop
    if fdo.config.state in (cfg.Progress.INDEXED_DIRS, cfg.Progress.FIRST_LOOP_IN_PROGRESS):
        fdo.first_loop()

    # Exit on sigint
    if not fdo.run:
        print("First Loop Exited")
        fdo.commit()
        fdo.cleanup()
        return

    # Run the second loop
    if fdo.config.state in (cfg.Progress.SECOND_LOOP_IN_PROGRESS, cfg.Progress.FIRST_LOOP_DONE):
        fdo.second_loop()

    if not fdo.run:
        fdo.commit()
        fdo.cleanup()
        return

    # We're done, clean up
    fdo.config.retain_progress = False
    fdo.config.delete_db = True
    fdo.config.delete_thumb = True

    return fdo

    # Keep progress, we're not done
    fdo.config.retain_progress = True
    fdo.config.delete_db = False
    fdo.config.delete_thumb = False

    # Run the index
    if fdo.config.state == cfg.Progress.INIT:
        if fdo.db.dir_table_exists():
            fdo.db.drop_directory_table()

        fdo.full_index()

    # Exit in sigint
    if not fdo.run:
        fdo.commit()
        fdo.cleanup()
        return

    # Run the first loop
    if fdo.config.state in (cfg.Progress.INDEXED_DIRS, cfg.Progress.FIRST_LOOP_IN_PROGRESS):
        fdo.first_loop()

    # Exit on sigint
    if not fdo.run:
        print("First Loop Exited")
        fdo.commit()
        fdo.cleanup()
        return

    # Run the second loop
    if fdo.config.state in (cfg.Progress.SECOND_LOOP_IN_PROGRESS, cfg.Progress.FIRST_LOOP_DONE):
        fdo.second_loop()

    if not fdo.run:
        print("Second Loop Exited")
        fdo.commit()
        fdo.cleanup()
        return

    # We're done, clean up
    fdo.config.retain_progress = False
    fdo.config.delete_db = True
    fdo.config.delete_thumb = True

    return fdo


if __name__ == "__main__":
    # dir_a = "/home/alisot2000/Desktop/SAMEPLE_MIRA/dir_a"
    # dir_b = "/home/alisot2000/Desktop/SAMEPLE_MIRA/dir_c"

    dir_a = "/home/alisot2000/Desktop/test-dirs/dir_a"
    dir_b = "/home/alisot2000/Desktop/test-dirs/dir_b"

    # dir_a = "/home/alisot2000/Desktop/workbench_tiny/dir_a"
    # dir_b = "/home/alisot2000/Desktop/workbench_tiny/dir_b"
    o = dif(dir_a=dir_a, dir_b=dir_b, purge=True)
    for p in o.get_diff_pairs():
        print(p)

    for c in o.get_diff_clusters(dir_a=True):
        print(c)

    for c in o.get_diff_clusters(dir_a=False):
        print(c)

    o.config.retain_progress = False
    o.config.delete_db = False
    o.config.delete_thumb = True

    o.cleanup()
