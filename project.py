from enum import Enum, auto
import json
import subprocess
import os
import re
from typing import List

import compiledb.parser
import compiledb.utils

from utils import *
from logger import logger
import compiledb

class GlobalConfig:
    cmake = 'cmake'
    bear = 'bear'
    icebear = 'icebear'
    build_jobs = '16'

    def __init__(self):
        def get_bear_version(bear):
            try:
                result = subprocess.run([bear, "--version"], capture_output=True, text=True, check=True)
                match = re.match(r'bear (\d+)\.', result.stdout)
                if match:
                    return int(match.group(1))
                return 2
            except (subprocess.CalledProcessError, OSError):
                return 2
        self.bear_version = get_bear_version(GlobalConfig.bear)

global_config = GlobalConfig()

class BuildType(Enum):
    CMake = auto()
    AutoConf = auto()
    Unknown = auto()

    @staticmethod
    def getType(build_type: str):
        if build_type == 'cmake':
            return BuildType.CMake
        elif build_type == 'autoconf':
            return BuildType.AutoConf
        else:
            return BuildType.Unknown

class OptionType(Enum):
    positive = auto()
    negative = auto()
    options = auto()

    @staticmethod
    def getType(option_type: str):
        if option_type == 'positive':
            return OptionType.positive
        elif option_type == 'negative':
            return OptionType.negative
        else:
            return OptionType.options

class Option:
    on_value_set = {'yes', '1', 'on'}
    off_value_set = {'no', '0', 'off'}

    def __init__(self, option, values, kind: OptionType, conflict, combination):
        self.option = option # The name of the config option.
        self.values = values # Possible values of the option, the first element is default value.
        self.kind = kind     # The kind of the option, determine how to turn on/off it.
        # Options cannot be turn on if this option is turn on.
        self.conflict = set(conflict) if conflict else set()
        # Option must be turn on if this option is tuen on.
        # ["key=value", ...]
        self.combination = combination if combination else []
        self.on_value = '1'
        self.off_value = '0'

        for value in self.values:
            value = str(value)
            if value.lower() in self.on_value_set:
                self.on_value = value
            elif value.lower() in self.off_value_set:
                self.off_value = value

    def turn_on(self):
        if len(self.values) > 0:
            # --enable-foo=yes
            return f"{self.option}={self.on_value}"
        # --enable-foo
        return self.option
    
    def turn_off(self):
        if len(self.values) > 0:
            # --enable-foo=no
            return f"{self.option}={self.off_value}"
        # empty
        return None
    
    def positive(self):
        # value and turn on/off
        if self.kind == OptionType.positive:
            return self.turn_on(), True
        elif self.kind == OptionType.negative:
            return self.turn_off(), False
        else:
            return None, False
    
    def negative(self):
        # value and turn on/off
        if self.kind == OptionType.positive:
            return self.turn_off(), False
        elif self.kind == OptionType.negative:
            return self.turn_on(), True
        else:
            return None, False

