import argparse
import json
import os
import sys

from project import Project, Configuration
from project_info import ProjectInfo

def handle_project(projects, opts):
    pwd = os.path.abspath(".")
    projects_root_dir = os.path.join(pwd, "expriments")

    for project in projects:
        if opts.repo and opts.repo != project['project'] and opts.repo != os.path.basename(project['project']):
            continue
        project_info = ProjectInfo(projects_root_dir, project)

        workspace_tag = opts.tag if opts.tag else opts.inc
        workspace = f"{project_info.src_dir}_workspace/{workspace_tag}"

        p = Project(workspace=workspace,
                    opts=opts,
                    project_info=project_info)
        
        for config in p.config_list:
            p.prepare_compilation_database(config)


class PSArgumentParser():
    def __init__(self):
        self.parser = argparse.ArgumentParser()
        self.parser.add_argument('--repo', type=str, dest='repo', help='Only analyse specific repos.')
        self.parser.add_argument('--verbose', action='store_true', dest='verbose', help='Record debug information.')
        self.parser.add_argument('--cc', type=str, dest='cc', default='clang-18', help='Customize the C compiler for configure & build.')
        self.parser.add_argument('--cxx', type=str, dest='cxx', default='clang++-18', help='Customize the C++ compiler for configure & build.')
        self.parser.add_argument('--preprocess-only', dest='prep_only', action='store_true', help='Only preprocess and diff')
        self.parser.add_argument('--inc', type=str, dest='inc', choices=['noinc', 'file', 'func'], default='func',
                                 help='Incremental analysis mode: noinc, file, func')
        self.parser.add_argument('--tag', type=str, dest='tag', help='Tag of this analysis.')
        self.parser.add_argument('--file-identifier', type=str, dest='file_identifier', choices=['file', 'target'], default='file name', 
                                 help='Identify analysis unit by file or target.')
    
    def parse_args(self, args):
        return self.parser.parse_args(args)

def main(args):
    parser = PSArgumentParser()
    opts = parser.parse_args(args)
    projects = json.load(open('expriments/cleaned_options.json', 'r'))
    handle_project(projects, opts)

if __name__ == '__main__':
    main(sys.argv[1:])