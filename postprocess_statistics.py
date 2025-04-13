import argparse
import json
import os
import sys

from project import Project, Configuration
from project_info import ProjectInfo
from utils import *

def reports_statistics_analysis(project: Project):
    datas = []
    for config in project.config_list:
        data = {
            "project": project.project_name,
            "config": config.tag,
            "reports number": 0,
        }
        new_reports_json = json.load(open(os.path.join(config.cache_path, 'new_reports.json'), 'r'))
        for analyzer, reports in new_reports_json.items():
            data['reports number'] = reports[f"{config.tag} number"]
            data[f"new reports ({analyzer})"] = reports["diff number"]
        datas.append(data)
    return datas

def merge_skipped_ranges(skipped1, skipped2):
    new_range = []
    idx1 = idx2 = 0

    while idx1 < len(skipped1) and idx2 < len(skipped2):
        range1 = skipped1[idx1]
        range2 = skipped2[idx2]

        start1, end1 = range1[0], range1[1]
        start2, end2 = range2[0], range2[1]

        overlap_start = max(start1, start2)
        overlap_end = min(end1, end2)

        if overlap_start <= overlap_end:
            new_range.append([overlap_start, overlap_end])

        if end1 < end2:
            idx1 += 1
        else:
            idx2 += 1
    return new_range

def projects_statistics_analysis(project: Project):
    datas = []
    combine_statistics_across_configs = {}

    for config in project.config_list:
        print(f"Processing {config.tag}...")
        data = {
            'project': project.project_name, 'config': config.tag,
            'files (total)': 0, 'files (main)': 0, 'files (user)': 0, 
            'Lines (total)': 0, 'Lines (skip)': 0, 'Coverage': 100.0, 
            'CG (total)': 0, 'CG (main)': 0, 'CG (user)': 0, 
            'Calls (total)': 0,
            'FPIC': 0, 'FPTY': 0, 'FPIC Rate': 0, 
            'VF': 0, 'VFIC': 0, 'VFIC Rate': 0,
            'file (sum)': 0, 'Lines (total sum)': 0, 'Lines (skip sum)': 0, "Coverage (sum)": 100.0
        }
        statistics_in_this_config = os.path.join(config.prep_path, 'project_statistics.json')
        if not os.path.exists(statistics_in_this_config):
            continue
        statistics_json = json.load(open(statistics_in_this_config, 'r'))
        
        for file, statistics in statistics_json.items():
            if statistics['kind'] != 'MAIN' and statistics['kind'] != 'USER':
                continue
            data['Lines (total)'] +=  statistics['Coverage']['total']
            data['Lines (skip)'] +=  statistics['Coverage']['skipped lines']
            
            data['files (total)'] += 1
            data['files (main)'] += 1 if statistics['kind'] == 'MAIN' else 0
            data['files (user)'] += 1 if statistics['kind'] == 'USER' else 0

            data['CG (total)'] +=  statistics['CG Nodes']
            data['CG (main)'] += statistics['CG Nodes'] if statistics['kind'] == 'MAIN' else 0
            data['CG (user)'] += statistics['CG Nodes'] if statistics['kind'] == 'USER' else 0

            data['Calls (total)'] +=  statistics['Call Exprs']
            
            data['FPIC'] += statistics['FPIC']
            data['FPTY'] += statistics['FPTY']
            
            data['VF'] += statistics['VF']
            data['VFIC'] += statistics['VFIC']

            # Combine statistics across all configurations.
            if file in combine_statistics_across_configs:
                # Only skipped lines need to be combined.
                skipped1 = combine_statistics_across_configs[file]['Coverage']['skipped']
                skipped2 = statistics['Coverage']['skipped']
                new_range = merge_skipped_ranges(skipped1, skipped2)
                combine_statistics_across_configs[file]['Coverage']['skipped'] = new_range

                total_lines = combine_statistics_across_configs[file]['Coverage']['total']
                skipped_lines = sum([x[1]-x[0] for x in new_range])
                combine_statistics_across_configs[file]['Coverage']['skipped lines'] = skipped_lines
                combine_statistics_across_configs[file]['Coverage']['coverage'] = 100.0 if total_lines == 0 else (100.0*(total_lines - skipped_lines)/total_lines)
            else:
                combine_statistics_across_configs[file] = statistics

        data['Coverage'] = 100.0 if data['Lines (total)'] == 0 else (100.0*(data['Lines (total)'] - data['Lines (skip)'])/data['Lines (total)'])
        data['FPIC Rate'] = 0.0 if data['Calls (total)'] == 0 else (100.0*data['FPIC']/data['Calls (total)'])
        data['VFIC Rate'] = 0.0 if data['Calls (total)'] == 0 else (100.0*data['VFIC']/data['Calls (total)'])
        
        # Combined statistics.
        data['files (sum)'] = len(combine_statistics_across_configs.keys())
        for file, statistics in combine_statistics_across_configs.items():
            data['Lines (total sum)'] +=  statistics['Coverage']['total']
            data['Lines (skip sum)'] +=  statistics['Coverage']['skipped lines']
        data['Coverage (sum)'] = 100.0 if data['Lines (total sum)'] == 0 else (100.0*(data['Lines (total sum)'] - data['Lines (skip sum)'])/data['Lines (total sum)'])

        datas.append(data)

    return datas

def handle_project(projects, opts):
    pwd = os.path.abspath(".")
    projects_root_dir = os.path.join(pwd, "expriments")
    reports_statistics_csv = projects_root_dir + "/reports_statistics.csv"
    projects_statistics_csv = projects_root_dir + '/projects_statistics.csv'
    first_in = True

    for project in projects:
        if opts.repo and opts.repo != project['project'] and opts.repo != os.path.basename(project['project']):
            continue
        if 'config_options' not in project:
            continue
        print(f"Processing project: {project['project']}")
        project_info = ProjectInfo(projects_root_dir, project)

        workspace_tag = opts.tag if opts.tag else opts.inc
        workspace = f"{project_info.src_dir}_workspace/{workspace_tag}"

        p = Project(workspace=workspace,
                    opts=opts,
                    project_info=project_info)
        
        datas = reports_statistics_analysis(p)
        add_to_csv(datas, reports_statistics_csv, first_in)

        datas = projects_statistics_analysis(p)
        add_to_csv(datas, projects_statistics_csv, first_in)

        first_in = False


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