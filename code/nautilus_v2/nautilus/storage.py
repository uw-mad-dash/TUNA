
import logging
from pathlib import Path

from nautilus.benchmarks import BenchmarkInfo
from nautilus.common import PathPair
from nautilus.dbms import DBMSInfo
from nautilus.utils import erase_dir


def get_directory_size(directory: Path) -> int:
    """ Returns the size of a directory (and its subdirectories) in bytes """
    return sum(p.stat().st_size for p in Path(directory).rglob('*'))


class DatabaseCacheEntry:

    def __init__(self,
        dbms_info: DBMSInfo,
        benchmark_info: BenchmarkInfo,
        data_dirpath: PathPair = None,
    ) -> None:
        self._dbms_info = dbms_info
        self._benchmark_info = benchmark_info

        if data_dirpath is not None:
            self._data_dirpath = data_dirpath
            data_dirpath.local.mkdir(exist_ok=False) # Create dir

    @property
    def dbms_info(self) -> DBMSInfo:
        return self._dbms_info

    @property
    def benchmark_info(self) -> BenchmarkInfo:
        return self._benchmark_info

    @property
    def data_dirpath(self) -> PathPair:
        return self._data_dirpath

    def __str__(self):
        return f'<DatabaseCacheEntry>\n\t'                  \
            f'DBMSInfo:\t{self.dbms_info}\n\t'              \
            f'BenchmarkInfo:\t{self.benchmark_info}\n\t'    \
            f'Host dirpath:\t{self.data_dirpath.host}\n\t'  \
            f'Local dirpath:\t{self.data_dirpath.local}\n\t'\
            f'Size (GiB):\t{get_directory_size(self.data_dirpath.local) / (2 ** 30):.3f}'

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return False

        # dbms info
        if self.dbms_info.name != other.dbms_info.name:
            return False
        if self.dbms_info.version != other.dbms_info.version:
            return False

        # benchmark info
        if type(self.benchmark_info) != type(other.benchmark_info):   # noqa: E721
            return False
        if self.benchmark_info.name != other.benchmark_info.name or \
            self.benchmark_info.workload != other.benchmark_info.workload:
            return False

        # benchmark_info.workload properties
        return self.benchmark_info.workload_properties == \
                    other.benchmark_info.workload_properties


