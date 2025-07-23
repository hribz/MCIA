import argparse
import json
import os
import sys
from typing import Dict, List

from pydantic import BaseModel, Field

from project import Project
from project_info import ProjectInfo
from utils import *

analyzers = ["CSA", "GSA", "CppCheck"]
inc_levels = []


class AnalyzerStatistics(BaseModel):
    total: int = 0
    configs: Dict[str, int] = Field(default_factory=dict)


class Summary(BaseModel):
    total: int = 0
    CSA: AnalyzerStatistics = Field(default_factory=AnalyzerStatistics)
    GSA: AnalyzerStatistics = Field(default_factory=AnalyzerStatistics)
    CppCheck: AnalyzerStatistics = Field(default_factory=AnalyzerStatistics)
    ClangTidy: AnalyzerStatistics = Field(default_factory=AnalyzerStatistics)


class Statistics(BaseModel):
    summary: Summary = Field(default_factory=Summary)
    diff: Summary = Field(default_factory=Summary)
    ClangTidyDistribution: Dict[str, int] = Field(default_factory=dict)

    def update_analyzer_statistics(
        self, analyzer_name: str, report_num: int, current_version: str
    ):
        getattr(self.summary, analyzer_name).total += report_num
        getattr(self.summary, analyzer_name).configs[current_version] = report_num
        self.summary.total += report_num

    def update_diff_statistics(
        self, analyzer_name: str, new_reports_count: int, current_version: str
    ):
        getattr(self.diff, analyzer_name).total += new_reports_count
        getattr(self.diff, analyzer_name).configs[current_version] = new_reports_count
        self.diff.total += new_reports_count

    def update_clang_tidy_distribution(self, distribution: Dict[str, int]):
        self.ClangTidyDistribution = distribution


def reports_statistics_analysis(project: Project):
    datas = []
    all_reports: Dict[str, Statistics] = {}
    for inc_level in inc_levels:
        reports_summary_file = os.path.join(
            project.workspace, f"reports_summary_{inc_level}.json"
        )
        if not os.path.exists(reports_summary_file):
            continue
        all_reports[inc_level] = Statistics(
            **json.load(open(reports_summary_file, "r"))
        )
    if len(all_reports) == 0:
        return datas

    for config in project.config_list:
        data = {"project": project.project_name, "version": config.tag}
        for analyzer in ["CSA", "GSA", "CppCheck"]:
            for inc_level in inc_levels:
                if inc_level in all_reports:
                    summary = all_reports[inc_level].summary
                    diff = all_reports[inc_level].diff
                    inc_analyzer = f"{analyzer} ({inc_level})"
                    data[inc_analyzer] = getattr(summary, analyzer).configs.get(
                        config.tag, 0
                    )
                    analyzer_diff = f"{inc_analyzer} (diff)"
                    data[analyzer_diff] = (
                        0
                        if (config == project.baseline or diff is None)
                        else getattr(diff, analyzer).configs.get(config.tag, 0)
                    )
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
        # print(f"Processing {config.tag}...")
        data = {
            "project": project.project_name,
            "version": config.tag,
            "files (total)": 0,
            "files (main)": 0,
            "files (user)": 0,
            "Lines (total)": 0,
            "Lines (skip)": 0,
            "Coverage": 100.0,
            "CG (total)": 0,
            "CG (main)": 0,
            "CG (user)": 0,
            "Calls (total)": 0,
            "FPIC": 0,
            "FPTY": 0,
            "FPIC Rate": 0,
            "VF": 0,
            "VFIC": 0,
            "VFIC Rate": 0,
            "files (sum)": 0,
            "Lines (total sum)": 0,
            "Lines (skip sum)": 0,
            "Coverage (sum)": 100.0,
        }
        statistics_in_this_config = os.path.join(
            config.prep_path, "project_statistics.json"
        )
        if not os.path.exists(statistics_in_this_config):
            continue
        statistics_json = json.load(open(statistics_in_this_config, "r"))

        for file, statistics in statistics_json.items():
            if statistics["kind"] != "MAIN" and statistics["kind"] != "USER":
                continue
            data["Lines (total)"] += statistics["Coverage"]["total"]
            data["Lines (skip)"] += statistics["Coverage"]["skipped lines"]

            data["files (total)"] += 1
            data["files (main)"] += 1 if statistics["kind"] == "MAIN" else 0
            data["files (user)"] += 1 if statistics["kind"] == "USER" else 0

            data["CG (total)"] += statistics["CG Nodes"]
            data["CG (main)"] += (
                statistics["CG Nodes"] if statistics["kind"] == "MAIN" else 0
            )
            data["CG (user)"] += (
                statistics["CG Nodes"] if statistics["kind"] == "USER" else 0
            )

            data["Calls (total)"] += statistics["Call Exprs"]

            data["FPIC"] += statistics["FPIC"]
            data["FPTY"] += statistics["FPTY"]

            data["VF"] += statistics["VF"]
            data["VFIC"] += statistics["VFIC"]

            # Combine statistics across all configurations.
            if file in combine_statistics_across_configs:
                # Only skipped lines need to be combined.
                skipped1 = combine_statistics_across_configs[file]["Coverage"][
                    "skipped"
                ]
                skipped2 = statistics["Coverage"]["skipped"]
                new_range = merge_skipped_ranges(skipped1, skipped2)
                combine_statistics_across_configs[file]["Coverage"][
                    "skipped"
                ] = new_range

                total_lines = combine_statistics_across_configs[file]["Coverage"][
                    "total"
                ]
                skipped_lines = sum([x[1] - x[0] for x in new_range])
                combine_statistics_across_configs[file]["Coverage"][
                    "skipped lines"
                ] = skipped_lines
                combine_statistics_across_configs[file]["Coverage"]["coverage"] = (
                    100.0
                    if total_lines == 0
                    else (100.0 * (total_lines - skipped_lines) / total_lines)
                )
            else:
                combine_statistics_across_configs[file] = statistics

        data["Coverage"] = (
            100.0
            if data["Lines (total)"] == 0
            else (
                100.0
                * (data["Lines (total)"] - data["Lines (skip)"])
                / data["Lines (total)"]
            )
        )
        data["FPIC Rate"] = (
            0.0
            if data["Calls (total)"] == 0
            else (100.0 * data["FPIC"] / data["Calls (total)"])
        )
        data["VFIC Rate"] = (
            0.0
            if data["Calls (total)"] == 0
            else (100.0 * data["VFIC"] / data["Calls (total)"])
        )

        # Combined statistics.
        data["files (sum)"] = len(combine_statistics_across_configs.keys())
        for file, statistics in combine_statistics_across_configs.items():
            data["Lines (total sum)"] += statistics["Coverage"]["total"]
            data["Lines (skip sum)"] += statistics["Coverage"]["skipped lines"]
        data["Coverage (sum)"] = (
            100.0
            if data["Lines (total sum)"] == 0
            else (
                100.0
                * (data["Lines (total sum)"] - data["Lines (skip sum)"])
                / data["Lines (total sum)"]
            )
        )

        datas.append(data)

    return datas


