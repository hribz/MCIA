import argparse
import json
import os
from git import Repo

from project import *
from utils import *

def clone_project(repo_name: str, repo_dir) -> bool:
    try:
        logger.info(f"[Clone Project] cloning repository {repo_name}")
        # repo_dir exist and not empty.
        if os.path.exists(repo_dir):
            dir_list = os.listdir(repo_dir)
            if os.path.exists(repo_dir) and len(dir_list) > 0 and dir_list != ['.git']:
                logger.info(f"[Clone Project] repository {repo_dir} already exists.")
                return True
        remake_dir(Path(repo_dir))
        Repo.clone_from(f"https://github.com/{repo_name}.git", repo_dir, multi_options=['--recurse-submodules'])
        return True
    except Exception as e:
        # clone error, repository no longer exists
        logger.error(f"[Clone Project] repository {repo_dir} cannot be cloned.\n{e}")
        return False

def checkout_target_commit(repo_dir: str, commit: str) -> bool:
    assert os.path.isabs(repo_dir)
    repo = Repo(repo_dir)

    try:
        repo.git.checkout(commit)
        return True

    except Exception as e:
        logger.error(f"error while checking out commit.\n{e}")
        return False

def parse_options(options, build_type):
    ret = []
    if build_type == BuildType.CMake:
        ret = [
            Option("CMAKE_BUILD_TYPE", ["Release", "Debug"])
        ]
    for option, values in enumerate(options):
        ret.append(Option(option, values))
    return ret

def handle_project(projects):
    pwd = os.path.abspath(".")
    projects_root_dir = os.path.join(pwd, "expriments")

    for project in projects:
        repo_name = project['project']
        build_type = BuildType.getType(project['build_type'])
        commit = project['shallow']
        options = project['config_options'
                          ]
        repo_dir = os.path.join(projects_root_dir, repo_name)
        if not clone_project(repo_name, repo_dir):
            continue
        if not checkout_target_commit(repo_dir, commit):
            continue
        build_dir = f"{repo_dir}_build"
        workspace = f"{repo_dir}_workspace"
        p = Project(workspace=workspace,
                    build_dir=build_dir,
                    options=parse_options(options, build_type),
                    build_type=build_type)
        p.process_every_configuraion()

class MCArgumentParser():
    def __init__(self):
        self.parser = argparse.ArgumentParser()
        pass

def main():
    parser = MCArgumentParser()
    projects = json.load('expriments/benchmark.json')
    handle_project(projects)

if __name__ == '__main__':
    main()