class Configuration:
    def __init__(self, build_type, options, src_path, build_path, workspace, constant_options: List[str], tag, opts):
        self.options: List[str] = options
        self.build_type = build_type
        self.src_path = src_path
        self.build_path = build_path
        self.workspace = workspace
        self.tag = tag
        self.opts = opts
        self.cache_path = os.path.join(self.workspace, self.tag)
        self.cache_file = os.path.join(self.workspace, 'cache.txt')
        makedir(self.cache_path)
        self.constant_options = constant_options
        self.compile_database = os.path.join(self.cache_path, "compile_commands.json")

    def option_cmd(self):
        cmd = self.constant_options.copy()
        if self.build_type == BuildType.CMake:
            cmd.extend([
                "-DCMAKE_EXPORT_COMPILE_COMMANDS=1",
                "CMAKE_C_COMPILER=clang-18",
                "CMAKE_CXX_COMPILER=clang++-18"
            ])
        for option in self.options:
            if self.build_type == BuildType.CMake:
                option = f"-D{option}"
            cmd.append(option)
        return cmd

    def config_cmd(self):
        cmd = []
        if self.build_type == BuildType.CMake:
            cmd = [GlobalConfig.cmake]
            cmd.extend(["-S", self.src_path])
            cmd.extend(["-B", self.build_path])
        elif self.build_type == BuildType.AutoConf:
            # Some projects should customize compiler by --cc/cxx, some projects don't support
            # these parameters, so we specify them in config_options.json.
            cmd = [f'{self.src_path}/configure']
            cmd.append(f"--prefix={self.build_path}")
        option_cmd = self.option_cmd()
        cmd.extend(option_cmd)
        # record options
        json.dump(option_cmd, open(os.path.join(self.cache_path, 'options.json'), 'w'), indent=4)
        return cmd
    
    def build_cmd(self):
        cmd = []
        if self.build_type == BuildType.CMake:
            cmd = ["cmake"]
            cmd.extend(["--build", f"{self.build_path}"])
            cmd.append(f"-j{GlobalConfig.build_jobs}")
        elif self.build_type == BuildType.AutoConf:
            cmd = ['make', f"-j{GlobalConfig.build_jobs}"]
            cmd.extend(['-C', self.build_path])
        cmd.extend(self.option_cmd())
        return cmd
    
    def icebear_cmd(self, not_update_cache=False):
        cmd = [GlobalConfig.icebear]
        cmd.extend(['-f', self.compile_database])
        cmd.extend(['-o', self.cache_path])
        cmd.extend(['-j', GlobalConfig.build_jobs])
        cmd.extend(['--inc', self.opts.inc])
        cmd.extend(['--analyzers', 'clangsa'])
        cmd.extend(['-c', self.cache_file])
        cmd.extend(['--cc', self.opts.cc])
        cmd.extend(['--cxx', self.opts.cxx])
        if self.opts.verbose:
            cmd.extend(['--verbose'])
        if self.opts.prep_only:
            cmd.append('--preprocess-only')
        if not_update_cache:
            cmd.append('--not-update-cache')
        return cmd

