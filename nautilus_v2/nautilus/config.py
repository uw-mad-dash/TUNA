import logging
import uuid
import yaml
from datetime import datetime
from functools import cached_property
from pathlib import Path

from omegaconf import OmegaConf, DictConfig

from nautilus.common import PathPair

# Define the default config file name
# NOTE: if you change this, make sure to update the Dockerfile as well
CONFIG_FILENAME = 'deploy-config.yaml'

logger = logging.getLogger(__name__)

class NautilusConfig:
    """ Loads deployed configuration and provides methods to access useful local/host paths.

    This class is initialized *only* once, from Ray actors/tasks inside the container.
    """
    __instance = None

    # Local path (i.e. inside docker) of Nautilus' image build directory
    IMAGE_BUILD_DIRECTORY = Path('/nautilus')

    def __init__(self):
        raise RuntimeError('Call get() instead')

    def create_local_dirs(self) -> None:
        """ Create local directories if they do not exist. """
        paths = self._get_local_dirs()
        for path in paths:
            path.mkdir(parents=True, exist_ok=True)
        logger.info('Local directories created!')

    def cleanup_local_dirs(self) -> None:
        """ Cleanup local directories. """
        from nautilus.utils import erase_dir

        paths = [d for d in  self._get_local_dirs() if d != self.empty_dir.local]
        raised = False
        for path in paths:
            # Erase folder contents, if it is not the temporary directory
            only_contents = self.temp_dirname is None
            try:
                erase_dir(path, only_contents=only_contents)
            except Exception as err:
                logger.error(f"Error while cleaning up '{path}': {err}")
                raised = True

        if raised:
            logger.warming('Some local directories could not be cleaned up! :/')
        else:
            logger.info('Local directories cleaned up!')

    @cached_property
    def dbms(self) -> DictConfig:
        """ DBMS config properties """
        return OmegaConf.to_container(self.config.dbms, resolve=True)

    @cached_property
    def deploy(self) -> DictConfig:
        """ Deploy config properties """
        return OmegaConf.to_container(self.config.deploy, resolve=True)

    @cached_property
    def workspace_dir(self) -> PathPair:
        """ Nautilus workspace directory (e.g., '/tmp/nautilus-workspace/' on host). """
        pair = PathPair(
            host=Path(self.config.deploy.workspace_mount_point),
            local=Path(self.config.nautilus.workspace_mount_point),
        )
        pair = self._append_temp_dirpath(pair)
        return pair

    @cached_property
    def disk_backup_mount_point(self) -> PathPair:
        """ Mounted disk backup mount point (e.g., '/mnt/ssd/backup/' on host). """
        pair = PathPair(
            host=Path(self.config.deploy.instance_type.disk_backup_mount_point),
            local=Path(self.config.nautilus.disk_backup_mount_point),
        )
        pair = self._append_temp_dirpath(pair)
        return pair

    @cached_property
    def disk_mount_point(self) -> PathPair:
        """ Mounted disk mount point (e.g., '/mnt/ssd/' on host). """
        pair = PathPair(
            host=Path(self.config.deploy.instance_type.disk_mount_point),
            local=Path(self.config.nautilus.disk_mount_point),
        )
        pair = self._append_temp_dirpath(pair)
        return pair

    @cached_property
    def empty_dir(self) -> PathPair:
        """ Empty directory to be used as a placeholder for the init db dir of DBMS compose.yaml.

        NOTE: We create an empty dir inside the workspace, when we do not use the init-db dir.
        """
        pair = PathPair(
            host=self.workspace_dir.host / 'empty-dir',
            local=self.workspace_dir.local / 'empty-dir',
        )
        return pair

    def _append_temp_dirpath(self, pair: PathPair) -> PathPair:
        """ Append temporary directory name to the path pair (if any). """
        if self.temp_dirname is None:
            return pair
        return PathPair(
            host=pair.host / self.temp_dirname,
            local=pair.local / self.temp_dirname)

    @classmethod
    def get(cls) -> 'NautilusConfig':
        """ Get the singleton instance. """
        assert cls.__instance is not None, 'NautilusConfig not initialized!'
        return cls.__instance

    @classmethod
    def init(cls, use_temp_directory: bool = True) -> 'NautilusConfig':
        """ Inits the singleton instance.
        NOTE: This method should be called only once.
        """
        assert cls.__instance is None, 'NautilusConfig already initialized!'
        cls.__instance = cls.__new__(cls)

        cls.__instance._init_instance(use_temp_directory=use_temp_directory)
        return cls.get()

    def _init_instance(self, use_temp_directory: bool = True) -> None:
        """ Creates the singleton instance. """
        self.config = self._load_from_directory(self.IMAGE_BUILD_DIRECTORY)
        self.temp_dirname = None

        temp_dirname = None
        if use_temp_directory:
            now = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            temp_dirname = f'{now}_{uuid.uuid4().hex[:8]}'
            logger.info(f'Generated temporary dirname: {temp_dirname}')
        self.temp_dirname = temp_dirname

    @staticmethod
    def _load_from_directory(directory: Path,) -> DictConfig:
        """ Reads config file previously written by deploy script """

        def read_config(filepath: Path) -> DictConfig:
            with open(filepath, 'r') as f:
                config_dict = yaml.load(f, Loader=yaml.FullLoader)
            return OmegaConf.create(config_dict)

        # Assemble config path
        config_path = directory / CONFIG_FILENAME

        try:
            config = read_config(config_path)
        except FileNotFoundError as err:
            logger.error(f'ERROR: Config file not found: {err}'
                        'Make sure to run the deploy script first!')
            raise

        logger.info(f'Read configuration from {config_path.as_posix()}')
        return config

    def _get_local_dirs(self) -> list[Path]:
        """ Returns a list of local directories to be created/cleaned."""
        return [
            self.workspace_dir.local,
            self.disk_mount_point.local,
            self.disk_backup_mount_point.local,
            self.empty_dir.local,
        ]
