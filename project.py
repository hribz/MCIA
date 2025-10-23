import json
import os
import re
import subprocess
from typing import Dict, List, Set

from git import Union

from incremental_database import FileLevelCache
from logger import logger
from project_info import *
from utils import *


class GlobalConfig:
    cmake = "cmake"
    bear = "bear"
    icebear = "icebear"
    build_jobs = "16"
    inc_gcc = "/home/xiaoyu/package/src/gcc/install/bin/gcc-14"

    def __init__(self):
        def get_bear_version(bear):
            try:
                result = subprocess.run(
                    [bear, "--version"], capture_output=True, text=True, check=True
                )
                match = re.match(r"bear (\d+)\.", result.stdout)
                if match:
                    return int(match.group(1))
                return 2
            except (subprocess.CalledProcessError, OSError):
                return 2

        self.bear_version = get_bear_version(GlobalConfig.bear)
        pwd = os.path.dirname(os.path.abspath(__file__))
        self.basic_info_extractor = os.path.join(pwd, "build/collectStatistics")


global_config = GlobalConfig()


class Configuration:
    def __init__(self, workspace, tag, opts, config_options, project_info: ProjectInfo):
        self.project_info = project_info
        self.workspace = workspace
        self.tag = tag
        self.opts = opts
        self.config_options = config_options
        self.prep_path = os.path.join(self.workspace, f"preprocess/{tag}")
        self.cache_file = os.path.join(self.prep_path, "file_level_cache.json")
        makedir(self.prep_path)
        self.compile_database = os.path.join(self.prep_path, "compile_commands.json")

    def option_cmd(self):
        cmd = self.project_info.constant_options.copy()
        if self.project_info.build_type == BuildType.CMake:
            cmd.extend(["-DCMAKE_EXPORT_COMPILE_COMMANDS=1"])
            cmd.extend(
                [
                    "-DCMAKE_BUILD_TYPE=Debug",
                    "-DCMAKE_C_FLAGS=-O0 -g0",
                    "-DCMAKE_CXX_FLAGS=-O0 -g0",
                ]
            )
        elif self.project_info.build_type == BuildType.Meson:
            cmd.extend(
                [
                    "--reconfigure",
                    "-Dc_args=-O0 -g0",
                    "-Dcpp_args=-O0 -g0",
                    "-Doptimization=0",
                    "-Ddebug=false",
                ]
            )
        for option in self.config_options:
            if (
                self.project_info.build_type == BuildType.CMake
                or self.project_info.build_type == BuildType.Meson
            ):
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
            cmd = [f"{self.project_info.src_dir}/configure"]
            # cmd.append(f"--prefix={self.project_info.build_dir}")
        elif self.project_info.build_type == BuildType.Meson:
            cmd = ["meson"]
            cmd.extend(
                ["setup", self.project_info.build_dir, self.project_info.src_dir]
            )
            if self.project_info.meson_native:
                cmd.extend(
                    ["--native", os.path.join(self.workspace, "native_file.ini")]
                )
        option_cmd = self.option_cmd()
        cmd.extend(option_cmd)
        # record options
        json.dump(
            option_cmd,
            open(os.path.join(self.prep_path, "options.json"), "w"),
            indent=4,
        )
        return cmd

    def build_cmd(self):
        cmd = []
        if self.project_info.build_type == BuildType.CMake:
            cmd = ["cmake"]
            cmd.extend(["--build", f"{self.project_info.build_dir}"])
            cmd.append(f"-j{GlobalConfig.build_jobs}")
        elif self.project_info.build_type == BuildType.AutoConf:
            cmd = ["make", f"-j{GlobalConfig.build_jobs}"]
        elif self.project_info.build_type == BuildType.Meson:
            cmd = ["ninja"]
            cmd.extend(["-C", self.project_info.build_dir])
            cmd.append(f"-j{GlobalConfig.build_jobs}")
        if self.project_info.ignore_make_error:
            if self.project_info.build_type.useMake():
                cmd.append("-i")
        return cmd

    def icebear_cmd(self, prep_only=False, update_cache=True, cache_file=None):
        if not cache_file:
            cache_file = self.cache_file
        cmd = [GlobalConfig.icebear]
        cmd.extend(["-f", self.compile_database])
        cmd.extend(["-o", self.workspace])
        cmd.extend(["-j", GlobalConfig.build_jobs])
        cmd.extend(["--inc", self.opts.inc])
        cmd.extend(["--analyzers", "clangsa"])
        cmd.extend(["--cache", cache_file])
        cmd.extend(["--cc", self.opts.cc])
        cmd.extend(["--cxx", self.opts.cxx])
        cmd.extend(["--gcc", GlobalConfig.inc_gcc])
        cmd.append(f"--file-identifier={self.opts.file_identifier}")
        cmd.append(f"--tag={self.tag}")
        cmd.extend(["--report-hash", "context"])
        cmd.extend(["--no-clean-inc"])
        if self.opts.basic_info:
            cmd.append(f"--basic-info={global_config.basic_info_extractor}")
        if self.opts.verbose:
            cmd.extend(["--verbose"])
        if prep_only:
            cmd.append("--preprocess-only")
        if not update_cache:
            cmd.append("--not-update-cache")
        if self.opts.only_process_reports:
            cmd.append("--only-process-reports")
        return cmd