class DatabaseStorageManager:
    def __init__(
        self,
        root_dirpath: PathPair,
        num_slots: int = 5,
        clear_dir: bool = True
    ) -> None:
        self.logger = logging.getLogger(__name__)

        self.root_dirpath = root_dirpath
        self.entries: dict[int, DatabaseCacheEntry] = {
            idx: None for idx in range(num_slots) }

        # LRU structures
        self.last_updated = { idx: None for idx in range(num_slots) }
        self.timestamp = 1

        # TODO: Support reusing existing entries from the root dirpath
        if clear_dir and root_dirpath.local.exists():
            erase_dir(root_dirpath.local, only_contents=True)
            self.logger.info(f'Erased root dir: {root_dirpath.local}')

        root_dirpath.local.mkdir(parents=True, exist_ok=True)
        assert root_dirpath.local.exists(), 'Root dirpath does not exist'
        assert root_dirpath.local.is_dir(), 'Root path is not a directory'

    def get_entry(
        self,
        dbms_info: DBMSInfo,
        benchmark_info: BenchmarkInfo
    ) -> PathPair | None:
        """ Get cached entry for given experiment info (if exists) """

        slot = self._find_entry_slot(dbms_info, benchmark_info)
        if slot is not None:
            entry = self.entries[slot]
            self._update_entry_timestamp(slot)
            self.logger.info(f'Found entry [slot={slot}]: {entry}')
            return entry.data_dirpath

        self.logger.info('No entry found :(')
        return None

    def allocate_entry(
        self,
        dbms_info: DBMSInfo,
        benchmark_info: BenchmarkInfo
    ) -> PathPair:
        """ Allocate a new entry for given experiment info """
        # Find next available slot
        free_slot = None
        for slot, entry in self.entries.items():
            if entry is None:
                free_slot = slot
                break

        # If no slot available, evict oldest entry
        if free_slot is None:
            free_slot = self._evict_lru_entry()

        # Allocate entry
        data_dirpath = PathPair(
            host=self.root_dirpath.host / str(free_slot),
            local=self.root_dirpath.local / str(free_slot),
        )
        entry = DatabaseCacheEntry(dbms_info, benchmark_info, data_dirpath=data_dirpath)
        self.entries[free_slot] = entry
        self._update_entry_timestamp(free_slot)

        self.logger.info(f'Allocated entry [slot={free_slot}]: {entry}')
        return entry.data_dirpath

    def evict_entry(
        self,
        dbms_info: DBMSInfo,
        benchmark_info: BenchmarkInfo
    ) -> bool:
        """ Evict entry for given experiment info (if exists) """
        slot = self._find_entry_slot(dbms_info, benchmark_info)
        if slot is None: # entry not found
            self.logger.warning(f'Entry not found for eviction: {dbms_info} - {benchmark_info}')
            return False

        # Perform eviction
        self._internal_evict_entry(slot)
        return True

    def _evict_lru_entry(self) -> int:
        """ Evict the least recently used entry """
        evict_slot, least_ts = None, None
        for slot, entry in self.entries.items():
            assert entry is not None, 'Entry is None but slot is occupied'

            if (least_ts is None) or (least_ts > self.last_updated[slot]):
                least_ts = self.last_updated[slot]
                evict_slot = slot

        assert evict_slot is not None

        # Perform eviction
        self._internal_evict_entry(evict_slot)
        return evict_slot

    def _find_entry_slot(
        self,
        dbms_info: DBMSInfo,
        benchmark_info: BenchmarkInfo
    ) -> int | None:
        # Iterate through existing entries
        new_entry = DatabaseCacheEntry(dbms_info, benchmark_info)
        for slot, entry in self.entries.items():
            if entry == new_entry:
                return slot
        return None

    def _internal_evict_entry(self, slot: int) -> None:
        entry = self.entries[slot]
        self.logger.info(f'Evicting entry [slot={slot}]: {entry}')

        local_data_dirpath = entry.data_dirpath.local
        assert local_data_dirpath.exists(), \
            'Entry is allocated but no datadir exists'

        # Delete entry contents
        erase_dir(local_data_dirpath, ignore_errors=True)
        assert not local_data_dirpath.exists(), \
            'Datadir was supposed to be deleted but still exists in file system'

        # Update data structures
        self.entries[slot] = None
        self.last_updated[slot] = None
        self.logger.info('Entry evicted successfully! :)')

    def _update_entry_timestamp(self, slot: int) -> None:
        """ Update the timestamp for the given slot """
        self.last_updated[slot] = self.timestamp
        self.timestamp += 1


