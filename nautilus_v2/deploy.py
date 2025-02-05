import logging
import os
import subprocess
import sys
from pathlib import Path

import docker
import hydra
import yaml
from hydra.core.hydra_config import HydraConfig
from omegaconf import OmegaConf, DictConfig

from deploy import setup_node, set_hydra_resolvers
from deploy.utils import get_host_id
from nautilus.config import CONFIG_FILENAME
from nautilus.utils import update_environ

docker_client = docker.from_env()

CURRENT_DIR = Path(__file__).parent.resolve()
SETUP_LOCK_FILE = CURRENT_DIR / ".setup.lock"
NAUTILUS_DIR = CURRENT_DIR / "nautilus"

operation = None
nodetype = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def store_config(
    config: DictConfig,
) -> None:
    """Store the deploy configuration to a file.

    This function is called *only* from deploy.py script.
    """
    # Assemble config path & write config to file
    directory = Path(__file__).parent / "nautilus"
    config_path = directory / CONFIG_FILENAME

    config_dict = OmegaConf.to_container(config, resolve=True)
    with open(config_path, "w") as f:
        yaml.dump(config_dict, f)
    logger.info(f"Saved config @ {config_path}")


class NautilusControl:
    ENV_EXTRA = {
        # docker compose: This is used a prefix to docker containers & networks
        "COMPOSE_PROJECT_NAME": "deploy",
    }

    # Docker compose file names
    BASE_DOCKERFILE_FILENAME = "compose.yaml"
    HEAD_DOCKERFILE_FILENAME = "compose.ray-head.yaml"
    WORKER_DOCKERFILE_FILENAME = "compose.ray-worker.yaml"

    def __init__(self, profile_dir: Path, node_type: str):
        self.profile_dir = profile_dir
        base_dockerfile_filepath = profile_dir / self.BASE_DOCKERFILE_FILENAME

        # Set the docker-compose file paths
        if node_type == "head":
            dockerfile_filepath = profile_dir / self.HEAD_DOCKERFILE_FILENAME
        elif node_type == "worker":
            dockerfile_filepath = profile_dir / self.WORKER_DOCKERFILE_FILENAME
        else:
            raise ValueError(f"Invalid node type [{node_type}]")
        logger.info(
            f"Using dockerfile [{dockerfile_filepath}] (extends {base_dockerfile_filepath})"
        )

        self.env = {**os.environ.copy(), **self.ENV_EXTRA}
        self.docker_cmd = (
            f"docker compose -f {base_dockerfile_filepath} -f {dockerfile_filepath}"
        )

    def build(self):
        """Builds the container"""
        cmd = f"{self.docker_cmd} build"
        subprocess.run(cmd, shell=True, check=True, env=self.env, cwd=CURRENT_DIR)

    def launch(self):
        """Launches the container"""
        logger.info("Launching...")
        cmd = (
            f"{self.docker_cmd} config && " f"{self.docker_cmd} up --force-recreate -d"
        )
        subprocess.run(cmd, shell=True, check=True, env=self.env, cwd=CURRENT_DIR)
        logger.info("Launched!")

    def shutdown(self, dbms_container_name: str):
        """Stops the container"""
        try:
            # Kill db container (if exists)
            dbms_container = docker_client.containers.get(dbms_container_name)
            dbms_container.stop(timeout=1)
        except:  # noqa: E722
            pass

        cmd = f"{self.docker_cmd} down"
        subprocess.run(cmd, shell=True, check=True, env=self.env, cwd=CURRENT_DIR)
        logger.info("Stopped")


@hydra.main(version_base=None, config_path="config", config_name="config")
def main(config: DictConfig) -> None:

    # Resolve config
    logger.debug(OmegaConf.to_yaml(config, resolve=False))

    set_hydra_resolvers(CURRENT_DIR)
    OmegaConf.resolve(config)

    logger.info(f"\n{OmegaConf.to_yaml(config, resolve=True)}")

    # Update env-vars
    extra_env_vars = {
        "HOST_ID": get_host_id(),
        "NAUTILUS_DIR": NAUTILUS_DIR,
    }
    update_environ(config.env, extra=extra_env_vars)

    # Execute setup script (if first time or failed previously)
    if not SETUP_LOCK_FILE.exists():
        logger.info("First time setup...")
        try:
            deploy_target = HydraConfig.get().runtime.choices.deploy
            setup_node(config.deploy, deploy_target)
        except Exception as err:
            logger.error(f"Error during setup: {repr(err)}")
            sys.exit(1)
        else:
            SETUP_LOCK_FILE.touch()

    # Create launcher
    global operation, nodetype
    profile_dir = NAUTILUS_DIR / "profile"
    control = NautilusControl(profile_dir, nodetype)

    if operation in ["start", "build"]:
        # Store deploy config
        # NOTE: This config is read by the docker container at runtime
        store_config(config)

        # Building docker image
        logger.info(f"Building {nodetype.upper()}...")
        control.build()
        logger.info("Finished building!")

    if operation == "start":
        # Launching
        logger.info(f"Launching {nodetype.upper()}...")
        control.launch()
        logger.info("Finished launching!")

    elif operation == "stop":
        # Shutdown-ing..
        logger.info(f"Shutting down {nodetype.upper()}...")
        control.shutdown(config.dbms.docker_container_name)
        logger.info("Finished shutting down!")


if __name__ == "__main__":
    # Usage: python3 deploy.py <operation> <nodetype> ...hydra config-args...
    #           <operation> = {start, stop}
    #           <nodetype>  = {head, worker}
    operations = {"start", "stop", "build"}
    node_types = {"head", "worker"}

    try:
        assert len(sys.argv) >= 3
        operation, nodetype = sys.argv[1], sys.argv[2]
        assert operation in operations
        assert nodetype in node_types
    except:  # noqa: E722
        print(
            "\n"
            "Usage: python3 deploy.py <depoy_operation> <ray_nodetype> ...hydra args...\n"
            "        <deploy_operation> = {build, start, stop}\n"
            "        <ray_nodetype>  = {head, worker}\n\n"
            "E.g. python3 deploy.py start head deploy=cloudlab +deploy/instance_type=c220g5\n\n"
        )
        sys.exit(1)

    sys.argv.pop(2)  # remove nodetype from args
    sys.argv.pop(1)  # remove operation from args

    main()  # pylint: disable=E1120