def get_equidistant_elements(lst, num):
    if len(lst) <= num:
        return lst.copy()
    step = (len(lst) - 1) / (num - 1)
    indices = [round(i * step) for i in range(num)]
    return [lst[i] for i in indices]

class Project:
    def __init__(self, workspace, opts, project_info: ProjectInfo):
        self.src_dir = project_info.src_dir  # The directory to store source code.
        self.project_name = os.path.basename(self.src_dir)
        logger.TAG = self.project_name
        self.workspace = workspace # The directory to store cache and analysis results.
        self.opts = opts
        self.project_info = project_info

        self.config_list: List[Configuration] = [] # All sampled configurations.
        self.chosen_config_list: List[Configuration] = [] # Configurations to be analyzed.
        self.zero_distance_configs: Set[Configuration] = set() # Configurations with zero distance.
        self.overall_cache_file = os.path.join(self.workspace, "file_level_cache.json")

        self.env = dict(os.environ)
        # O0 optimization level and no debug information.
        self.env.update(
            {
                "CFLAGS": f"{self.env.get('CFLAGS', '')} -O0 -g0".strip(),
                "CXXFLAGS": f"{self.env.get('CXXFLAGS', '')} -O0 -g0".strip(),
                "OPTFLAGS": "-O0 -g0",
            }
        )

        self.sampling_config = SamplingConfig(self.project_info.options, 15)
        self.config_sampler = ConfigSampling(
            self.project_info.options, self.sampling_config
        )
        if not project_info.must_gcc:
            self.env["CC"] = "clang-18"
            self.env["CXX"] = "clang++-18"
        if project_info.env:
            self.env.update(project_info.env)
        self.create_dir()
        self.configuration_sampling()

    def create_dir(self):
        makedir(self.project_info.build_dir)
        makedir(self.workspace)
        if self.project_info.meson_native:
            native_file = os.path.join(self.workspace, "native_file.ini")
            if os.path.exists(native_file):
                return
            native_config = ""
            for key, value in self.project_info.meson_native.items():
                native_config += f"[{key}]\n"
                for k, v in value.items():
                    if isinstance(v, str):
                        native_config += f"{k} = '{v}'\n"
                    else:
                        native_config += f"{k} = {v}\n"

            with open(native_file, "w") as f:
                f.write(native_config)

    def create_configuration(self, options, workspace, tag):
        return Configuration(workspace, tag, self.opts, options, self.project_info)

    def get_different_kind_configuration(self, kind: ConfigType, tag):
        options = self.config_sampler.get_different_kind_configuration(kind)
        if options is None:
            return None
        return self.create_configuration(options, self.workspace, tag)

    def configuration_sampling(self):
        classified_options = {ty: [] for ty in OptionType}
        for option in self.config_sampler.options:
            classified_options[option.kind].append(
                f"{option.option} on:{option.on_value} off:{option.off_value}"
            )
        with open(os.path.join(self.workspace, "configure.txt"), "w") as f:
            for ty in OptionType:
                f.write(ty.getStr() + "\n")
                f.writelines([(op_str + "\n") for op_str in classified_options[ty]])
        # Default configuration
        default_configuration = self.get_different_kind_configuration(
            ConfigType.default, "0_default"
        )
        # Default as baseline
        self.baseline = default_configuration
        all_config = [default_configuration]
        
        # All negative configuration
        all_config.append(
            self.get_different_kind_configuration(
                ConfigType.all_negative, f"{len(all_config)}_all_negative"
            )
        )

        # All positive configuration
        all_config.append(
            self.get_different_kind_configuration(
                ConfigType.all_positive, f"{len(all_config)}_all_positive"
            )
        )

        # One positive sampling.
        all_positives = self.config_sampler.get_all_options(ConfigType.one_positive)
        selected_positives = get_equidistant_elements(
            all_positives, self.sampling_config.num
        )
        for options in selected_positives:
            one_positive = self.create_configuration(
                options, self.workspace, f"{len(all_config)}_one_positive"
            )
            all_config.append(one_positive)
        # One negative sampling.
        all_negatives = self.config_sampler.get_all_options(ConfigType.one_negative)
        selected_negatives = get_equidistant_elements(
            all_negatives, self.sampling_config.num
        )
        for options in selected_negatives:
            one_negative = self.create_configuration(
                options, self.workspace, f"{len(all_config)}_one_negative"
            )
            all_config.append(one_negative)


        self.config_list = [self.baseline] + [
            config for config in all_config if config != self.baseline
        ]
        # self.config_list = [all_negative_configuration]
        with open(os.path.join(self.workspace, "configure.txt"), "a") as f:
            for config in self.config_list:
                configure_script = commands_to_shell_script(config.config_cmd())
                f.write(config.tag + "\n")
                f.write(configure_script + "\n")
        
        if self.project_info.filter_configs:
            old_list = self.config_list.copy()
            self.config_list = [old_list[idx] for idx in self.project_info.filter_configs]

    def execute_prerequisites(self, config: Configuration):
        for prerequisite in self.project_info.prerequisites:
            run(prerequisite, config.project_info.build_dir, "Prerequisite", self.env)
        if self.project_info.must_make:
            self.build_clean(config)
        if self.project_info.build_type == BuildType.CMake:
            run_without_check(
                ["rm", os.path.join(config.project_info.build_dir, "CMakeCache.txt")],
                config.project_info.build_dir,
                tag="RM CMakeCache",
                env=self.env,
            )
        elif self.project_info.build_type == BuildType.Meson:
            run_without_check(
                [
                    "rm",
                    os.path.join(
                        config.project_info.build_dir, "meson-private", "cmd_line.txt"
                    ),
                    os.path.join(
                        config.project_info.build_dir, "meson-private", "coredata.dat"
                    ),
                ],
                config.project_info.build_dir,
                tag="RM Meson Build Cache",
                env=self.env,
            )

    def configure(self, config: Configuration) -> bool:
        configure_script = commands_to_shell_script(config.config_cmd())
        logger.info(f"[Configure Script] {configure_script}")
        if not os.path.exists(config.project_info.build_dir):
            logger.error(
                f"[Configure Script] Please make sure {config.project_info.build_dir} exists!"
            )
            return False
        process = subprocess.run(
            config.config_cmd(),
            cwd=config.project_info.build_dir,
            env=self.env,
            capture_output=True,
            text=True,
        )
        logger.info(
            f"[Configure Output]\nstdout:\n{process.stdout}\nstderr:\n{process.stderr}"
        )
        if process.returncode != 0:
            logger.info(f"[Configure Failed] {configure_script}")
        else:
            if self.project_info.build_type.notNeedBear():
                shutil.copy(
                    os.path.join(
                        config.project_info.build_dir, "compile_commands.json"
                    ),
                    config.compile_database,
                )

        return process.returncode == 0

    def build(self, config: Configuration) -> bool:
        if global_config.bear_version == 2:
            cmd = [GlobalConfig.bear, "--cdb", str(config.compile_database)]
        else:
            cmd = [GlobalConfig.bear, "--output", str(config.compile_database), "--"]
        cmd.extend(config.build_cmd())

        logger.info(f"[Building] {commands_to_shell_script(cmd)}")
        process = subprocess.run(
            cmd,
            cwd=config.project_info.build_dir,
            env=self.env,
            capture_output=True,
            text=True,
        )
        if process.returncode != 0:
            logger.error(f"[Build Failed] {commands_to_shell_script(cmd)}")
            logger.error(
                f"[Build Output]\nstdout:\n{process.stdout}\nstderr:\n{process.stderr}"
            )
        else:
            logger.info(f"[Build Success] {commands_to_shell_script(cmd)}")
        if self.project_info.ignore_make_error:
            return True
        return process.returncode == 0

    def build_clean(self, config: Configuration):
        if config.project_info.build_type.useMake():
            run(
                ["make", "clean"], config.project_info.build_dir, "Make Clean"
            )
        else:
            run(
                ["ninja", "clean"], config.project_info.build_dir, "Ninja Clean"
            )

    def parse_makefile(self, config: Configuration):
        if self.project_info.build_type.notNeedBear():
            # The compile_commands.json of opencv contain compile argument like -DXXX="long long",
            # compiledb doesn't perserve the "", so we use CMake's compile_commands.json.
            # TODO: compiledb support -DXXX="long long"?
            logger.info(
                "[Parse Makefile] Use compile_commands.json generated by CMake/Meson"
            )
            return True

        # Get compile_commands.json without build by parse "make -n -B -i".
        # make arguments:
        # -n: Output compile commands only;
        # -B: Don't consider incremental build;
        # -i: Ignore errors while executing.
        make_n = subprocess.run(
            ["make", "-n", "-i"],
            capture_output=True,
            text=True,
            cwd=config.project_info.build_dir,
            env=self.env,
        )
        # compiledb arguments:
        # -f: Overwrite compile_commands.json instead of just updating it.
        # -S: Do not check if source files exist in the file system.
        compiledb_cmd = ["compiledb", "-o", config.compile_database, "-f", "-S"]
        logger.info(f"[Compiledb Script] {commands_to_shell_script(compiledb_cmd)}")
        subprocess.run(
            compiledb_cmd,
            capture_output=True,
            text=True,
            cwd=config.project_info.build_dir,
            input=make_n.stdout,
            timeout=60,  # Set timeout to avoid make execute recursively.
        )

        def split_cdb_item(cdb_file):
            # Split items which command contain multiple files.
            if os.path.exists(cdb_file):
                cdb: List = json.load(open(cdb_file, "r"))
                idx = 0
                while idx < len(cdb):
                    ccmd = cdb[idx]
                    idx += 1
                    if "command" in ccmd:
                        from shlex import split

                        arguments = split(ccmd["command"])
                    else:
                        arguments = ccmd["arguments"]

                    current_file = os.path.abspath(
                        os.path.join(ccmd["directory"], ccmd["file"])
                    )
                    new_item_num = 0
                    files_in_one_command = []
                    arguments_without_files = []

                    for argument in arguments:
                        extname = os.path.splitext(argument)[1][1:]
                        if extname in {
                            "c",
                            "C",
                            "cc",
                            "CC",
                            "cp",
                            "cpp",
                            "CPP",
                            "cxx",
                            "CXX",
                            "c++",
                            "C++",
                        }:
                            # It's source code file.
                            this_file = os.path.abspath(
                                os.path.join(ccmd["directory"], argument)
                            )
                            files_in_one_command.append((this_file))
                        else:
                            arguments_without_files.append(argument)

                    for file in files_in_one_command:
                        if file != current_file:
                            # Split this item.
                            new_item = ccmd.copy()
                            new_item["file"] = file
                            if "arguments" in new_item:
                                new_item.pop("arguments")
                            new_arguments = arguments_without_files.copy()
                            new_arguments.insert(1, file)
                            new_item["command"] = " ".join(new_arguments)
                            cdb.insert(idx, new_item)
                            new_item_num += 1
                        else:
                            ccmd["file"] = current_file
                            if "arguments" in ccmd:
                                ccmd.pop("arguments")
                            new_arguments = arguments_without_files.copy()
                            new_arguments.insert(1, file)
                            ccmd["command"] = " ".join(new_arguments)

                    if new_item_num > 0:
                        logger.info(
                            f"[SPLIT CDB] Find {new_item_num} new item in {arguments}"
                        )
                        idx += new_item_num  # Skip new item

                with open(cdb_file, "w") as f:
                    json.dump(cdb, f, indent=3)

        split_cdb_item(config.compile_database)

        def filter_commands(make_n_output):
            commands = []
            buffer = []
            for line in make_n_output.split("\n"):
                line = line.rstrip()
                if not line:
                    continue
                # Merge \ at the end of line.
                if line.endswith("\\"):
                    buffer.append(line[:-1].strip())
                else:
                    buffer.append(line.strip())
                    commands.append(" ".join(buffer))
                    buffer = []

            return commands

        def dry_run(commands):
            skip_patterns = [
                r"^\s*((/[\w-]+)+/)?(gcc|clang|cc|g\+\+|clang\+\+|nvcc|ld|ar|ccache)\s",  # Compile, link.
                r"\smake\s",  # Make
                r"\smsgfmt\s",  # Don't parse .po
                r"\s-shared\b",  # Shared library.
                r"\s-shared\b",  # Shared library.
                r"\s-arch\b",  # Architecture argument.
                # r'\.(o|a|so|dylib|exe)\b',  # Target or executable file.
                # No command
                r"^\s*#",  # Comment(e.g. # This is a comment).
                r"\b(make|info|warning)\b",  # Ignore Makefile function(e.g. $(info ...))
                r"^\s*\$\(",  # Ignore variable expansion(e.g. $(RM) file.o)
            ]
            dir_stack = [config.project_info.build_dir]

            for cmd in commands:
                skip = False
                if not cmd:
                    continue

                # make[%d] Entering/Leaving directory 'path'
                entering_match = re.search(
                    r"make\[\d+\]: Entering directory \'(.+)\'", cmd
                )
                leaving_match = re.search(
                    r"make\[\d+\]: Leaving directory \'(.+?)\'", cmd
                )
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
                            cmd, shell=True, check=True, cwd=dir_stack[-1], env=self.env
                        )
                    except subprocess.CalledProcessError as e:
                        logger.info(f"[FAILED!] {cmd}\nError: {e}")
            return True

        if self.project_info.dry_run:
            logger.info(f"[DRY RUN] {config.tag}")
            make_n_commands = filter_commands(make_n.stdout)
            return dry_run(make_n_commands)
        return True

    def icebear(self, config: Configuration, cache_file):
        if config == self.baseline:
            icebear_cmd = config.icebear_cmd(update_cache=True)
        else:
            # Only record one config as baseline cache.
            icebear_cmd = config.icebear_cmd(update_cache=True, cache_file=cache_file)
        run(icebear_cmd, self.src_dir, "IceBear Running")

    def icebear_for_fdb(self, config: Configuration, cache_file):
        if config == self.baseline:
            icebear_cmd = config.icebear_cmd(prep_only=True, update_cache=True)
        else:
            # Don't update cache for non-baseline configurations.
            icebear_cmd = config.icebear_cmd(prep_only=True, update_cache=False, cache_file=cache_file)
        run(icebear_cmd, self.src_dir, "IceBear Pre-Analysis Running")

    def prepare_compilation_database(self, config):
        if self.opts.skip_prepare:
            return True
        self.execute_prerequisites(config)
        process_status = self.configure(config)
        if not process_status:
            logger.error(
                f"[Configure {config.tag}] Configure failed! Stop subsequent jobs."
            )
            return False
        if self.project_info.must_make:
            return self.build(config)
        else:
            process_status = self.parse_makefile(config)
            if not process_status:
                logger.error(
                    f"[Parse Makefile {config.tag}] Parse makefile failed! Stop subsequent jobs."
                )
                return False
        return True

    def get_candidate_config_list(self) -> List[Configuration]:
        configs_not_chosen = list(filter(
            lambda c: c not in self.chosen_config_list, self.config_list
        ))
        # If configuration has not been chosen, but its distance to all chosen configurations is zero,
        # then it won't be chosen anymore.
        all_candidates = list(filter(
            lambda c: c not in self.zero_distance_configs, configs_not_chosen
        ))
        return get_equidistant_elements(all_candidates, 5)

    def determine_chosen_configurations(self, chosen_configs: Union[None, List[Configuration]]=None):
        if chosen_configs is not None:
            logger.info(f"[Use Given Configurations] {', '.join([config.tag for config in chosen_configs])}")
            for config in chosen_configs:
                self.chosen_config_list.append(self.create_configuration(config.config_options, self.workspace, config.tag))
            return
        
        choose_process_record = os.path.join(self.workspace, "choose_process.txt")
        choose_process = []

        # Choose configurations through adaptive sampling.
        choice_rounds = 5

        # Start from baseline configuration.
        curr_config = self.baseline
        process_status = self.prepare_compilation_database(curr_config)
        if not process_status:
            logger.error(
                f"[Prepare {curr_config.tag}] Prepare compilation database failed! Stop subsequent jobs."
            )
            return
        self.icebear_for_fdb(curr_config, None)
        file_level_cache = FileLevelCache.model_validate(json.load(open(curr_config.cache_file)))
        with open(self.overall_cache_file, "w") as f:
            f.write(file_level_cache.model_dump_json(indent=3))
        self.chosen_config_list.append(curr_config)
        choose_process.append(f"{curr_config.tag}")

        while choice_rounds:
            choice_rounds -= 1
            candidate_config_list = self.get_candidate_config_list()
            if not candidate_config_list:
                break
            chosen_config = None
            max_dis = 0
            choose_process.append("")
            for config in candidate_config_list:
                logger.TAG = f"{self.project_name}/{config.tag}"
                # 1. Calculate incremental database by icebear.
                process_status = self.prepare_compilation_database(config)
                if not process_status:
                    continue
                self.icebear_for_fdb(config, self.overall_cache_file)
                # 2. Calculate distance.
                curr_flc = FileLevelCache.model_validate(json.load(open(config.cache_file)))
                curr_dis = file_level_cache.distance(curr_flc)
                logger.info(f"[Distance] {config.tag}: {curr_dis}")
                choose_process[-1] += f"{config.tag}:{curr_dis} "
                # 3. Choose the configuration which introduce largest distance.
                if curr_dis > max_dis:
                    max_dis = file_level_cache.distance(curr_flc)
                    chosen_config = config
                else:
                    logger.info(f"[Not Chosen] {config.tag}: {curr_dis} < {max_dis}")
                    if curr_dis == 0:
                        self.zero_distance_configs.add(config)
                        print([config.tag for config in self.zero_distance_configs])
            if chosen_config:
                curr_config = chosen_config
                self.chosen_config_list.append(chosen_config)
                choose_process[-1] += f"=> {chosen_config.tag}"
                chosen_flc = FileLevelCache.model_validate(json.load(open(chosen_config.cache_file)))
                file_level_cache.root.update(chosen_flc.root)
                with open(self.overall_cache_file, "w") as f:
                    f.write(file_level_cache.model_dump_json(indent=3))
        
        with open(choose_process_record, "w") as f:
            f.write("\n".join(choose_process))

    def clean_workspace_preprocess(self):
        chosen_tags = {config.tag for config in self.chosen_config_list}
        for config in self.config_list:
            if config.tag not in chosen_tags:
                shutil.rmtree(config.prep_path, ignore_errors=True)

    def process_every_configuration(self):
        if not self.opts.prep_only:
            inc_levels = [self.opts.inc]
            if self.opts.inc == "all":
                inc_levels = ["noinc", "file", "func"]
            for inc_level in inc_levels:
                remove_file(
                    os.path.join(self.workspace, f"reports_summary_{inc_level}.json")
                )
                remove_file(
                    os.path.join(self.workspace, f"unique_reports_{inc_level}.json")
                )

        if self.opts.clean_cache:
            run(
                ["rm", self.overall_cache_file],
                self.workspace,
                tag="RM Cache",
                env=self.env,
            )
            logger.info(f"[Clean Cache] {self.overall_cache_file}")

        for config in self.chosen_config_list:
            logger.TAG = f"{self.project_name}/{config.tag}"
            process_status = self.prepare_compilation_database(config)
            if not process_status:
                continue
            # if os.path.exists(config.cache_file):
            #     shutil.copyfile(
            #         config.cache_file, os.path.join(config.prep_path, os.path.basename(config.cache_file))
            #     )
            self.icebear(config, self.overall_cache_file)
