import subprocess


def run_command_simple(cmd: list[str], shell=False):
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        text=True,
        shell=shell
    )
