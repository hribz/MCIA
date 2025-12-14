import argparse
import json
import os
import sys

from git import Repo

from project import *
from project_info import ProjectInfo
from utils import *


def clone_project(repo_name: str, repo_dir) -> bool:
    try:
        logger.info(f"[Clone Project] cloning repository {repo_name}")
        # repo_dir exist and not empty.
        if os.path.exists(repo_dir):
            dir_list = os.listdir(repo_dir)
            if os.path.exists(repo_dir) and len(dir_list) > 0 and dir_list != [".git"]:
                logger.info(f"[Clone Project] repository {repo_dir} already exists.")
                return True
        remake_dir(Path(repo_dir))
        Repo.clone_from(
            f"https://github.com/{repo_name}.git",
            repo_dir,
            multi_options=["--recurse-submodules"],
        )
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


def handle_project(projects, opts):
    pwd = os.path.abspath(".")
    projects_root_dir = os.path.join(pwd, "expriments")

    for project in projects:
        if (
            opts.repo
            and opts.repo != project["project"]
            and opts.repo != os.path.basename(project["project"])
        ):
            continue
        if "config_options" not in project:
            continue
        project_info = ProjectInfo(projects_root_dir, project)

        if not clone_project(project_info.repo_name, project_info.src_dir):
            continue
        if not checkout_target_commit(project_info.src_dir, project_info.commit):
            continue
        workspace_tag = (opts.tag if opts.tag else opts.inc)
        workspace = f"{project_info.src_dir}_workspace/{workspace_tag}"

        # hash_workspace = workspace + "_hash"
        # logger.start_log(hash_workspace)
        # p = Project(workspace=hash_workspace, opts=opts, project_info=project_info)
        # p.determine_chosen_configurations()

        logger.start_log(workspace)
        tp = Project(workspace=workspace, opts=opts, project_info=project_info)
        # tp.determine_chosen_configurations(p.chosen_config_list)
        tp.clean_before_analysis()
        tp.determine_chosen_configurations()
        # tp.process_every_configuration()
        # tp.clean_workspace_preprocess(tp.config_list)
        with open(tp.workspace + "/chosen_config.json", "w") as f:
            json.dump(
                [config.tag for config in tp.chosen_config_list], f, indent=3
            )


class MCArgumentParser:
    def __init__(self):
        self.parser = argparse.ArgumentParser()
        self.parser.add_argument(
            "--repo", type=str, dest="repo", help="Only analyse specific repos."
        )
        self.parser.add_argument(
            "--verbose",
            action="store_true",
            dest="verbose",
            help="Record debug information.",
        )
        self.parser.add_argument(
            "--cc",
            type=str,
            dest="cc",
            default="clang",
            help="Customize the C compiler for configure & build.",
        )
        self.parser.add_argument(
            "--cxx",
            type=str,
            dest="cxx",
            default="clang++",
            help="Customize the C++ compiler for configure & build.",
        )
        self.parser.add_argument(
            "--preprocess-only",
            dest="prep_only",
            action="store_true",
            help="Only preprocess and diff",
        )
        self.parser.add_argument(
            "--inc",
            type=str,
            dest="inc",
            choices=["noinc", "file", "func", "all"],
            default="func",
            help="Incremental analysis mode: noinc, file, func, all",
        )
        self.parser.add_argument(
            "--tag", type=str, dest="tag", help="Tag of this analysis."
        )
        self.parser.add_argument(
            "--file-identifier",
            type=str,
            dest="file_identifier",
            choices=["file", "target"],
            default="file name",
            help="Identify analysis unit by file or target.",
        )
        self.parser.add_argument(
            "--clean-cache",
            action="store_true",
            dest="clean_cache",
            help="Clean the cache before analysis.",
        )
        self.parser.add_argument(
            "--clean-preprocess-cache",
            action="store_true",
            dest="clean_preprocess_cache",
            help="Clean the preprocess files before analysis.",
        )
        self.parser.add_argument(
            "--basic-info",
            action="store_true",
            dest="basic_info",
            help="Extract the basic project info.",
        )
        self.parser.add_argument(
            "--only-process-reports",
            dest="only_process_reports",
            action="store_true",
            help="Only postprocess reports",
        )
        self.parser.add_argument(
            "--skip_prepare",
            dest="skip_prepare",
            action="store_true",
            help="Skip prepare compilation database",
        )
        # Strategy and sampling controls
        self.parser.add_argument(
            "--strategy",
            type=str,
            dest="strategy",
            choices=["preset", "random-space", "twise", "pairwise-explicit", "adaptive"],
            default="random-space",
            help="Configuration selection strategy: preset, random-space, twise, pairwise-explicit (2-option only), or adaptive (incremental complexity).",
        )
        self.parser.add_argument(
            "--t-wise",
            type=int,
            dest="t_wise",
            default=2,
            help="t value for t-wise (interaction) sampling when --strategy twise (default 2 = pairwise).",
        )
        self.parser.add_argument(
            "--candidate-size",
            type=int,
            dest="candidate_size",
            default=5,
            help="Number of random candidates evaluated per round when using random-space strategy.",
        )
        self.parser.add_argument(
            "--stop-threshold",
            type=int,
            dest="stop_threshold",
            default=0,
            help="Stop when the max distance in a round is <= this value for N consecutive rounds.",
        )
        self.parser.add_argument(
            "--stop-patience",
            type=int,
            dest="stop_patience",
            default=3,
            help="Number of consecutive low-distance rounds (<= threshold) before stopping in random-space strategy.",
        )
        self.parser.add_argument(
            "--random-seed",
            type=int,
            dest="random_seed",
            default=0,
            help="Seed for deterministic candidate sampling when using random-space strategy.",
        )
        self.parser.add_argument(
            "--max-round-retries",
            type=int,
            dest="max_round_retries",
            default=3,
            help="Maximum consecutive failed sampling rounds before aborting random-space strategy.",
        )
        self.parser.add_argument(
            "--max-random-options",
            type=int,
            dest="max_random_options",
            default=3,
            help="Upper bound on how many distinct options are toggled per random candidate.",
        )
        self.parser.add_argument(
            "--max-rounds",
            type=int,
            dest="max_rounds",
            default=10,
            help="Maximum random-space sampling rounds before stopping (0 disables the limit).",
        )
        self.parser.add_argument(
            "--max-configs",
            type=int,
            dest="max_configs",
            default=200,
            help="Maximum number of configurations to generate (for adaptive, twise, pairwise-explicit strategies).",
        )

    def parse_args(self, args):
        return self.parser.parse_args(args)


def main(args):
    parser = MCArgumentParser()
    opts = parser.parse_args(args)
    logger.verbose = opts.verbose
    projects = json.load(open("expriments/cleaned_options.json", "r"))
    handle_project(projects, opts)


if __name__ == "__main__":
    main(sys.argv[1:])
