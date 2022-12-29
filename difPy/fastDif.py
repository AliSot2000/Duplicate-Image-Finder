from database import Database
from typing import Union
import os
import warnings
import math
from utils import *


"""
Fast implementation of the DifPy Library.
Features:
- Use GPU to accelerate the comparison
- Use Parallelization to use multicore CPUs
- Use of aspect rotation to ignore images with non-matching aspect ratio
- Use hash based deduplication to find duplicates with color grading
- Use of binary differentiation to detect hard file duplicates
- Use of file names / zero difference to detect images which differ only in the metadata.
"""


class FastDifPy:

    p_db: str
    p_root_dir_a: str
    p_root_dir_b: Union[str, None]

    __thumbnail_size_x = 64
    __thumbnail_size_y = 64

    supported_file_types = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".gif", ".webp"}

    db: Database

    def __init__(self, directory_a: str, directory_b: str = None, test_db: bool = True):
        """
        Provide the directories to be searched. If a different implementation of the database is used,
        set the test_db to false.

        :param directory_a: first directory to search for differentiation.
        :param directory_b: second directory to compare against. Otherwise, comparison will be done against directory
        itself.
        :param test_db: Weather or not the code should test for the presence of the default sqlite database.
        """

        self.p_root_dir_b = directory_a
        self.p_root_dir_b = directory_b

        # proceed with the database if the default is used.
        if test_db:
            if not self.test_for_db():
                print("No matching database found. Creating new one.")
                self.db = Database(os.path.join(self.p_root_dir_a, "diff.db"))
                self.write_config()

    def test_for_db(self):
        """
        Test if the database is present in the current directory/ies. Directory A has priority.
        If a Database is found, the config is checked to make sure the paths match the current ones.

        :return: True -> Database connected and ready to use. False -> Database not found.
        """
        db_a = os.path.join(self.p_root_dir_a, "diff.db")
        dir_b = self.p_root_dir_b  # can be none
        db_b = os.path.join(dir_b, "diff.db")
        matching_config = False

        if os.path.exists(db_a):
            temp_db = Database(db_a)
            cfg = temp_db.get_config('main_config')

            # verify the config matches the call arguments (in case the computation was stopped during the
            # execution before)
            if cfg is not None:
                matching_config = cfg["directory_a"] == self.p_root_dir_a and cfg["directory_b"] == self.p_root_dir_b

                # return straight away in case the other directory is not set
                if matching_config and dir_b is None:
                    self.db = temp_db
                    return True

        if dir_b is not None and os.path.exists(db_b):
            temp_db = Database(db_b)
            cfg = temp_db.get_config('main_config')

            # verify the config matches the call arguments (in case the computation was stopped during the
            # execution before)
            if cfg is not None:
                temp_match = cfg["directory_a"] == self.p_root_dir_a and cfg["directory_b"] == self.p_root_dir_b

                if matching_config and temp_match:
                    raise Exception("Two matching configs found. Please remove one of the databases in one of the "
                                    "selected directories so the program can continue.")

                if temp_match:
                    self.db = temp_db
                    return True

        return False

    def get_progress_from_db(self):
        """
        Loads the progress state from the database.
        WARNING: The programm WILL NOT reindex the files. If you added files in the meantime, the files are NOT going
        compared against!
        :return:
        """

        # TODO get the progress from the database
        print("Not implemented yet")

    def write_config(self):
        """
        Write the initial config to the database.
        :return:
        """
        temp_config = {
            "directory_a": self.p_root_dir_a,
            "directory_b": self.p_root_dir_b
        }
        self.db.create_config(type_name="main_config", config=temp_config)

    # Perform two loops.
    # First loop:
    # - load the metadata / paths of the images i.e. (image size)
    # - If desired, compute the thumbnail of the image
    # - if desired compute the hash of the image

    # Second loop
    # - compress the images (if not thumbnails were calculated)
    #

    def index_the_dirs(self):
        # create the tables in the database
        self.db.create_directory_tables(secondary_folder=self.p_root_dir_b is not None)

        self.recursive_index(True)
        if self.p_root_dir_b is not None:
            self.recursive_index(False)

    def recursive_index(self, dir_a: bool = True, path: str = None, ignore_thumbnail: bool = True):
        """
        Recursively index the directories. This function is called by the index_the_dirs function.
        :param ignore_thumbnail: If any directory at any level, starting with .thumb should be ignored.
        :param dir_a: True -> Index dir A. False -> Index dir B
        :param path: The path to the current directory. This is used for recursion.
        :return:
        """

        # load the path to index from
        if path is None:
            if dir_a:
                path = self.p_root_dir_a
            else:
                path = self.p_root_dir_b

        for file_name in os.listdir(path):
            full_path = os.path.join(path, file_name)

            # Thumbnail directory is called .thumbnails
            if file_name.startswith(".thumb") and ignore_thumbnail:
                continue

            # for directories, continue the recursion
            if os.path.isdir(full_path):
                self.recursive_index(dir_a, full_path)

            if os.path.isfile(full_path):
                # check if the file is supported, then add it to the database
                if os.path.splitext(full_path)[1] in self.supported_file_types:
                    self.db.add_file(full_path, file_name, dir_a)

    def estimate_disk_usage(self):
        """
        Estimate the diskusage of the thumbnail directory given the compressed image size.
        :return:
        """
        dir_a_count = self.db.get_dir_count(True)
        dir_b_count = self.db.get_dir_count(False)

        byte_count_a = dir_a_count * self.__thumbnail_size_x * self.__thumbnail_size_y * 3
        byte_count_b = dir_b_count * self.__thumbnail_size_x * self.__thumbnail_size_y * 3

        target = max(len(self.p_root_dir_a), len(self.p_root_dir_b))

        print(f"Estimated disk usage by {fill(self.p_root_dir_a, target)}: " + h(byte_count_a, "B") + " bytes")
        print(f"Estimated disk usage by {fill(self.p_root_dir_b, target)}: " + h(byte_count_b, "B") + " bytes")

    def clean_up(self):
        # TODO remove the thumbnails
        # TODO remove database (if desired)
        print("Not implemented yet")

    @property
    def thumbnail_size_x(self):
        return self.__thumbnail_size_x

    @thumbnail_size_x.setter
    def thumbnail_size_x(self, value):
        if value < 0:
            raise ValueError("Thumbnail size must be positive")

        if value > 1000:
            warnings.warn("Thumbnail size is very large. Higher Accuracy will slow down the process and "
                          "increase storage usage.")
        self.__thumbnail_size_x = value

    @property
    def thumbnail_size_y(self):
        return self.__thumbnail_size_y

    @thumbnail_size_y.setter
    def thumbnail_size_y(self, value):
        if value < 0:
            raise ValueError("Thumbnail size must be positive")

        if value > 1000:
            warnings.warn("Thumbnail size is very large. Higher Accuracy will slow down the process and "
                          "increase storage usage.")
        self.__thumbnail_size_y = value