def analyzer_statistics_analysis(project: Project, specific):
    datas = []
    for config in project.config_list:
        log_path = os.path.join(config.workspace, "logs")
        log_prefix = f"{project.project_name}_{project.opts.inc}_{config.tag}"
        if specific:
            log_file = os.path.join(log_path, log_prefix + "_specific.csv")
        else:
            log_file = os.path.join(log_path, log_prefix + ".csv")
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8") as file:
                csv_reader = csv.DictReader(file)
                for row in csv_reader:
                    datas.append(row)
        else:
            print(f"{log_file} doesn't exists.")
    return datas


def ave_for_datas(datas: List[Dict], key):
    if len(datas) < 1:
        return None
    values = []
    for item in datas:
        value = item[key]
        if str.isdecimal(value):
            values.append(int(value))
        else:
            try:
                float_value = float(value)
                values.append(float_value)
            except ValueError:
                values.append(0)
    ret = sum(values) / len(values) if len(values) > 0 else None
    return ret


def sum_for_datas(datas: List[Dict], key):
    if len(datas) < 1:
        return None
    if key not in datas[0]:
        return None
    values = []
    for item in datas:
        value = item[key]
        if isinstance(value, int | float):
            values.append(value)
        elif isinstance(value, str):
            if str.isdecimal(value):
                values.append(int(value))
            else:
                try:
                    float_value = float(value)
                    values.append(float_value)
                except ValueError:
                    values.append(0)
        else:
            values.append(0)
    ret = sum(values)
    return ret


def calculate_overview_data(keys, overview_data, datas):
    for key in keys:
        sum_val = sum_for_datas(datas, key)
        if sum_val is not None:
            overview_data[key] = sum_val


