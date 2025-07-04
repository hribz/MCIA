import csv
import os
import shutil
import subprocess
from pathlib import Path

from logger import logger


def commands_to_shell_script(commands):
    assert commands is not None
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


def remove_file(file: str):
    if os.path.exists(file):
        os.remove(file)


def run(cmd, cwd, tag, env=dict(os.environ)) -> bool:
    logger.info(f"[{tag}] {commands_to_shell_script(cmd)}")
    if not os.path.exists(cwd):
        logger.error(f"[{tag}] Please make sure {cwd} exists!")
        return False
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    while True:
        output = process.stdout.readline()
        if output == "" and process.poll() is not None:
            break
        if output:
            print(output.strip())

    if process.returncode == 0:
        return True
    else:
        logger.error(f"[{tag}] {commands_to_shell_script(cmd)} failed!")
        return False


def run_without_check(cmd, cwd, tag, env=dict(os.environ)) -> bool:
    makedir(cwd)
    logger.info(f"[{tag}] {commands_to_shell_script(cmd)}")
    if not os.path.exists(cwd):
        logger.error(f"[{tag}] Please make sure {cwd} exists!")
        return False
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    while True:
        output = process.stdout.readline()
        if output == "" and process.poll() is not None:
            break
        if output:
            print(output.strip())
    return process.returncode == 0


def add_to_csv(datas, csv_file, write_headers: bool = True):
    makedir(os.path.dirname(csv_file))
    if len(datas) == 0:
        return
    fieldnames = datas[0].keys()
    if not write_headers and os.path.exists(csv_file):
        with open(csv_file, "r") as f:
            origin_headers = f.readlines()[0].strip().split(",")
            if len(origin_headers) > len(fieldnames):
                fieldnames = origin_headers
    with open(csv_file, "w" if write_headers else "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_headers:
            writer.writeheader()
        for data in datas:
            data = {h: data.get(h, "Skipped") for h in fieldnames}
            writer.writerow(data)


def combine_csv(from_csv, to_csv, first_in):
    assert os.path.exists(from_csv), f"{from_csv} does not exist!"
    with open(from_csv, "r") as from_file:
        with open(to_csv, "w" if first_in else "a") as to_file:
            if first_in:
                to_file.writelines(from_file.readlines())
            else:
                to_file.writelines(from_file.readlines()[1:])
