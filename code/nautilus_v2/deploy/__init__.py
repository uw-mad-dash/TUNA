
from omegaconf import DictConfig

from .cloudlab import setup as cloudlab_setup
from .resolvers import set_hydra_resolvers

__all__ = [
    'cloudlab_setup'
    'setup_node',
    'set_hydra_resolvers',
]

def setup_node(deploy_config: DictConfig, deploy_target: str) -> None:
    if deploy_target == 'cloudlab':
        cloudlab_setup(deploy_config, format_disk=False)
    else:
        raise NotImplementedError(f"Deploy target `{deploy_target}' is not supported, yet..")
