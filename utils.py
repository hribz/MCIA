import subprocess
import os
import shutil
from pathlib import Path
from logger import logger

def commands_to_shell_script(commands):
    assert(commands is not None)
    from shlex import join
    return join(commands)

def makedir(path: str):
    if not os.path.exists(path):
        try:
            os.makedirs(path)
        except FileExistsError:  # may happen when multi-thread
            pass

def remake_dir(path: Path, debug_TAG=None):
    if path.exists():
        if debug_TAG:
            logger.debug(f"{debug_TAG} remove: {path}")
        shutil.rmtree(path)
    os.makedirs(path)

def run(cmd, cwd, tag) -> bool:
    makedir(cwd)
    try:
        logger.info(f"[{tag}] {commands_to_shell_script(cmd)}")
        process = subprocess.Popen(cmd, cwd=cwd, stdout=None, stderr=None, check=True)
        process.wait()
        return True
    except subprocess.CalledProcessError as e:
        return False
    
def run_without_check(cmd, cwd, tag) -> bool:
    makedir(cwd)
    logger.info(f"[{tag}] {commands_to_shell_script(cmd)}")
    process = subprocess.Popen(cmd, cwd=cwd, stdout=None, stderr=None)
    process.wait()
    return process.returncode == 0