"""
# TODO: Move the following to a test file
if __name__ == '__main__':
    from nautilus.dbms import DBMSInfo
    from nautilus.benchmarks import OLTPBenchInfo, YCSBBenchmarkInfo
    from nautilus.benchmarks.oltpbench import OLTPBenchWorkloadProperties

    import logging
    logging.basicConfig(level=logging.DEBUG)

    rootpath = Path('/tmp/nautilus')
    sm = DatabaseStorageManager(rootpath, rootpath, num_slots=3)

    bi1 = OLTPBenchInfo('oltpbench', 'ycsbA', 30, 300,
        OLTPBenchWorkloadProperties(20, 40, 'unlimited'))

    # get -- no entry
    db1 = DBMSInfo('postgres', {'aaa': 11})
    assert sm.get_entry(db1, bi1) == (None, None)
    # allocate + get
    db1_path, _ = sm.allocate_entry(db1, bi1)
    assert db1_path == rootpath / '0'
    db1_path_get, _ = sm.get_entry(db1, bi1)
    assert  db1_path_get == db1_path
    # similar dbms info to db1
    db1_similar = [
        DBMSInfo('postgres', None),
        DBMSInfo('postgres', {'bbb': 222})
    ]
    for db1_ in db1_similar:
        db1_similar_path, _ = sm.get_entry(db1_, bi1)
        assert db1_similar_path == db1_path

    # get -- no entry
    db2 = DBMSInfo('cassandra', {'aaa': 11})
    assert sm.get_entry(db2, bi1) == (None, None)
    # allocate + get
    db2_path, _ = sm.allocate_entry(db2, bi1)
    assert db2_path == rootpath / '1'
    db2_path_get, _ = sm.get_entry(db2, bi1)
    assert  db2_path_get == db2_path
    db2_similar = [
        DBMSInfo('cassandra', None),
        DBMSInfo('cassandra', {'aaa': 11})
    ]
    for db2_ in db2_similar:
        db2_similar_path, _ = sm.get_entry(db2_, bi1)
        assert db2_similar_path == db2_path


    # get entry for similar benchmark infos
    bi1_similar = [
        OLTPBenchInfo('oltpbench', 'ycsbA', 3, 300, OLTPBenchWorkloadProperties(20, 40, 'unlimited')),
        OLTPBenchInfo('oltpbench', 'ycsbA', 30, 3, OLTPBenchWorkloadProperties(20, 40, 'unlimited')),
        OLTPBenchInfo('oltpbench', 'ycsbA', 30, 300, OLTPBenchWorkloadProperties(20, 1, 'unlimited')),
        OLTPBenchInfo('oltpbench', 'ycsbA', 30, 300, OLTPBenchWorkloadProperties(20, 40, 1000)),
        OLTPBenchInfo('oltpbench', 'ycsbA', 1, 1, OLTPBenchWorkloadProperties(20, 1, 1)),
    ]
    for bi1_ in bi1_similar:
        db1_similar_path, _ = sm.get_entry(db1, bi1_)
        assert db1_similar_path == db1_path
        db2_similar_path, _ = sm.get_entry(db2, bi1_)
        assert db2_similar_path == db2_path

    # get -- no entry
    bi2 = OLTPBenchInfo('oltpbench', 'tpcc', 30, 300,
        OLTPBenchWorkloadProperties(1, 40, 'unlimited'))
    assert sm.get_entry(db1, bi2) == (None, None)
    # allocate + get
    db1_bi2_path, _ = sm.allocate_entry(db1, bi2)
    assert db1_bi2_path == rootpath / '2'
    db1_bi2_path_get, _ = sm.get_entry(db1, bi2)
    assert db1_bi2_path == db1_bi2_path_get
    assert sm.get_entry(db2, bi2) == (None, None)

    # get -- no entry
    bi3 = OLTPBenchInfo('oltpbench', 'tpcc', 30, 300,
        OLTPBenchWorkloadProperties(100, 40, 'unlimited'))
    assert sm.get_entry(db1, bi3) == (None, None)

    # check evict
    ## update entries 0 + 2, to force entry 1 to be the oldest
    sm.get_entry(db1, bi1)[0] == db1_path
    sm.get_entry(db1, bi2)[0] == db1_bi2_path
    db1_bi3_path, _ = sm.allocate_entry(db1, bi3)
    assert sm.get_entry(db1, bi3)[0] == db1_bi3_path
    assert sm.get_entry(db2, bi1) == (None, None) # evicted


    assert sm.get_entry(db2, bi3) == (None, None)
    db2_bi3_path, _ = sm.allocate_entry(db2, bi3)
    assert sm.get_entry(db2, bi3)[0] == db2_bi3_path
    assert sm.get_entry(db1, bi1) == (None, None) # evicted
"""