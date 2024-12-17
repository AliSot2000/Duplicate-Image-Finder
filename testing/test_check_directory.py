import unittest
from typing import List

from fast_diff_py import FastDifPy, Config


def test_method(part_a: List[str], part_b: List[str], recurse: bool):
    """
    This function is used to test the FastDifPy class. It and execute the given test.
    """
    cfg = Config(part_a=part_a, part_b=part_b, recurse=recurse)
    return FastDifPy(config=cfg, test_mode=True)


class TestFastDiffCheckDirs(unittest.TestCase):
    """
    This is a test class that will test the FastDifPy's check_directories function.
    """

    # ==================================================================================================================
    # Test Cases checking directories between partition a and partition b
    # ==================================================================================================================

    def test_same_dir_ab_rec(self):
        fdo = test_method(
            part_a=["/path/to/dir_1"],
            part_b=["/path/to/dir_1"],
            recurse=True
        )
        # We have twice the same dir, should return True -> would raise an exception in caller method in FastDifPy
        self.assertTrue(fdo.check_directories())
        fdo.cleanup()

    def test_same_dir_ab_no_rec(self):
        fdo = test_method(
            part_a=["/path/to/dir_1"],
            part_b=["/path/to/dir_1"],
            recurse=False
        )
        # We have twice the same dir, should return True -> would raise an exception in caller method in FastDifPy
        self.assertTrue(fdo.check_directories())
        fdo.cleanup()

    def test_subdir_ab_rec(self):
        fdo = test_method(
            part_a=["/path/to/dir_1"],
            part_b=["/path/to/dir_1/subdir"],
            recurse=True
        )
        # Subdirectories of each other, should return True -> would raise an exception in caller method in FastDifPy
        self.assertTrue(fdo.check_directories())

    def test_subdir_ab_rec_inv(self):
        fdo = test_method(
            part_a=["/path/to/dir_1/subdir"],
            part_b=["/path/to/dir_1"],
            recurse=True
        )
        # Subdirectories of each other, should return True -> would raise an exception in caller method in FastDifPy
        self.assertTrue(fdo.check_directories())
        fdo.cleanup()

    def test_subdir_ab_no_rec(self):
        fdo = test_method(
            part_a=["path/to/dir_1"],
            part_b=["/path/to/dir_1/subdir"],
            recurse=False
        )
        # Subdirectories of each other, should return False, we're not recursing
        self.assertFalse(fdo.check_directories())
        fdo.cleanup()

    def test_subdir_ab_no_rec_inv(self):
        fdo = test_method(
            part_a=["/path/to/dir_1/subdir"],
            part_b=["path/to/dir_1"],
            recurse=False
        )
        # Subdirectories of each other, should return False, we're not recursing
        self.assertFalse(fdo.check_directories())
        fdo.cleanup()

    # ==================================================================================================================
    # Test Cases checking directories within partition a
    # ==================================================================================================================

    def test_aa_same_dir_rec(self):
        fdo = test_method(
            part_a=["/path/to/dir_1", "/path/to/dir_1"],
            part_b=[],
            recurse=True
        )
        # We have twice the same dir, should return True -> would raise an exception in caller method in FastDifPy
        self.assertTrue(fdo.check_directories())
        fdo.cleanup()

    def test_aa_same_dir_no_rec(self):
        fdo = test_method(
            part_a=["/path/to/dir_1", "/path/to/dir_1"],
            part_b=[],
            recurse=False
        )
        # We have twice the same dir, should return True -> would raise an exception in caller method in FastDifPy
        self.assertTrue(fdo.check_directories())
        fdo.cleanup()

    def test_aa_subdir_rec(self):
        fdo = test_method(
            part_a=["/path/to/dir_1", "/path/to/dir_1/subdir"],
            part_b=[],
            recurse=True
        )
        # Subdirectories of each other, should return True -> would raise an exception in caller method in FastDifPy
        self.assertTrue(fdo.check_directories())
        fdo.cleanup()

    def test_aa_subdir_no_rec(self):
        fdo = test_method(
            part_a=["/path/to/dir_1", "/path/to/dir_1/subdir"],
            part_b=[],
            recurse=False
        )
        # Subdirectories of each other, should return False, we're not recursing
        self.assertFalse(fdo.check_directories())
        fdo.cleanup()

    # ==================================================================================================================
    # Test Cases checking directories within partition b
    # ==================================================================================================================

    def test_bb_same_dir_rec(self):
        fdo = test_method(
            part_a=["/path/to/dir_2"],
            part_b=["/path/to/dir_1", "/path/to/dir_1"],
            recurse=True
        )
        # We have twice the same dir, should return True -> would raise an exception in caller method in FastDifPy
        self.assertTrue(fdo.check_directories())
        fdo.cleanup()

    def test_bb_same_dir_no_rec(self):
        fdo = test_method(
            part_a=["/path/to/dir_2"],
            part_b=["/path/to/dir_1", "/path/to/dir_1"],
            recurse=False
        )
        # We have twice the same dir, should return True -> would raise an exception in caller method in FastDifPy
        self.assertTrue(fdo.check_directories())
        fdo.cleanup()

    def test_bb_subdir_rec(self):
        fdo = test_method(
            part_a=["/path/to/dir_2"],
            part_b=["/path/to/dir_1", "/path/to/dir_1/subdir"],
            recurse=True
        )
        # Subdirectories of each other, should return True -> would raise an exception in caller method in FastDifPy
        self.assertTrue(fdo.check_directories())
        fdo.cleanup()

    def test_bb_subdir_no_rec(self):
        fdo = test_method(
            part_a=["/path/to/dir_2"],
            part_b=["/path/to/dir_1", "/path/to/dir_1/subdir"],
            recurse=False
        )
        # Subdirectories of each other, should return False, we're not recursing
        self.assertFalse(fdo.check_directories())
        fdo.cleanup()


if __name__ == '__main__':
    unittest.main()

