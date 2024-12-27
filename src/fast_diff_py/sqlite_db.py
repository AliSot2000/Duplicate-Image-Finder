import os.path
from typing import List, Dict, Set, Tuple, Iterator, Union

from fast_diff_py.datatransfer import PreprocessArg, PreprocessResult
from fast_diff_py.sqlite_wrapper import BaseSQliteDB
from fast_diff_py.utils import to_b64, from_b64


class SQLiteDB(BaseSQliteDB):
    debug: bool
    def __init__(self, db_path: str, debug: bool = False):
        """
        In Debug Mode, Model Validation is turned on, for performance reasons, it's skipped.
        """
        super().__init__(db_path)
        self.debug = debug

    @staticmethod
    def __get_directory_table_names(temp: bool = False) -> str:
        """
        Get the table names for the directories

        :param temp: Whether to get the temp table or not
        """
        if temp:
            tbl_name = "directory_temp"
        else:
            tbl_name = "directory"

        return tbl_name

    # Create Tables Command
    def create_directory_table_and_index(self, temp: bool = False):
        """
        Create the table for the directories
        :param temp: Whether to create the temp table or not
        """
        tbl_name = self.__get_directory_table_names(temp)

        stmt = (f"CREATE TABLE {tbl_name} ("
                f"key INTEGER PRIMARY KEY AUTOINCREMENT, "
                f"path TEXT, "
                f"filename TEXT, "
                f"error TEXT, "
                f"success INTEGER DEFAULT -1 CHECK ({tbl_name}.success IN (-2, -1, 0, 1)), "
                f"px INTEGER DEFAULT -1 CHECK ({tbl_name}.px >= -1), "
                f"py INTEGER DEFAULT -1 CHECK ({tbl_name}.py >= -1), "
                f"allowed INTEGER DEFAULT 0 CHECK ({tbl_name}.allowed IN (0, 1)), "
                f"file_size INTEGER DEFAULT -1 CHECK ({tbl_name}.file_size >= -1), "
                f"created REAL DEFAULT -1 CHECK ({tbl_name}.created >= -1), "
                f"dir_index INTEGER DEFAULT -1 CHECK ({tbl_name}.dir_index >= -1), "
                f"part_b INTEGER DEFAULT 0 CHECK ({tbl_name}.part_b IN (0, 1)), "
                f"hash_0 INTEGER, "
                f"hash_90 INTEGER, "
                f"hash_180 INTEGER, "
                f"hash_270 INTEGER, "
                f"deleted INTEGER DEFAULT 0 CHECK ({tbl_name}.deleted IN (0, 1)), "
                f"UNIQUE (path, part_b))")

        self.debug_execute(stmt, )
        if not temp:
            self.create_directory_indexes()

    def drop_directory_table(self):
        """
        Drop the directory table
        """
        self.debug_execute("DROP TABLE IF EXISTS directory")
        self.debug_execute("DROP TABLE IF EXISTS directory_temp")

    def create_directory_indexes(self):
        """
        Create the indexes on the directory table
        """
        self.debug_execute(f"CREATE INDEX directory_key_index ON directory (key)")
        self.debug_execute(f"CREATE INDEX directory_partition_index ON directory (part_b)")
        self.debug_execute(f"CREATE INDEX directory_success_index ON directory (success)")
        self.debug_execute(f"CREATE INDEX directory_success_file_size_created ON directory (file_size, created)")

    def drop_directory_index(self):
        """
        Drop the index on the directory table
        """
        self.debug_execute("DROP INDEX IF EXISTS directory_key_index")
        self.debug_execute("DROP INDEX IF EXISTS directory_partition_index")
        self.debug_execute("DROP INDEX IF EXISTS directory_success_index")
        self.debug_execute("DROP INDEX IF EXISTS directory_success_file_size_created")

    def create_hash_table_and_index(self):
        """
        Create the table for the hash values and create an index for faster lookups
        """
        stmt = ("CREATE TABLE hash_table ("
                "key INTEGER PRIMARY KEY AUTOINCREMENT , "
                "hash TEXT UNIQUE , "
                "count INTEGER CHECK (hash_table.count >= 0))"
                )

        self.debug_execute(stmt)

        stmt = "CREATE INDEX hash_table_index ON hash_table (hash)"
        self.debug_execute(stmt)

        self.create_hash_indexes()

    def create_diff_table_and_index(self):
        """
        Create the table for the diffs.
        """
        stmt = ("CREATE TABLE dif_table ("
                "key INTEGER PRIMARY KEY AUTOINCREMENT, "
                "key_a INTEGER NOT NULL, "
                "key_b INTEGER NOT NULL, "
                "dif REAL CHECK (dif_table.dif >= -1) DEFAULT -1, "
                "success INT CHECK (dif_table.success IN (0, 1, 2, 3)) DEFAULT -1, " # 2, matching hash # 3, matching aspect
                "error TEXT, "
                "UNIQUE (key_a, key_b)) ")

        self.debug_execute(stmt)

        self.debug_execute("CREATE INDEX dif_table_key_index ON dif_table (key)")
        self.debug_execute("CREATE INDEX dif_table_key_a_key_b_index ON dif_table (key_a, key_b)")

    def create_hash_indexes(self):
        """
        Add indexes on hashes for improved performance when retrieving the duplicates based on hash.
        """
        self.debug_execute("CREATE INDEX directory_hash_0_index ON directory (hash_0)")
        self.debug_execute("CREATE INDEX directory_hash_90_index ON directory (hash_90)")
        self.debug_execute("CREATE INDEX directory_hash_180_index ON directory (hash_180)")
        self.debug_execute("CREATE INDEX directory_hash_270_index ON directory (hash_270)")

    # ==================================================================================================================
    # Dir Table
    # ==================================================================================================================

    def dir_table_exists(self):
        """
        Check if the directory table exists
        """
        stmt = "SELECT name FROM sqlite_master WHERE type='table' AND name='directory'"
        self.debug_execute(stmt)
        return self.sq_cur.fetchone() is not None

    def bulk_insert_file_external(self,
                                  paths: List[str],
                                  allowed: List[int],
                                  size: List[int],
                                  created: List[float],
                                  part_a: bool):
        """
        Insert a list of files into the database

        :param paths: The paths to the files
        :param allowed: Whether the file is allowed for the comparison
        :param size: The sizes of the files
        :param created: The creation time of the files (unix timestamp)
        :param part_a: Whether this is partition A or partition B

        """
        part = 0 if part_a else 1
        args = [(paths[i],
                 os.path.basename(paths[i]),
                 allowed[i],
                 size[i],
                 created[i],
                 part)
                for i in range(len(paths))]

        self.debug_execute_many(
            stmt="INSERT INTO directory (path, filename, allowed, file_size, created, part_b) VALUES (?, ?, ?, ?, ?, ?)",
            args=args)

    def bulk_insert_file_internal(self,
                                  path: str,
                                  files: List[Tuple[str, int, int, float]],
                                  index: int,
                                  part_b: bool = False):
        """
        Insert a folder of files into the database

        :param path: The path to the folder
        :param files: List of file info (filename, allowed, file_size, created)
        :param index: The index of the directory (in the config)
        :param part_b: Whether this is the B directory or not
        """
        stmt = ("INSERT INTO directory (path, filename, allowed, file_size, created, part_b, dir_index) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)")
        _part_b = 1 if part_b else 0

        args = [
            (os.path.join(path, files[i][0]),
             files[i][0],
             files[i][1],
             files[i][2],
             files[i][3],
             _part_b,
             index)
            for i in range(len(files))
        ]

        self.debug_execute_many(stmt, args)

    def reset_preprocessing(self):
        """
        Reset the Preprocessing flag of -2 in the dir table
        """
        self.debug_execute("UPDATE directory SET success = -1 WHERE success = -2")

    def batch_of_preprocessing_args(self, batch_size: int) -> List[PreprocessArg]:
        """
        Get a batch of preprocessing args

        :param batch_size: How many rows to fetch at once
        """
        stmt = ("SELECT key, path FROM directory WHERE success = -1 AND allowed = 1 LIMIT ?")
        self.debug_execute(stmt, (batch_size,))

        if self.debug:
            results = [PreprocessArg(file_path=row[1], key=row[0]) for row in self.sq_cur.fetchall()]
        else:
            results = [PreprocessArg.model_construct(file_path=row[1], key=row[0]) for row in self.sq_cur.fetchall()]

        # Update to processing
        stmt = ("UPDATE directory SET success = -2 WHERE key IN "
                "(SELECT key FROM directory WHERE success = -1 AND allowed = 1 LIMIT ?)")
        self.debug_execute(stmt, (batch_size,))

        return results

    def batch_of_first_loop_results(self, results: List[PreprocessResult], has_hash: bool = False):
        """
        Insert the results of the preprocessing into the database
        """
        if self.debug:
            for r in results:
                assert r is not None, "Result is None"
        err = []
        success = []

        # Split errors and successes
        for res in results:
            if res.error is not None:
                err.append(res)
            else:
                success.append(res)

        # Update the errors
        update_err = [(to_b64(res.error), res.key) for res in err]
        update_err_stmt = "UPDATE directory SET error = ?, success = 0 WHERE key = ?"
        self.debug_execute_many(update_err_stmt, update_err)

        # Update the successes
        if has_hash:
            # Update that has hash
            update_success = [(res.org_x, res.org_y, res.hash_0, res.hash_90, res.hash_180, res.hash_270, res.key)
                              for res in success]
            update_success_stmt = (
                "UPDATE directory SET px = ?, py = ?, hash_0 = ?, hash_90 = ?, hash_180 = ?, hash_270 = ?, success = 1"
                " WHERE key = ?" )

            # Update that doesn't have hash
        else:
            update_success = [(res.org_x, res.org_y, res.key) for res in success]
            update_success_stmt = "UPDATE directory SET px = ?, py = ?, success = 1 WHERE key = ?"

        self.debug_execute_many(update_success_stmt, update_success)

    def get_partition_entry_count(self, part_b: bool, only_allowed: bool = True) -> int:
        """
        Get the number of entries in the directory table

        :param part_b: Whether to get the count for partition b or partition a
        :param only_allowed: Whether to only count the allowed entries
        """
        _part_b = 1 if part_b else 0
        stmt = "SELECT COUNT(*) FROM directory WHERE part_b = ?"
        if only_allowed:
            stmt += " AND allowed = 1"
        self.debug_execute(stmt, (_part_b,))
        return self.sq_cur.fetchone()[0]

    def get_b_offset(self) -> int:
        """
        Get the index belonging to dir_b
        """
        stmt = "SELECT MIN(key) FROM directory WHERE part_b = 1"
        self.debug_execute(stmt)
        return self.sq_cur.fetchone()[0]

    def get_directory_stats(self, index: int, allowed: bool = True):
        """
        Get the number of entries for a given directory and a given alloed state
        """
        stmt = "SELECT COUNT(*) FROM directory WHERE dir_index = ? AND allowed = ?"
        self.debug_execute(stmt, (index, 1 if allowed else 0))
        return self.sq_cur.fetchone()[0]

    def repopulate_directory_table(self) -> bool:
        """
        Populate the directory table in a specific order to make sure we don't have holes when we're building the
        caches etc.

        What should happen:
        First the smaller partition of partition A and partition B is inserted
        Then the larger partition of partition A and partition B is inserted
        Lastly the not allowed entries are inserted

        Then the keys are updated so they are zero-indexed

        Then the old table is dropped and the new table is renamed

        And lastly the indexes are recreated

        :return: Whether the partition assignment was inverted
        """
        self.create_directory_table_and_index(temp=True)
        tmp_tbl = self.__get_directory_table_names(True)
        d_tbl = self.__get_directory_table_names(False)

        # Determine the order in which we get the keys for the allowed entries
        dac = self.get_partition_entry_count(part_b=False, only_allowed=True)
        dbc = self.get_partition_entry_count(part_b=True, only_allowed=True)

        invert_partition = False

        # Make sure the smaller allowed partition is first
        if dac < dbc or dbc == 0:
            # Inserting the directory_b entries first
            stmt_asc= (f"INSERT INTO {tmp_tbl} "
                       f"(path, filename, error, success, px, py, allowed, file_size, created, dir_index, part_b, "
                       f"hash_0, hash_90, hash_180, hash_270) "
                       f"SELECT path, filename, error, success, px, py, allowed, file_size, created, dir_index, part_b, "
                       f"hash_0, hash_90, hash_180, hash_270 "
                       f"FROM {d_tbl} WHERE allowed = 1 ORDER BY part_b ASC")

            self.debug_execute(stmt_asc)

        # Need to swap
        else:
            # Inserting the directory_b entries first
            stmt_b_a = (f"INSERT INTO {tmp_tbl} "
                        f"(path, filename, error, success, px, py, allowed, file_size, created, dir_index, part_b, "
                        f"hash_0, hash_90, hash_180, hash_270) "
                        f"SELECT path, filename, error, success, px, py, allowed, file_size, created, dir_index, 0 AS part_b, "
                        f"hash_0, hash_90, hash_180, hash_270 "
                        f"FROM {d_tbl} WHERE part_b = 1 AND allowed = 1")

            stmt_a_b = (f"INSERT INTO {tmp_tbl} "
                        f"(path, filename, error, success, px, py, allowed, file_size, created, dir_index, part_b, "
                        f"hash_0, hash_90, hash_180, hash_270) "
                        f"SELECT path, filename, error, success, px, py, allowed, file_size, created, dir_index, 1 AS part_b, "
                        f"hash_0, hash_90, hash_180, hash_270 "
                        f"FROM {d_tbl} WHERE part_b = 0 AND allowed = 1")

            self.debug_execute(stmt_b_a)
            self.debug_execute(stmt_a_b)
            invert_partition = True

        # Writing the remaining not allowed entries
        stmt_r = (f"INSERT INTO {tmp_tbl} "
                  f"(path, filename, error, success, px, py, allowed, file_size, created, dir_index, part_b, "
                  f"allowed, hash_0, hash_90, hash_180, hash_270) "
                    f"SELECT path, filename, error, success, px, py, allowed, file_size, created, dir_index, part_b, "
                  f"allowed, hash_0, hash_90, hash_180, hash_270 "
                  f"FROM {d_tbl} WHERE allowed = 0 ORDER BY part_b ASC")

        # Add the non-allowed entries
        self.debug_execute(stmt_r)

        # Set keys to zero-index
        self.debug_execute(f"UPDATE {tmp_tbl} SET key = key - (SELECT MIN(key) FROM {tmp_tbl})")

        # INFO Index is dropped with table
        self.debug_execute(f"DROP TABLE {d_tbl}")

        # Renaming the temp table and index
        self.debug_execute(f"ALTER TABLE {tmp_tbl} RENAME TO {d_tbl}")
        self.drop_directory_index()
        self.create_directory_indexes()

        return invert_partition

    def get_rows_directory(self, start: int, batch_size: int, part_b: bool = False,
                           do_hash: bool = False, aspect: bool = False, path: bool = False) \
            -> Tuple[List[str], List[Tuple[int, int, int, int]], List[Tuple[int, int]], List[int]]:
        """
        Get the rows from the directory table

        :param start: The start index
        :param batch_size: The size of the batch
        :param part_b: Whether to get the rows from the dir_b table or not
        :param do_hash: Whether to get the hash values or not
        :param aspect: Whether to get the aspect ratio or not
        :param path: Whether to get the path or not
        """
        # We want everything
        part_b_i = 1 if part_b else 0
        if do_hash and aspect and path:
            stmt = ("SELECT key, path, hash_0, hash_90, hash_180, hash_270, px, py "
                    "FROM directory WHERE part_b = ? AND allowed = 1 LIMIT ? OFFSET ?")
        elif do_hash and aspect and not path:
            stmt = ("SELECT key, hash_0, hash_90, hash_180, hash_270, px, py FROM directory "
                    "WHERE part_b = ? AND allowed = 1 LIMIT ? OFFSET ?")
        elif do_hash and not aspect and path:
            stmt = ("SELECT key, path, hash_0, hash_90, hash_180, hash_270 FROM directory "
                    "WHERE part_b = ? AND allowed = 1 LIMIT ? OFFSET ?")
        elif do_hash and not aspect and not path:
            stmt = ("SELECT key, hash_0, hash_90, hash_180, hash_270 FROM directory "
                    "WHERE part_b = ? AND allowed = 1 LIMIT ? OFFSET ?")
        elif not do_hash and aspect and path:
            stmt = "SELECT key, path, px, py FROM directory WHERE part_b = ? AND allowed = 1 LIMIT ? OFFSET ?"
        elif not do_hash and aspect and not path:
            stmt = "SELECT key, px, py FROM directory WHERE part_b = ? AND allowed = 1 LIMIT ? OFFSET ?"
        elif not do_hash and not aspect and path:
            stmt = "SELECT key, path FROM directory WHERE part_b = ? AND allowed = 1 LIMIT ? OFFSET ?"
        elif not do_hash and not aspect and not path:
            stmt = "SELECT key FROM directory WHERE part_b = ? AND allowed = 1 LIMIT ? OFFSET ?"
            # return [], [], []
        else:
            raise ValueError("Tertiem Non Datur")

        self.debug_execute(stmt, (part_b_i, batch_size, start))
        rows = self.sq_cur.fetchall()
        keys = []
        paths = []
        hashes = []
        aspects = []

        for row in rows:
            if do_hash and aspect and path:
                # stmt = "SELECT key, path, hash_0, hash_90, hash_180, hash_270, px, py FROM directory LIMIT ? OFFSET ?"
                keys.append(row[0])
                paths.append(row[1])
                hashes.append((row[2], row[3], row[4], row[5]))
                aspects.append((row[6], row[7]))
            elif do_hash and aspect and not path:
                # stmt = "SELECT key, hash_0, hash_90, hash_180, hash_270, px, py FROM directory LIMIT ? OFFSET ?"
                keys.append(row[0])
                hashes.append((row[1], row[2], row[3], row[4]))
                aspects.append((row[5], row[6]))
            elif do_hash and not aspect and path:
                # stmt = "SELECT key, path, hash_0, hash_90, hash_180, hash_270 FROM directory LIMIT ? OFFSET ?"
                keys.append(row[0])
                paths.append(row[1])
                hashes.append((row[2], row[3], row[4], row[5]))
            elif do_hash and not aspect and not path:
                # stmt = "SELECT key, hash_0, hash_90, hash_180, hash_270 FROM directory LIMIT ? OFFSET ?"
                keys.append(row[0])
                hashes.append((row[1], row[2], row[3], row[4]))
            elif not do_hash and aspect and path:
                # stmt = "SELECT key, path, px, py FROM directory LIMIT ? OFFSET ?"
                keys.append(row[0])
                paths.append(row[1])
                aspects.append((row[2], row[3]))
            elif not do_hash and aspect and not path:
                # stmt = "SELECT key, px, py FROM directory LIMIT ? OFFSET ?"
                keys.append(row[0])
                aspects.append((row[1], row[2]))
            elif not do_hash and not aspect and path:
                # stmt = "SELECT key, path FROM directory LIMIT ? OFFSET ?"
                keys.append(row[0])
                paths.append(row[1])
            elif not do_hash and not aspect and not path:
                # stmt = "SELECT key FROM directory LIMIT ? OFFSET ?"
                keys.append(row[0])
            else:
                raise ValueError("Tertiem Non Datur")

        return paths, hashes, aspects, keys

    def set_deleted(self, key: int, deleted: bool = True):
        """
        Set the deleted state of a file

        :param key: The key of the file
        :param deleted: Whether the file is deleted or not
        """
        stmt = "UPDATE directory SET deleted = ? WHERE key = ?"
        self.debug_execute(stmt, (1 if deleted else 0, key))

    def get_directory_errors(self) -> Iterator[Tuple[str, str]]:
        """
        Get the filepaths and errors from the directory table

        Return the errors with iterator.
        """
        self.debug_execute("SELECT path, error FROM directory WHERE success = 0")

        for res in self.sq_cur.fetchall():
            yield res[0], from_b64(res[1])

    def get_directory_disallowed(self) -> Iterator[str]:
        """
        Get the filepaths from the directory table which weren't allowed
        """
        self.debug_execute("SELECT path FROM directory WHERE allowed = 0")
        for res in self.sq_cur.fetchall():
            yield res[0]

    # ==================================================================================================================
    # Hash Table
    # ==================================================================================================================

    def bulk_insert_hashes(self, hashes: List[str]):
        """
        Insert a list of hashes into the hash table. Performs either an insert, if the hash doesn't exist or updates
        the matching hash

        :param hashes: List of hashes to insert
        """
        stmt = "INSERT INTO hash_table (hash, count) VALUES (?, 1) ON CONFLICT(hash) DO UPDATE SET count = count + 1;"
        tgt = [(h,) for h in hashes]
        self.debug_execute_many(stmt, tgt)

    def get_bulk_hash_lookup(self, hashes: Set[str]) -> Dict[str, int]:
        """
        Get the keys for a list of hashes

        :param hashes: List of hashes to lookup

        :return: List of keys
        """
        lookup: Dict[str, int] = {}

        for h in hashes:
            self.debug_execute("SELECT key FROM hash_table WHERE hash = ?", (h,))
            res = self.sq_cur.fetchone()
            assert res is not None, "Hash not found"
            lookup[h] = res[0]

        return lookup

    def get_hash_cluster_count(self) -> int:
        """
        Get the number of clusters which have a matching hash. Keep in mind, that an image has 4 hashes for all 4
        rotations. So the best lower bound for the actual number of clusters is /4.

        :return: The number of clusters
        """
        self.debug_execute("SELECT COUNT(*) FROM hash_table WHERE count > 1")
        return self.sq_cur.fetchone()[0]

    def get_all_hash_clusters(self, include_deleted: bool = True) -> Iterator[Tuple[str, List[str]]]:
        """
        Get all clusters from the hash table

        :param include_deleted: Whether to include deleted images in the clusters

        :return: A list of tuples the first string is the hash, the List of strings is the list of files with that hash.
        """
        for i in range(self.get_hash_cluster_count()):
            yield self.get_ith_hash_cluster(i=i, include_deleted=include_deleted)

    def get_ith_hash_cluster(self, i: int, include_deleted: bool = True) -> Tuple[str, List[str]]:
        """
        Get the ith cluster of hashes

        :param i: The index of the cluster
        :param include_deleted: Whether to include deleted entries (files marked as deleted in the db)

        :return: hash, List of file paths with that hash. Ordered by file_size desc, created asc

        :raises IndexError: If the index is out of bounds and the hash couldn't be found.

        => Check the number of clusters with `get_hash_cluster_count`
        """
        self.debug_execute("SELECT hash FROM hash_table WHERE count > 1 LIMIT 1 OFFSET ?", (i,))
        tgt_hash = self.sq_cur.fetchone()

        if tgt_hash is None:
            raise IndexError("Index out of bound.")

        if include_deleted:
            stmt = ("SELECT path FROM directory "
                    "WHERE hash_0 = ? OR hash_90 = ? OR hash_180 = ? OR hash_270 = ? "
                    "ORDER BY file_size DESC, created ASC")
        else:
            stmt = ("SELECT path FROM directory "
                    "WHERE (hash_0 = ? OR hash_90 = ? OR hash_180 = ? OR hash_270 = ?) AND deleted = 0 "
                    "ORDER BY file_size DESC, created ASC")

        # Get the files from the cluster
        self.debug_execute(stmt, (tgt_hash[0], tgt_hash[0], tgt_hash[0], tgt_hash[0]))
        files = [row[0] for row in self.sq_cur.fetchall()]

        return str(tgt_hash[0]), files

    # ==================================================================================================================
    # Diff Table
    # ==================================================================================================================

    def bulk_insert_diff_success(self, args: List[Tuple[int, int, int, float]]):
        """
        Insert the results of the diff into the database
        """
        stmt = ("INSERT INTO dif_table (key_a, key_b, success, dif) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key_a, key_b) DO NOTHING")
        self.debug_execute_many(stmt, args)

    def bulk_insert_diff_error(self, args: List[Tuple[int, int, str]]):
        """
        Insert the error of the diff into the database
        """
        restructured_args = [(key_a, key_b, to_b64(error)) for key_a, key_b, error in args]
        stmt = ("INSERT INTO  dif_table (key_a, key_b, success, error) VALUES (?, ?, 0, ?) "
                "ON CONFLICT(key_a, key_b) DO NOTHING")
        self.debug_execute_many(stmt, restructured_args)

    def get_pair_count_diff(self):
        """
        Get the number of pairs that need to be computed
        """
        stmt = "SELECT COUNT(*) FROM dif_table WHERE success = -1"
        self.debug_execute(stmt)
        return self.sq_cur.fetchone()[0]

    def get_duplicate_pairs(self, delta: float, include_hash_match: bool = False) -> List[Tuple[str, str, float]]:
        """
        Get all Pairs of images that are below the threshold from the table.

        :param delta: The threshold for the difference
        :param include_hash_match: Whether to include diffs of 0 that were a result of having matching hashes

        :return: List of tuples with the following information:
        - path_a
        - path_b
        - dif
        """
        # INFO:
        #  1 -> success, dif = actual dif
        #  2 -> matching hash, dif = 0.0
        #  3 -> matching aspect, if no match, dif = -1.0

        if include_hash_match:
            stmt = ("SELECT a.path, b.path, d.dif "
                    "FROM dif_table AS d "
                    "JOIN directory AS a ON a.key = d.key_a "
                    "JOIN directory AS b ON b.key = d.key_b "
                    "WHERE dif < ? AND d.success IN (1, 2) ORDER BY d.key_a, d.key_b")
        else:
            stmt = ("SELECT a.path, b.path, d.dif "
                    "FROM dif_table AS d "
                    "JOIN directory AS a ON a.key = d.key_a "
                    "JOIN directory AS b ON b.key = d.key_b "
                    "WHERE dif < ? AND d.success = 1 ORDER BY d.key_a, d.key_b")

        self.debug_execute(stmt, (delta,))
        for row in self.sq_cur.fetchall():
            yield row

    def get_all_cluster(self, delta: float, group_a: bool = True, include_hash_match: bool = True) \
            -> Iterator[Tuple[str, List[Tuple[str, float]]]]:
        """
        Get clusters of images that have a difference below the threshold.

        Within each cluster, the images are sorted by file_size desc, created asc

        :param delta: The threshold for the difference
        :param group_a: Either group by partition a or partition b.
        :param include_hash_match: Whether to include diffs of 0 that were a result of having matching hashes
        """
        stmt = ("SELECT a.path, b.path, d.dif "
                "FROM dif_table AS d "
                "JOIN directory AS a ON a.key = d.key_a "
                "JOIN directory AS b ON b.key = d.key_b ")

        if include_hash_match:
            stmt += " WHERE dif <= ? AND d.success IN (1, 2) "
        else:
            stmt += " WHERE dif <= ? AND d.success = 1 "

        if group_a:
            stmt += "ORDER BY d.key_a, b.file_size DESC, b.created ASC"
        else:
            stmt += "ORDER BY d.key_b, a.file_size DESC, a.created ASC"

        self.debug_execute(stmt, (delta,))

        row = self.sq_cur.fetchone()

        if row is None:
            return -1, {}

        head = row[0] if group_a else row[1]
        acc = [row]

        while True:
            row = self.sq_cur.fetchone()

            # Exit Loop condition
            if row is None:
                if group_a:
                    yield head, [(r[1], r[2]) for r in acc]
                else:
                    yield head, [(r[0], r[2]) for r in acc]
                break

            # Check the new head
            int_head = row[0] if group_a else row[1]
            if int_head == head:
                acc.append(row)
            else:
                if group_a:
                    yield head, [(r[1], r[2]) for r in acc]
                else:
                    yield head, [(r[0], r[2]) for r in acc]
                head = int_head
                acc = [row]

    def get_cluster_count(self, delta: float, part_a: bool = True, include_hash_match: bool = True) -> int:
        """
        Get the number of clusters that are below the threshold

        :param delta: The threshold for the difference
        :param part_a: Whether to get the count for partition a or partition b (part_b might be part_a if
        it was left empty)
        :param include_hash_match: Whether to include diffs of 0 that were a result of having matching hashes

        :return: The number of clusters
        """
        if part_a and include_hash_match:
            stmt = "SELECT COUNT(DISTINCT(key_a)) FROM dif_table WHERE dif <= ? AND success IN (1, 2)"
        elif part_a and not include_hash_match:
            stmt = "SELECT COUNT(DISTINCT(key_a)) FROM dif_table WHERE dif <= ? AND success = 1"
        elif not part_a and include_hash_match:
            stmt = "SELECT COUNT(DISTINCT(key_b)) FROM dif_table WHERE dif <= ? AND success IN (1, 2)"
        elif not part_a and not include_hash_match:
            stmt = "SELECT COUNT(DISTINCT(key_b)) FROM dif_table WHERE dif <= ? AND success = 1"
        else:
            raise ValueError("Tertiem Non Datur")

        self.debug_execute(stmt, (delta,))
        return self.sq_cur.fetchone()[0]

    def get_ith_diff_cluster(self,
                             index: int,
                             delta: float,
                             part_a: bool = True,
                             include_hash_match: bool = True,
                             include_deleted: bool = True) -> Tuple[str, List[Tuple[str, float]]]:
        """
        Function allows the retrieval of a specific cluster as opposed to all clusters like with `get_all_cluster`

        :param delta: The threshold for the difference
        :param part_a: Whether to get the count for partition a or partition b (part_b might be part_a if
        it was left empty)
        :param include_hash_match: Whether to include diffs of 0 that were a result of having matching hashes
        :param index: The index of the cluster to retrieve
        :param include_deleted: Whether to include deleted entries (files marked as deleted in the db)

        :raises IndexError: If the index is out of bounds and the hash couldn't be found.
        """
        if part_a and include_hash_match:
            stmt = "SELECT DISTINCT(key_a) FROM dif_table WHERE dif <= ? AND success IN (1, 2) LIMIT 1 OFFSET ?"
        elif part_a and not include_hash_match:
            stmt = "SELECT DISTINCT(key_a) FROM dif_table WHERE dif <= ? AND success = 1 LIMIT 1 OFFSET ?"
        elif not part_a and include_hash_match:
            stmt = "SELECT DISTINCT(key_b) FROM dif_table WHERE dif <= ? AND success IN (1, 2) LIMIT 1 OFFSET ?"
        elif not part_a and not include_hash_match:
            stmt = "SELECT DISTINCT(key_b) FROM dif_table WHERE dif <= ? AND success = 1 LIMIT 1 OFFSET ?"
        else:
            raise ValueError("Tertiem Non Datur")

        # Get the key
        self.debug_execute(stmt, (delta, index))
        res = self.sq_cur.fetchone()
        if res is None:
            raise IndexError("Index out of bound.")

        tgt_key = res[0]

        self.debug_execute("SELECT path FROM directory WHERE key = ?", (tgt_key,))
        tgt_path = self.sq_cur.fetchone()[0]

        if part_a and include_hash_match and include_deleted:
            stmt = ("SELECT dir.path, dif.dif "
                    "FROM dif_table AS dif JOIN directory AS dir ON dir.key = dif.key_b "
                    "WHERE dif.key_a = ? AND dif.dif <= ? AND dif.success IN (1, 2) "
                    "ORDER BY dir.file_Size DESC, dir.created ASC")
        elif part_a and include_hash_match and not include_deleted:
            stmt = ("SELECT dir.path, dif.dif "
                    "FROM dif_table AS dif JOIN directory AS dir ON dir.key = dif.key_b "
                    "WHERE dif.key_a = ? AND dif.dif <= ? AND dif.success IN (1, 2) AND dir.deleted = 0 "
                    "ORDER BY dir.file_Size DESC, dir.created ASC")
        elif part_a and not include_hash_match and include_deleted:
            stmt = ("SELECT dir.path, dif.dif "
                    "FROM dif_table AS dif JOIN directory AS dir ON dir.key = dif.key_b "
                    "WHERE dif.key_a = ? AND dif.dif <= ? AND dif.success = 1 "
                    "ORDER BY dir.file_Size DESC, dir.created ASC")
        elif part_a and not include_hash_match and not include_deleted:
            stmt = ("SELECT dir.path, dif.dif "
                    "FROM dif_table AS dif JOIN directory AS dir ON dir.key = dif.key_b "
                    "WHERE dif.key_a = ? AND dif.dif <= ? AND dif.success = 1 AND dir.deleted = 0 "
                    "ORDER BY dir.file_Size DESC, dir.created ASC")
        elif not part_a and include_hash_match and include_deleted:
            stmt = ("SELECT dir.path, dif.dif "
                    "FROM dif_table AS dif JOIN directory AS dir ON dir.key = dif.key_a "
                    "WHERE dif.key_b = ? AND dif.dif <= ? AND dif.success IN (1, 2) "
                    "ORDER BY dir.file_Size DESC, dir.created ASC")
        elif not part_a and include_hash_match and not include_deleted:
            stmt = ("SELECT dir.path, dif.dif "
                    "FROM dif_table AS dif JOIN directory AS dir ON dir.key = dif.key_a "
                    "WHERE dif.key_b = ? AND dif.dif <= ? AND dif.success IN (1, 2) AND dir.deleted = 0 "
                    "ORDER BY dir.file_Size DESC, dir.created ASC")
        elif not part_a and not include_hash_match and include_deleted:
            stmt = ("SELECT dir.path, dif.dif "
                    "FROM dif_table AS dif JOIN directory AS dir ON dir.key = dif.key_a "
                    "WHERE dif.key_b = ? AND dif.dif <= ? AND dif.success = 1 "
                    "ORDER BY dir.file_Size DESC, dir.created ASC")
        elif not part_a and not include_hash_match and not include_deleted:
            stmt = ("SELECT dir.path, dif.dif "
                    "FROM dif_table AS dif JOIN directory AS dir ON dir.key = dif.key_a "
                    "WHERE dif.key_b = ? AND dif.dif <= ? AND dif.success = 1 AND dir.deleted = 0 "
                    "ORDER BY dir.file_Size DESC, dir.created ASC")
        else:
            raise ValueError("Tertiem Non Datur")

        self.debug_execute(stmt, (tgt_key, delta))
        res = [(row[0], row[1]) for row in self.sq_cur.fetchall()]
        return tgt_path, res

    def get_max_cluster_size(self) -> int:
        """
        Get the maximum size of a given cluster. Is useful for the gui (in  case we have a lot of images)
        """
        max_a = "SELECT MAX(CNT) FROM (SELECT COUNT(key_b) AS CNT FROM dif_table GROUP BY key_a)"
        max_b = "SELECT MAX(CNT) FROM (SELECT COUNT(key_a) AS CNT FROM dif_table GROUP BY key_b)"

        self.debug_execute(max_a)
        res_a = self.sq_cur.fetchone()[0]
        self.debug_execute(max_b)
        res_b = self.sq_cur.fetchone()[0]

        if res_a is None:
            res_a = 0

        if res_b is None:
            res_b = 0

        return max(res_a, res_b)

    def drop_diff(self, threshold: float):
        """
        Drop all diffs above a certain threshold
        """
        self.debug_execute("DELETE FROM dif_table WHERE dif > ?", (threshold,))

    def get_dif_errors(self) -> Iterator[Tuple[str, Union[str, None], str]]:
        """
        Get all errors from the dif_table
        If an error was encountered loading image a, path b is None.

        :returns: Iterator which contains path a, path b and error.
        """
        # Get errors from dif table where issue was with image a
        self.debug_execute("SELECT da.path, dif.error "
                           "FROM dif_table AS dif "
                           "JOIN directory AS da ON da.key = dif.key_a WHERE dif.key_b = -1")

        for path, error in self.sq_cur.fetchall():
            yield path, None, from_b64(error)

        # Get errors where issue was with image b
        self.debug_execute("SELECT da.path, db.path, dif.error "
                           "FROM dif_table AS dif "
                           "JOIN directory AS da ON da.key = dif.key_a "
                           "JOIN directory AS db ON db.key = dif.key_b WHERE dif.success = 0")

        for path_a, path_b, error in self.sq_cur.fetchall():
            yield path_a, path_b, from_b64(error)