def handle_project(projects, opts):
    pwd = os.path.abspath(".")
    projects_root_dir = os.path.join(pwd, "expriments")
    reports_statistics_csv = projects_root_dir + "/reports_statistics.csv"
    projects_statistics_csv = projects_root_dir + "/projects_statistics.csv"
    analyzers_statistics_csv = projects_root_dir + "/analyzers_statistics.csv"
    analyzers_statistics_specific_csv = (
        projects_root_dir + "/analyzers_statistics_specific.csv"
    )
    time_overview = projects_root_dir + f"/time_overview.csv"
    reports_overview = projects_root_dir + "/reports_overview.csv"
    first_in = True

    time_overview_datas = []
    reports_overview_datas = []

    for project in projects:
        if (
            opts.repo
            and opts.repo != project["project"]
            and opts.repo != os.path.basename(project["project"])
        ):
            continue
        if "config_options" not in project:
            continue
        print(f"Processing project: {project['project']}")
        project_info = ProjectInfo(projects_root_dir, project)

        workspace_tag = opts.tag if opts.tag else opts.inc
        workspace = f"{project_info.src_dir}_workspace/{workspace_tag}"

        p = Project(workspace=workspace, opts=opts, project_info=project_info)

        time_overview_data = {
            "project": p.project_name,
            "version": "total",
            "files": 0,
            "diff files": 0,
            "prepare for inc": 0,
            "changed function": 0,
            "reanalyze function": 0,
        }
        time_overview_data.update({key: 0 for key in analyzers})

        reports_overview_data = {"project": p.project_name, "version": "total"}
        reports_overview_data.update(
            {
                key: 0
                for key in [
                    i
                    for analyzer in analyzers
                    for i in (analyzer, analyzer + " (diff)")
                ]
            }
        )

        datas = reports_statistics_analysis(p)
        if datas:
            # Single reports statistics.
            add_to_csv(datas, os.path.join(workspace, "reports_statistics.csv"))
            # Overall reports statistics.
            if not opts.repo:
                add_to_csv(datas, reports_statistics_csv, first_in)

            keys = [
                i for analyzer in analyzers for i in (analyzer, analyzer + " (diff)")
            ]
            calculate_overview_data(keys, reports_overview_data, datas)

        datas = projects_statistics_analysis(p)
        if datas:
            # Single project statistics.
            add_to_csv(datas, os.path.join(workspace, "projects_statistics.csv"))
            # Overall statistics.
            if not opts.repo:
                add_to_csv(datas, projects_statistics_csv, first_in)

        datas = analyzer_statistics_analysis(p, False)
        if datas:
            add_to_csv(datas, os.path.join(workspace, "analyzers_statistics.csv"))
            if not opts.repo:
                add_to_csv(datas, analyzers_statistics_csv, first_in)

            keys = ["prepare for inc"]
            calculate_overview_data(keys, time_overview_data, datas)

        datas = analyzer_statistics_analysis(p, True)
        if datas:
            add_to_csv(
                datas, os.path.join(workspace, "analyzers_statistics_specific.csv")
            )
            if not opts.repo:
                add_to_csv(datas, analyzers_statistics_specific_csv, first_in)

            keys = analyzers.copy()
            keys.extend([f"analyze ({inc_level})" for inc_level in inc_levels])
            keys.extend(
                ["files", "diff files", "changed function", "reanalyze function"]
            )
            calculate_overview_data(keys, time_overview_data, datas)

        time_overview_datas.append(time_overview_data)
        reports_overview_datas.append(reports_overview_data)
        first_in = False

    if not opts.repo:
        add_to_csv(time_overview_datas, time_overview, True)
        add_to_csv(reports_overview_datas, reports_overview, True)


class PSArgumentParser:
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
            "--inc",
            type=str,
            dest="inc",
            choices=["noinc", "file", "func", "all"],
            default="all",
            help="Incremental analysis mode: noinc, file, func, all",
        )
        self.parser.add_argument(
            "--tag", type=str, dest="tag", help="Tag of this analysis."
        )
        self.parser.add_argument(
            "--order", type=str, dest="order", help="Order of this analysis."
        )
        

    def parse_args(self, args):
        return self.parser.parse_args(args)


def main(args):
    global inc_levels, analyzers
    parser = PSArgumentParser()
    opts = parser.parse_args(args)
    projects = json.load(open("expriments/cleaned_options.json", "r"))
    inc_levels = [opts.inc]
    if opts.inc == "all":
        inc_levels = ["noinc", "file", "func"]
    analyzers = [f"{i} ({inc_level})" for i in analyzers for inc_level in inc_levels]
    handle_project(projects, opts)


if __name__ == "__main__":
    main(sys.argv[1:])
