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

def run(cmd, cwd, tag, env=dict(os.environ)) -> bool:
    logger.info(f"[{tag}] {commands_to_shell_script(cmd)}")
    if not os.path.exists(cwd):
        logger.error(f"[{tag}] Please make sure {cwd} exists!")
        return False
    process = subprocess.Popen(cmd, cwd=cwd, stdout=None, stderr=None, env=env)
    return_code = process.wait()
    if return_code == 0:
        return True
    else:
        # Do something
        logger.error(f"[{tag}] {commands_to_shell_script(cmd)} failed!\nstdout: {process.stdout}\nstderr: {process.stderr}")
        return False
    
def run_without_check(cmd, cwd, tag, env=dict(os.environ)) -> bool:
    makedir(cwd)
    logger.info(f"[{tag}] {commands_to_shell_script(cmd)}")
    if not os.path.exists(cwd):
        logger.error(f"[{tag}] Please make sure {cwd} exists!")
        return False
    process = subprocess.Popen(cmd, cwd=cwd, stdout=None, stderr=None, env=env)
    return_code = process.wait()
    if return_code != 0:
        logger.error(f"[{tag}] {commands_to_shell_script(cmd)} failed!\nstdout: {process.stdout}\nstderr: {process.stderr}")
    return return_code == 0