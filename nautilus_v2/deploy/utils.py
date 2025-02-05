import logging
import subprocess

logger = logging.getLogger(__name__)

LINE_SEP = 50 * '='

def run_command(cmd, reraise=True, **kwargs) -> subprocess.CompletedProcess | None:
    """ Run a shell command and return the completed process """
    logger.debug(f'Running command: `{cmd}`...')
    logger.debug(LINE_SEP)

    cp = None
    try:
        cp = subprocess.run(cmd, shell=True, **kwargs)
        if cp.returncode != 0:
            logger.warn(f'Non-zero code [{cp.returncode}] for command `{cmd}`')

    except Exception as err:
        logger.error(f'Exception raised: {repr(err)}')
        logger.error(f'Error while running command `{cmd}`')
        if reraise:
            raise

    return cp

def setup_docker(user: str):
    """ Provide user privileges to run docker commands without sudo
    and enable automatic docker service startup on system reboot.
    """
    logger.debug('Setting up docker...')
    # Avoid using sudo when running docker commands
    run_command(f'sudo usermod -aG docker {user}', check=True)
    # Launch docker even if restarted!
    run_command('sudo systemctl enable docker', check=True)
    logger.info('Docker setup complete')

def get_host_id() -> str:
    """ Returns the (sanitized) IP address or the hostname of the machine """
    try:
        # Cloudlab-specific
        with open('/var/emulab/boot/myip', 'r') as f:
            return f.read().replace('.','-').strip()
    except:  # noqa: E722
        pass
    finally:
        # Generally available
        import socket
        return socket.gethostname().replace('.','-').strip()
