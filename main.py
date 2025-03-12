import argparse
import json
import os
import sys
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
            Option("CMAKE_BUILD_TYPE", ["Release", "Debug"], OptionType.options, None, None)
        ]
    for option in options:
        ret.append(Option(option['key'], option['values'], OptionType.getType(option['kind']), option.get('conflict'), option.get('combination')))
    return ret

def get_if_exists(dict, key, default=None):
    return dict[key] if key in dict else default

def handle_project(projects, opts):
    pwd = os.path.abspath(".")
    projects_root_dir = os.path.join(pwd, "expriments")

    for project in projects:
        repo_name = project['project']
        build_type = BuildType.getType(project['build_type'])
        out_of_tree = get_if_exists(project, 'out_of_tree', True)
        # The options cannot be changed in this environment.
        constant_options = get_if_exists(project, 'constant_options', [])
        commit = project['shallow']
        options = project['config_options']
        prerequisites = get_if_exists(project, 'prerequisites', [])
        repo_dir = os.path.join(projects_root_dir, repo_name)

        if opts.repo and opts.repo != repo_name and opts.repo != os.path.basename(repo_dir):
            continue

        if not clone_project(repo_name, repo_dir):
            continue
        if not checkout_target_commit(repo_dir, commit):
            continue
        build_dir = f"{repo_dir}_build" if out_of_tree else repo_dir
        workspace = f"{repo_dir}_workspace/{opts.inc}"
        logger.start_log(workspace)
        p = Project(src_dir=repo_dir,
                    workspace=workspace,
                    build_dir=build_dir,
                    options=parse_options(options, build_type),
                    build_type=build_type,
                    constant_options=constant_options,
                    opts = opts,
                    prerequisites=prerequisites)
        p.process_every_configuraion()

class MCArgumentParser():
    def __init__(self):
        self.parser = argparse.ArgumentParser()
        self.parser.add_argument('--repo', type=str, dest='repo', help='Only analyse specific repos.')
        self.parser.add_argument('--verbose', action='store_true', dest='verbose', help='Record debug information.')
        self.parser.add_argument('--cc', type=str, dest='cc', default='clang-18', help='Customize the C compiler for configure & build.')
        self.parser.add_argument('--cxx', type=str, dest='cxx', default='clang++-18', help='Customize the C++ compiler for configure & build.')
        self.parser.add_argument('--preprocess-only', dest='prep_only', action='store_true', help='Only preprocess and diff')
        self.parser.add_argument('--inc', type=str, dest='inc', choices=['noinc', 'file', 'func'], default='func',
                                 help='Incremental analysis mode: noinc, file, func')
    
    def parse_args(self, args):
        return self.parser.parse_args(args)

def main(args):
    parser = MCArgumentParser()
    opts = parser.parse_args(args)
    projects = json.load(open('expriments/cleaned_options.json', 'r'))
    handle_project(projects, opts)

if __name__ == '__main__':
    main(sys.argv[1:])