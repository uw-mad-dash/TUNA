import logging
import os
import shutil
import subprocess
import traceback
from pathlib import Path

from nautilus.config import NautilusConfig
from omegaconf import DictConfig, OmegaConf

LINE_SEP = 50 * '='

logger = logging.getLogger(__name__)

def run_command(cmd: str, **kwargs) -> subprocess.CompletedProcess:
    logger.debug(f'Running command: `{cmd}`...')
    logger.debug(LINE_SEP)

    try:
        cp = subprocess.run(cmd, shell=True, **kwargs)
        if cp.returncode != 0:
            logger.warn(f'Non-zero code [{cp.returncode}] for command `{cmd}`')

    except Exception as err:
        logger.error(f'Exception raised: {repr(err)}')
        logger.error(f'Error while running command `{cmd}`')
        cp = None

    return cp

def clear_system_caches(level: int = 3) -> None:
    """ Clear the system caches by dropping the caches (level 1, 2, 3)
        - 1: free pagecache
        - 2: free dentries and inodes
        - 3: free pagecache, dentries and inodes
    """
    assert 1 <= level <= 3, f'Invalid level: {level}'
    cmd = f'sync;sync;sync ; echo {level} > /host_proc/sys/vm/drop_caches'
    run_command(cmd)

def disk_sync(container_name: str = None) -> None:
    """ Sync the disk """
    # Flush disk locally first
    os.sync() ; os.sync() ; os.sync()  # noqa: E702
    # Flush disk in the dbms container (optional)
    # NOTE: not sure if this is necessary :)
    if container_name is not None:
        run_command(f'docker exec {container_name} sync;sync;sync', check=True)

def update_environ(
    config: DictConfig,
    extra: dict[str, str] | None = None,
) -> None:
    """ Updates the environment variables of the system """
    env_vars = { **OmegaConf.to_container(config, resolve=True) }
    if extra is not None and isinstance(extra, dict):
        env_vars.update(extra)

    # Set environment variables
    logger.debug(f'Found {len(env_vars)} env-vars from config: {env_vars.keys()}')
    for k, v in env_vars.items():
        os.environ[k] = str(v)
        logger.debug(f'export {k}={os.environ[k]}')

def report_and_return_error(
    logger: logging.Logger,
    error: Exception,
    result: str,
    prefix: str ='UNEXPECTED ERROR'
) -> dict[str, str]:
    logger.exception(f'[{prefix}] @ {result}: {repr(error)}')
    return {
        'result': result,
        'error': str(repr(error)),
        'traceback': traceback.format_exc(),
    }


def erase_dir(dirpath: Path, ignore_errors=False, only_contents=False) -> None:
    logger.info(f"Erasing data from '{dirpath}' [only_contents={only_contents}]...")

    try:
        if not only_contents:
            shutil.rmtree(dirpath, ignore_errors=ignore_errors)
        else:
            for path in dirpath.iterdir():
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path, ignore_errors=ignore_errors)

    except Exception as err:
        error_message = ('Error while trying to erase folder contents '
                        f'@[{dirpath}]: {str(err)}')
        logger.error(error_message)
        # swallow exception because it causes issues with in memory databases otherwise

def trim_stream_output(s, stream_name: str):
    """ Trim the size of the stream output string. """
    if isinstance(s, str):
        return s

    limit = NautilusConfig.get().config.nautilus.max_output_chars[stream_name]
    if len(s) > limit:
        # trim to last XX characters
        s = s[-limit:]
        logger.debug(f'Trimmed [{stream_name}] to {limit} chars!')

    return s
