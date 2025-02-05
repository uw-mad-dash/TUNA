import netifaces
from logging import getLogger
from omegaconf import OmegaConf
from pathlib import Path

logger = getLogger(__name__)

def set_hydra_resolvers(root_dirpath: Path):
    """ Register custom resolvers for Hydra """

    OmegaConf.register_new_resolver('local_ip', _get_local_ip)
    OmegaConf.register_new_resolver('project_dir', lambda: root_dirpath.as_posix())
    OmegaConf.register_new_resolver('cloudlab_instance_type_cfg', _get_cloudlab_instance_type_cfg)

def _get_local_ip(netifaces_pref: list):
    """ Returns the first IPv4 address from list of interfaces that are preferred """
    #global config

    if _get_local_ip.result:
        return _get_local_ip.result # memoization

    #for iface in config.deploy.netifaces_pref:
    for iface in netifaces_pref:
        try:
            addresses = netifaces.ifaddresses(iface)[netifaces.AF_INET]
        except Exception as err:
            logger.debug(f'Error while retrieving `{iface}` IP address: {str(err)}')
            continue

        _get_local_ip.result = addresses[0]['addr']
        logger.info(f'Found IPv4 address [{_get_local_ip.result}] of interface `{iface}`')
        break
    else:
        _get_local_ip.result = ''
        #logger.info(f'No IPv4 address found on interfaces `{config.deploy.netifaces_pref}`')

    return _get_local_ip.result

_get_local_ip.result = None

def _get_cloudlab_instance_type_cfg():
    """ Returns the instance type configuration for cloudlab

    Related Link: https://github.com/facebookresearch/hydra/discussions/2246
    """
    from deploy.cloudlab import get_node_type

    filename = f'{get_node_type()}.yaml'
    path = Path('./config/deploy/instance_type') / filename

    if not path.exists():
        raise FileNotFoundError(f'Cloudlab instance type config file [{filename}] not found.'
                                'Are you sure this instance type is supported?')
    return OmegaConf.load(path)