class Project:
    def __init__(self, src_dir, workspace, build_dir, options, build_type, constant_options: List[str], opts):
        self.src_dir = src_dir     # The directory to store source code.
        self.project_name = os.path.basename(self.src_dir)
        logger.TAG = self.project_name
        self.workspace = workspace # The directory to store cache and analysis results. 
        self.build_dir = build_dir # The directory to build project.
        self.config_list: List[Configuration] = []
        self.config_options: List[Option] = options
        self.build_type = build_type
        # The options cannot be changed in this environment, 
        # it's a str list, just consider it as initial option_cmd.
        self.constant_options = constant_options
        self.opts = opts
        self.create_dir()
        self.configuation_sampling()

    def create_dir(self):
        makedir(self.build_dir)
        makedir(self.workspace)

    def create_configuration(self, options, workspace, tag):
        return Configuration(self.build_type, options, self.src_dir, self.build_dir, workspace, self.constant_options, tag, self.opts)
    
    def get_different_kind_configuration(self, kind: OptionType, tag):
        options = []
        option_to_idx = dict()
        conflict_options = set()

        def add_to_options(op, overwrite):
            if op is not None:
                ops = op.split("=")
                if ops[0] in option_to_idx:
                    if overwrite:
                        options[ops[0]] = op
                else:
                    option_to_idx[ops[0]] = len(options)
                    options.append(op)
        
        for option in self.config_options:
            if kind == OptionType.positive:
                op, state = option.positive()
            elif kind == OptionType.negative:
                op, state = option.negative()
            else:
                # TODO: select one value
                op, state = None, False
            if state == True:
                # This option is turn on.
                if option.option not in conflict_options:
                    add_to_options(op, False)
                    conflict_options = conflict_options.union(option.conflict)
                    # Options in combination must be set to these value.
                    for com_op in option.combination:
                        add_to_options(com_op, True)
            else:
                # This option is turn off.
                add_to_options(op, False)
        if len(conflict_options):
            logger.debug(f"[Conflict Options] {conflict_options}")
        return self.create_configuration(options, self.workspace, tag)

    def configuation_sampling(self):
        # Default configuration
        default_configuration = self.create_configuration([], self.workspace, "0_default")
        # All positive configuration
        all_positive_configuration = self.get_different_kind_configuration(OptionType.positive, "1_all_positive")
        # All no configuration
        all_negative_configuration = self.get_different_kind_configuration(OptionType.negative, "2_all_negative")
        # Default as baseline
        self.baseline = default_configuration
        self.config_list = [default_configuration, all_positive_configuration, all_negative_configuration]

    def configure(self, config: Configuration) -> bool:
        return run(config.config_cmd(), config.build_path, "Configure Script")            
        
    def build(self, config: Configuration) -> bool:
        if global_config.bear_version == 2:
            cmd = [GlobalConfig.bear, '--cdb', str(config.compile_database)]
        else:
            cmd = [GlobalConfig.bear, '--output', str(config.compile_database), '--']
        cmd.extend(config.build_cmd())
        return run(cmd, config.build_path, "Build Script")

    def build_clean(self, config: Configuration):
        run_without_check(["make", "clean"], config.build_path, "Make Clean")

    def parse_makefile(self, config: Configuration):
        # Get compile_commands.json without build by parse "make -n -B -i".
        # make arguments:
        # -n: Output compile commands only;
        # -B: Don't consider incremental build;
        # -i: Ignore errors while executing.
        # compiledb arguments:
        # -f: Overwrite compile_commands.json instead of just updating it.
        # -S: Do not check if source files exist in the file system.
        compiledb_cmd = ['compiledb', 
                         '-o', config.compile_database, '-f', '--command-style', '-S',
                         'make', '-n', '-B', '-i'
                        ]
        logger.info(f"[Compiledb Script] {commands_to_shell_script(compiledb_cmd)}")
        subprocess.run(compiledb_cmd, 
            capture_output=True, 
            text=True, 
            cwd=config.build_path, 
            timeout=60 # Set timeout to avoid make execute recursively.
        )

        def split_cdb_item(cdb_file):
            # Split items which command contain multiple files.
            if os.path.exists(cdb_file):
                cdb: List = json.load(open(cdb_file, 'r'))
                idx = 0
                while idx < len(cdb):
                    ccmd = cdb[idx]
                    idx += 1
                    if 'command' in ccmd:
                        arguments = ccmd['command'].split(' ')
                    else:
                        arguments = ccmd['arguments']

                    current_file = os.path.abspath(os.path.join(ccmd['directory'], ccmd['file']))
                    new_item_num = 0
                    files_in_one_command = []
                    arguments_without_files = []

                    for (argument) in (arguments):
                        extname = os.path.splitext(argument)[1][1:]
                        if extname in {'c', 'C', 'cc', 'CC', 'cp', 'cpp', 'CPP', 'cxx', 'CXX', 'c++', 'C++'}:
                            # It's source code file.
                            this_file = os.path.abspath(os.path.join(ccmd['directory'], argument))
                            files_in_one_command.append((this_file))
                        else:
                            arguments_without_files.append(argument)

                    for file in files_in_one_command:
                        if file != current_file:
                            # Split this item.
                            new_item = ccmd.copy()
                            new_item['file'] = file
                            if 'arguments' in new_item:
                                new_item.remove('arguments')
                            new_arguments = arguments_without_files.copy()
                            new_arguments.insert(1, file)
                            new_item['command'] = " ".join(new_arguments)
                            cdb.insert(idx, new_item)
                            new_item_num += 1
                        else:
                            ccmd['file'] = current_file
                            if 'arguments' in ccmd:
                                ccmd.remove('arguments')
                            new_arguments = arguments_without_files.copy()
                            new_arguments.insert(1, file)
                            ccmd['command'] = " ".join(new_arguments)

                    if new_item_num > 0:
                        logger.info(f"[SPLIT CDB] Find {new_item_num} new item in {arguments}")
                        idx += new_item_num # Skip new item

                with open(cdb_file, 'w') as f:
                    json.dump(cdb, f, indent=3)
        
        split_cdb_item(config.compile_database)

    def icebear(self, config: Configuration):
        if config == self.baseline:
            icebear_cmd = config.icebear_cmd(not_update_cache=False)
        else:
            icebear_cmd = config.icebear_cmd(not_update_cache=True)
        run(icebear_cmd, config.cache_path, "IceBear Preprocess")

    def reports_analysis(self, config1: Configuration, config2: Configuration):
        if config1 == config2:
            logger.debug(f"[Report Analysis] {config1.tag} is same as {config2.tag}")
        
        class Report:
            def __init__(self, file, report):
                self.file = file
                self.report = report

            def __eq__(self, value):
                return self.file == value.file and self.report == value.report
            
            def __hash__(self):
                return hash((self.file, self.report))

        def get_reports(analyzer, config: Configuration):
            reports_dir = os.path.join(config.cache_path, analyzer)
            if analyzer == 'csa':
                reports_dir = os.path.join(reports_dir, 'csa-reports/version')
            
            def get_file_list(dir, file_pattern='*'):
                assert os.path.exists(dir)
                path = Path(dir)
                ret = []
                for abs_report in path.rglob(file_pattern):
                    # is_file(): the path of the report
                    # is_dir() and ...: empty direcotry, means correspond file doesn't have report.
                    if abs_report.is_file() or (abs_report.is_dir() and not os.listdir(abs_report)):
                        ret.append('/' + str(abs_report.relative_to(dir)))
                return ret
            
            file_list = get_file_list(reports_dir)
            file_to_reports = {}
            for file in file_list:
                if os.path.isfile(os.path.join(reports_dir, file[1:])):
                    # file with reports.
                    origin_file, report = os.path.split(file)
                    if origin_file not in file_to_reports:
                        file_to_reports[origin_file] = set()
                    file_to_reports[origin_file].add(Report(origin_file, report))
                else:
                    # file doesn't have reports.
                    file_to_reports[file] = set()
            return file_to_reports
        
        def diff_reports(reports1, reports2):
            file_to_diff = {}
            diff_num = 0
            for file, reports in reports2.items():
                if file in reports1:
                    diff = reports - reports1[file]
                    if len(diff) > 0:
                        file_to_diff[file] = {
                            # This field exists meaning that this file also be analyzed in baseline.
                            config1.tag: sorted([i.report for i in reports1[file]]),
                            config2.tag: sorted([i.report for i in diff])
                        }
                        diff_num += len(diff)
                else:
                    # If this file doesn't have reports, don't record it.
                    if len(reports) > 0:
                        file_to_diff[file] = {
                            config2.tag: sorted([i.report for i in reports])
                        }
                        diff_num += len(reports)
            return file_to_diff, diff_num

        analyzers = ['csa']
        all_diff = {}
        for analyzer in analyzers:
            all_diff[analyzer] = {}
            reports1 = get_reports(analyzer, config1)
            reports2 = get_reports(analyzer, config2)
            diff, diff_num = diff_reports(reports1, reports2)
            if len(diff) > 0:
                all_diff[analyzer] = {
                    f'{config1.tag} number': sum([len(v) for k, v in reports1.items()]),
                    f'{config2.tag} number': sum([len(v) for k, v in reports2.items()]),
                    'diff number': diff_num,
                    'file to diff': diff
                }
            logger.info(f"[Reports Analysis] Find {diff_num} new reports in {config2.tag}")

        with open(os.path.join(config2.cache_path, 'new_reports.json'), 'w') as f:
            json.dump(all_diff, f, indent=4, sort_keys=True)

    def process_every_configuraion(self):
        for config in self.config_list:
            logger.TAG = f"{self.project_name}/{config.tag}"
            # self.configure(config)
            # self.parse_makefile(config)
            # self.icebear(config)
            self.reports_analysis(self.baseline, config)
        pass