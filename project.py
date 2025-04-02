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

from project_info import *

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

class Configuration:
    def __init__(self, workspace, tag, opts, config_options, project_info: ProjectInfo):
        self.project_info = project_info
        self.workspace = workspace
        self.tag = tag
        self.opts = opts
        self.config_options = config_options
        self.cache_path = os.path.join(self.workspace, self.tag)
        self.cache_file = os.path.join(self.workspace, 'cache.txt')
        makedir(self.cache_path)
        self.compile_database = os.path.join(self.cache_path, "compile_commands.json")

    def option_cmd(self):
        cmd = self.project_info.constant_options.copy()
        if self.project_info.build_type == BuildType.CMake:
            cmd.extend([
                "-DCMAKE_EXPORT_COMPILE_COMMANDS=1",
                "-DCMAKE_C_COMPILER=clang-18",
                "-DCMAKE_CXX_COMPILER=clang++-18"
            ])
        for option in self.config_options:
            if self.project_info.build_type == BuildType.CMake:
                option = f"-D{option}"
            cmd.append(option)
        return cmd

    def config_cmd(self):
        cmd = []
        if self.project_info.build_type == BuildType.CMake:
            cmd = [GlobalConfig.cmake]
            cmd.extend(["-S", self.project_info.src_dir])
            cmd.extend(["-B", self.project_info.build_dir])
        elif self.project_info.build_type == BuildType.AutoConf:
            # Some projects should customize compiler by --cc/cxx, some projects don't support
            # these parameters, so we specify them in config_options.json.
            cmd = [f'{self.project_info.src_dir}/configure']
            # cmd.append(f"--prefix={self.project_info.build_dir}")
        option_cmd = self.option_cmd()
        cmd.extend(option_cmd)
        # record options
        json.dump(option_cmd, open(os.path.join(self.cache_path, 'options.json'), 'w'), indent=4)
        return cmd
    
    def build_cmd(self):
        cmd = []
        if self.project_info.build_type == BuildType.CMake:
            cmd = ["cmake"]
            cmd.extend(["--build", f"{self.project_info.build_dir}"])
            cmd.append(f"-j{GlobalConfig.build_jobs}")
        elif self.project_info.build_type == BuildType.AutoConf:
            cmd = ['make', f"-j{GlobalConfig.build_jobs}"]
        if self.project_info.ignore_make_error:
            cmd.append("-i")
        return cmd
    
    def icebear_cmd(self, update_cache):
        cmd = [GlobalConfig.icebear]
        cmd.extend(['-f', self.compile_database])
        cmd.extend(['-o', self.cache_path])
        cmd.extend(['-j', GlobalConfig.build_jobs])
        cmd.extend(['--inc', self.opts.inc])
        cmd.extend(['--analyzers', 'clangsa'])
        cmd.extend(['-c', self.cache_file])
        cmd.extend(['--cc', self.opts.cc])
        cmd.extend(['--cxx', self.opts.cxx])
        cmd.append(f'--file-identifier={self.opts.file_identifier}')
        if self.opts.verbose:
            cmd.extend(['--verbose'])
        if self.opts.prep_only:
            cmd.append('--preprocess-only')
        if not update_cache:
            cmd.append('--not-update-cache')
        return cmd

