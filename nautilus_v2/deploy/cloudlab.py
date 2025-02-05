
import logging
import os

from omegaconf import DictConfig

from .utils import run_command, setup_docker

logger = logging.getLogger(__name__)

def get_node_type() -> str:
    """ Get the type of the CloudLab node (e.g., c220g5). """
    with open('/var/emulab/boot/nodetype', 'r') as f:
        return f.read().strip()

def setup(config: DictConfig, format_disk: bool = False) -> None:
    """ Method to setup the CloudLab instance before deploying Nautilus. """

    logger.info('Setting up CloudLab instance...')
    user = os.environ.get('USER', None)
    assert user is not None, 'Environment variable `USER` is not set!'

    print(type(config), config)

    instance_type = config.instance_type.name
    disk_mount_point, disk_partition, disk_device = (
        config.instance_type.disk_mount_point,
        config.instance_type.disk_partition,
        config.instance_type.disk_device)

    msg = (f'Instance type: {instance_type}\n'
        f'Disk mount point: {disk_mount_point}\n'
        f'Disk partition: {disk_partition}\n'
        f'Disk device: {disk_device}\n')
    logger.info(msg)

    setup_docker(user)

    # Umount & clean
    logger.info('Unmounting & cleaning...')
    cmd = f'sudo umount {disk_mount_point} ; ' \
        f'sudo rm -rf {disk_mount_point}'
    run_command(cmd, check=True)

    lsblk_stdout = run_command(
        'lsblk -lp', capture_output=True, text=True, check=True).stdout
    partition_exists = disk_partition in lsblk_stdout

    if not partition_exists:
        # Create partition
        logger.debug(f'Creating partition [{disk_partition}] on disk [{disk_device}]...')
        cmd = _get_create_disk_partition_cmd(
            instance_type, disk_partition, disk_device)
        run_command(cmd, check=True)

        logger.info('Partition created!')
        format_disk = True

    run_command(f'sudo mkdir -p {disk_mount_point}', check=True)
    logger.debug('Mount point created!')

    if format_disk:
        # Format partition
        logger.debug(f'Formatting partition [{disk_partition}] on disk [{disk_device}]...')
        cmd = f'sudo mkfs -F -t ext4 {disk_partition}'
        run_command(cmd, check=True)

        logger.info('Partition formatted!')

    logger.debug('Mounting partition...')
    cmd = f'sudo mount -t ext4 {disk_partition} {disk_mount_point} && ' \
        f'sudo chown -R {user} {disk_mount_point}'
    run_command(cmd, check=True)
    logger.info('Partition mounted!')

    logger.info('Successfully setup CloudLab instance!')


def _get_create_disk_partition_cmd(instance_type, disk_partition, disk_device):
    try:
        assert disk_partition.startswith(disk_device)
        partition_num = int(disk_partition[len(disk_device):])
    except Exception as err:
        error_msg = f'Unknown partition number: ' \
                    f'device="{disk_device}", partition="{disk_partition}": {repr(err)}'
        raise Exception(error_msg) from err

    if instance_type == 'c220g5':
        return f'''(
            echo n;
            echo {partition_num};
            echo ;
            echo ;
            echo w;
            ) | sudo fdisk {disk_device}'''
    else:
        raise NotImplementedError(f"Creating partition on `{instance_type}' is not supported, yet..")

