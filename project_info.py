import os
from typing import List

from option import *


class BuildType(Enum):
    CMake = auto()
    AutoConf = auto()
    Meson = auto()
    Unknown = auto()

    @staticmethod
    def getType(build_type: str):
        if build_type == "cmake":
            return BuildType.CMake
        elif build_type == "autoconf":
            return BuildType.AutoConf
        elif build_type == "meson":
            return BuildType.Meson
        else:
            return BuildType.Unknown

    def notNeedBear(self):
        return self == BuildType.Meson or self == BuildType.CMake

    def useMake(self):
        return self == BuildType.AutoConf or self == BuildType.CMake


def get_if_exists(dict, key, default=None):
    return dict[key] if key in dict else default


def parse_options(options, switch_values, build_type):
    ret = []
    if build_type == BuildType.CMake:
        ret = [
            Option(
                "CMAKE_BUILD_TYPE",
                ["Release", "Debug"],
                None,
                OptionType.options,
                None,
                None,
                None,
            )
        ]
    for option in options:
        if option["kind"] == "ignore":
            continue
        switch_values_of_this_option = (
            switch_values.get(option["kind"], None) if switch_values else None
        )
        ret.append(
            Option(
                option["key"],
                option["values"],
                switch_values_of_this_option,
                OptionType.getType(option["kind"]),
                option.get("conflict"),
                option.get("combination"),
                option.get("on_value"),
            )
        )
    return ret


class ProjectInfo:
    def __init__(self, projects_root_dir, project):
        self.repo_name = project["project"]
        self.src_dir = os.path.join(
            projects_root_dir, self.repo_name
        )  # The directory to store source code.

        self.build_type = BuildType.getType(project["build_type"])
        self.out_of_tree = get_if_exists(project, "out_of_tree", True)
        # The options cannot be changed in this environment,
        # it's a str list, just consider it as initial option_cmd.
        self.constant_options = get_if_exists(project, "constant_options", [])
        self.commit = project["shallow"]

        self.switch_values = get_if_exists(project, "switch_values")
        self.meson_native = get_if_exists(project, "native_file", None)
        self.options: List[Option] = parse_options(
            project["config_options"], self.switch_values, self.build_type
        )
        self.prerequisites = get_if_exists(
            project, "prerequisites", []
        )  # The commands need to be executed before building the project.
        self.dry_run = get_if_exists(project, "dry_run", False)
        self.must_make = get_if_exists(
            project, "make", False
        )  # This project must built before analysis.
        self.must_gcc = get_if_exists(
            project, "gcc", False
        )  # This project must built through gcc.
        self.env = get_if_exists(project, "env", {})
        self.ignore_make_error = get_if_exists(project, "ignore make error", False)
        self.filter_configs = get_if_exists(
            project, "filter", None
        )

        self.build_dir = (
            f"{self.src_dir}_build" if self.out_of_tree else self.src_dir
        )  # The directory to build project.