class Project:
    def __init__(self, workspace, opts, project_info: ProjectInfo):
        self.src_dir = project_info.src_dir     # The directory to store source code.
        self.project_name = os.path.basename(self.src_dir)
        logger.TAG = self.project_name
        self.workspace = workspace # The directory to store cache and analysis results.
        self.config_list: List[Configuration] = []
        self.opts = opts
        self.project_info = project_info
        self.env = dict(os.environ)
        if not project_info.must_gcc:
            self.env['CC'] = 'clang-18'
            self.env['CXX'] = 'clang++-18'
        if project_info.env:
            self.env.update(project_info.env)
        self.create_dir()
        self.configuation_sampling()

    def create_dir(self):
        makedir(self.project_info.build_dir)
        makedir(self.workspace)

    def create_configuration(self, options, workspace, tag):
        return Configuration(workspace, tag, self.opts, options, self.project_info)
    
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
        
        for option in self.project_info.options:
            if kind == OptionType.positive:
                op, state = option.positive()
                if state and option.option == '--enable-all':
                    logger.info(f"[Enable All] --enable-all is turn on, don't need to consider other options.")
                    options = [op]
                    break
            elif kind == OptionType.negative:
                op, state = option.negative()
                if state and option.option == '--disable-all':
                    logger.info(f"[Disable All] --disable-all is turn on, don't need to consider other options.")
                    options = [op]
                    break
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
                    add_to_options(option.negative()[0], True)
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
        all_config = [default_configuration, all_positive_configuration, all_negative_configuration]
        self.config_list = [self.baseline] + [config for config in all_config if config != self.baseline]

    def execute_prerequisites(self, config: Configuration) -> bool:
        for prerequisite in self.project_info.prerequisites:
            return run(prerequisite, config.project_info.build_dir, "Prerequisite", self.env)

    def configure(self, config: Configuration) -> bool:
        configure_script = commands_to_shell_script(config.config_cmd())
        logger.info(f"[Configure Script] {configure_script}")
        if not os.path.exists(config.project_info.build_dir):
            logger.error(f"[Configure Script] Please make sure {config.project_info.build_dir} exists!")
            return False
        process = subprocess.run(
            config.config_cmd(),
            cwd=config.project_info.build_dir,
            env=self.env,
            text=True
        )
        logger.info(f"[Configure Output]\nstdout:\n{process.stdout}\nstderr:\n{process.stderr}")
        if process.returncode != 0:
            logger.info(f"[Configure Failed] {configure_script}")

        if self.project_info.build_type == BuildType.CMake:
            shutil.copy(os.path.join(config.project_info.build_dir, "compile_commands.json"), config.compile_database)

        return process.returncode == 0
        
    def build(self, config: Configuration) -> bool:
        if global_config.bear_version == 2:
            cmd = [GlobalConfig.bear, '--cdb', str(config.compile_database)]
        else:
            cmd = [GlobalConfig.bear, '--output', str(config.compile_database), '--']
        cmd.extend(config.build_cmd())
        
        logger.info(f"[Building] {commands_to_shell_script(cmd)}")
        process = subprocess.run(
            cmd,
            cwd=config.project_info.build_dir,
            env=self.env,
            capture_output=True,
            text=True
        )
        logger.info(f"[Build Output]\nstdout:\n{process.stdout}\nstderr:\n{process.stderr}")
        if process.returncode != 0:
            logger.info(f"[Build Failed] {commands_to_shell_script(cmd)}")
        return process.returncode == 0

    def build_clean(self, config: Configuration):
        run_without_check(["make", "clean"], config.project_info.build_dir, "Make Clean")

    def parse_makefile(self, config: Configuration):
        if self.build_type == BuildType.CMake:
            # The compile_commands.json of opencv contain compile argument like -DXXX="long long",
            # compiledb doesn't perserve the "", so we use CMake's compile_commands.json.
            # TODO: compiledb support -DXXX="long long"?
            logger.info(f"[Parse Makefile] Use compile_commands.json generated by CMake")
            return True

        # Get compile_commands.json without build by parse "make -n -B -i".
        # make arguments:
        # -n: Output compile commands only;
        # -B: Don't consider incremental build;
        # -i: Ignore errors while executing.
        make_n = subprocess.run(
            ['make', '-n', '-i'],
            capture_output=True,
            text=True,
            cwd=config.project_info.build_dir,
            env=self.env
        )
        # compiledb arguments:
        # -f: Overwrite compile_commands.json instead of just updating it.
        # -S: Do not check if source files exist in the file system.
        compiledb_cmd = ['compiledb',
                         '-o', config.compile_database, '-f', '-S'
                        ]
        logger.info(f"[Compiledb Script] {commands_to_shell_script(compiledb_cmd)}")
        subprocess.run(compiledb_cmd, 
            capture_output=True, 
            text=True, 
            cwd=config.project_info.build_dir, 
            input=make_n.stdout,
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
                        from shlex import split
                        arguments = split(ccmd['command'])
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
                                new_item.pop('arguments')
                            new_arguments = arguments_without_files.copy()
                            new_arguments.insert(1, file)
                            new_item['command'] = " ".join(new_arguments)
                            cdb.insert(idx, new_item)
                            new_item_num += 1
                        else:
                            ccmd['file'] = current_file
                            if 'arguments' in ccmd:
                                ccmd.pop('arguments')
                            new_arguments = arguments_without_files.copy()
                            new_arguments.insert(1, file)
                            ccmd['command'] = " ".join(new_arguments)

                    if new_item_num > 0:
                        logger.info(f"[SPLIT CDB] Find {new_item_num} new item in {arguments}")
                        idx += new_item_num # Skip new item

                with open(cdb_file, 'w') as f:
                    json.dump(cdb, f, indent=3)
        
        split_cdb_item(config.compile_database)

        def filter_commands(make_n_output):
            commands = []
            buffer = []
            for line in make_n_output.split('\n'):
                line = line.rstrip()
                if not line:
                    continue
                # Merge \ at the end of line.
                if line.endswith('\\'):
                    buffer.append(line[:-1].strip())
                else:
                    buffer.append(line.strip())
                    commands.append(' '.join(buffer))
                    buffer = []
            
            return commands
        
        def dry_run(commands):
            skip_patterns = [
                r'^\s*((/[\w-]+)+/)?(gcc|clang|cc|g\+\+|clang\+\+|nvcc|ld|ar|ccache)\s',  # Compile, link.
                r'\smake\s',   # Make
                r'\smsgfmt\s', # Don't parse .po
                r'\s-shared\b',  # Shared library.
                r'\s-shared\b',  # Shared library.
                r'\s-arch\b',    # Architecture argument.
                # r'\.(o|a|so|dylib|exe)\b',  # Target or executable file.

                # No command
                r'^\s*#',                # Comment(e.g. # This is a comment).
                r'\b(make|info|warning)\b',  # Ignore Makefile function(e.g. $(info ...))
                r'^\s*\$\('              # Ignore variable expansion(e.g. $(RM) file.o)
            ]
            dir_stack = [config.project_info.build_dir]
            
            for cmd in commands:
                skip = False
                if not cmd:
                    continue

                # make[%d] Entering/Leaving directory 'path'
                entering_match = re.search(r'make\[\d+\]: Entering directory \'(.+)\'', cmd)
                leaving_match = re.search(r'make\[\d+\]: Leaving directory \'(.+?)\'', cmd)
                if entering_match:
                    logger.debug(f"[ENTERING] {cmd}")
                    dir_stack.append(entering_match.group(1))
                    continue
                elif leaving_match:
                    assert leaving_match.group(1) == dir_stack[-1]
                    logger.debug(f"[LEAVING] {cmd}")
                    dir_stack.pop()
                    continue

                # Skip this command if it's for compilation.
                for pattern in skip_patterns:
                    if re.search(pattern, cmd, re.IGNORECASE):
                        logger.debug(f"[SKIPPED] {cmd}")
                        skip = True
                        break
                if not skip:
                    logger.debug(f"[EXECUTE] {cmd}")
                    try:
                        subprocess.run(
                            cmd,
                            shell=True,
                            check=True,
                            cwd=dir_stack[-1],
                            env=self.env
                        )
                    except subprocess.CalledProcessError as e:
                        logger.info(f"[FAILED!] {cmd}\nError: {e}")
            return True
        
        if self.project_info.dry_run:
            logger.info(f"[DRY RUN] {config.tag}")
            make_n_commands = filter_commands(make_n.stdout)
            return dry_run(make_n_commands)
        return True

    def icebear(self, config: Configuration):
        if config == self.baseline:
            icebear_cmd = config.icebear_cmd(update_cache=True)
        else:
            # Only record one config as baseline cache.
            icebear_cmd = config.icebear_cmd(update_cache=False)
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
            if not os.path.exists(reports_dir):
                return {}
            
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
            reports1 = get_reports(analyzer, config1)
            reports2 = get_reports(analyzer, config2)
            diff, diff_num = diff_reports(reports1, reports2)
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
            self.execute_prerequisites(config)
            if self.project_info.must_make:
                self.build_clean(config)
            process_status = self.configure(config)
            if not process_status:
                logger.error(f"[Configure {config.tag}] Configure failed! Stop subsequent jobs.")
                break
            if self.project_info.must_make:
                self.build(config)
            else:
                process_status = self.parse_makefile(config)
                if not process_status:
                    logger.error(f"[Parse Makefile {config.tag}] Parse makefile failed! Stop subsequent jobs.")
                    continue
            self.icebear(config)
            self.reports_analysis(self.baseline, config)
        pass