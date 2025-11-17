import json
import os
import re
import subprocess
import random
from typing import Dict, List, Set, Union

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
        # Strategy selection
        self.strategy = getattr(self.opts, "strategy", "preset")
        self.candidate_size = getattr(self.opts, "candidate_size", 5)
        self.stop_threshold = getattr(self.opts, "stop_threshold", 0)
        self.stop_patience = getattr(self.opts, "stop_patience", 3)
        self.random_seed = getattr(self.opts, "random_seed", 0)
        self.max_round_retries = max(0, getattr(self.opts, "max_round_retries", 3))
        self.max_random_options = max(1, getattr(self.opts, "max_random_options", 5))
        self.max_rounds = max(0, getattr(self.opts, "max_rounds", 50))
        self.rand = random.Random(self.random_seed)

        if self.strategy == "preset":
            self.configuration_sampling()
        else:
            self.configuration_sampling_random_space()

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

    def configuration_sampling_random_space(self):
        # Record options classification like the preset strategy
        classified_options = {ty: [] for ty in OptionType}
        for option in self.config_sampler.options:
            classified_options[option.kind].append(
                f"{option.option} on:{option.on_value} off:{option.off_value}"
            )
        with open(os.path.join(self.workspace, "configure.txt"), "w") as f:
            for ty in OptionType:
                f.write(ty.getStr() + "\n")
                f.writelines([(op_str + "\n") for op_str in classified_options[ty]])

        # Baseline as default configuration (no options)
        default_configuration = self.get_different_kind_configuration(
            ConfigType.default, "0_default"
        )
        self.baseline = default_configuration
        self.config_list = [self.baseline]
        # Used to avoid generating duplicate random option sets
        self._generated_hashes = set()
        # Seed hashes with baseline
        self._generated_hashes.add(self.config_sampler.get_options_hash(self.baseline.config_options))

    def _random_option_set(self) -> List[str]:
        """Generate a random, constraint-aware option list drawn from the full value space."""
        options: List[str] = []
        option_to_idx: Dict[str, int] = {}
        conflict_options = set()

        def add_to_options(op: Union[str, None], overwrite: bool):
            nonlocal options, option_to_idx
            if op is None:
                return
            key = op.split("=")[0]
            if key in option_to_idx:
                if overwrite:
                    options[option_to_idx[key]] = op
            else:
                option_to_idx[key] = len(options)
                options.append(op)

        def handle_switch(option, turn_on: bool) -> bool:
            nonlocal conflict_options
            op, state = (option.positive() if turn_on else option.negative())
            # state means whether this option is considered "on" semantically
            if state:
                if option.option not in conflict_options:
                    conflict_options = conflict_options.union(option.conflict)
                    # Check combination conflicts
                    for com_op in option.combination:
                        com_key = com_op.split("=")[0]
                        if com_key in conflict_options and com_op != option.negative()[0]:
                            return False
                    add_to_options(op, False)
                    for com_op in option.combination:
                        add_to_options(com_op, True)
                else:
                    # If in conflict set, try to force negative value
                    add_to_options(option.negative()[0], True)
            else:
                add_to_options(op, False)
            return True

        # Shuffle options to explore different combinations
        shuffled = self.project_info.options.copy()
        self.rand.shuffle(shuffled)

        selected_options = shuffled[: min(len(shuffled), self.max_random_options)]

        for option in selected_options:
            # Switch options: randomly on/off, try alternative if conflict
            if option.is_switch():
                first_try = bool(self.rand.getrandbits(1))
                if not handle_switch(option, first_try):
                    # Try the opposite
                    handle_switch(option, not first_try)
                continue

            # Multi-value options: choose a random value if available
            if option.values and len(option.values) > 0:
                value = self.rand.choice(option.values)
                add_to_options(f"{option.option}={value}", True)
            # else: skip if no values

        return options

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
        choose_process_details: List[Dict] = []

        def snapshot_options(config: Configuration) -> List[str]:
            return list(config.config_options)

        def mark_chosen(round_info: Dict, chosen_tag: str, max_dis: int):
            round_info["chosen"] = chosen_tag
            round_info["max_distance"] = max_dis
            for cand in round_info["candidates"]:
                if cand["tag"] == chosen_tag:
                    cand["chosen"] = True
                    break

        def append_stop(reason: str):
            choose_process_details.append({"type": "stop", "reason": reason})

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
        choose_process_details.append(
            {
                "type": "baseline",
                "tag": curr_config.tag,
                "options": snapshot_options(curr_config),
            }
        )

        round_counter = 0
        if self.strategy == "preset":
            while choice_rounds:
                choice_rounds -= 1
                candidate_config_list = self.get_candidate_config_list()
                if not candidate_config_list:
                    append_stop("No more preset candidates available.")
                    break
                round_counter += 1
                round_info: Dict = {
                    "type": "round",
                    "round": round_counter,
                    "strategy": "preset",
                    "candidates": [],
                }
                chosen_config = None
                max_dis = 0
                for config in candidate_config_list:
                    logger.TAG = f"{self.project_name}/{config.tag}"
                    # 1. Calculate incremental database by icebear.
                    process_status = self.prepare_compilation_database(config)
                    if not process_status:
                        round_info["candidates"].append(
                            {
                                "tag": config.tag,
                                "result": "prepare-failed",
                                "options": snapshot_options(config),
                            }
                        )
                        continue
                    self.icebear_for_fdb(config, self.overall_cache_file)
                    # 2. Calculate distance.
                    curr_flc = FileLevelCache.model_validate(json.load(open(config.cache_file)))
                    curr_dis = file_level_cache.distance(curr_flc)
                    logger.info(f"[Distance] {config.tag}: {curr_dis}")
                    round_info["candidates"].append(
                        {
                            "tag": config.tag,
                            "result": "distance",
                            "distance": curr_dis,
                            "options": snapshot_options(config),
                        }
                    )
                    # 3. Choose the configuration which introduce largest distance.
                    if curr_dis > max_dis:
                        max_dis = curr_dis
                        chosen_config = config
                    else:
                        logger.info(f"[Not Chosen] {config.tag}: {curr_dis} < {max_dis}")
                        if curr_dis == 0:
                            self.zero_distance_configs.add(config)
                if chosen_config:
                    curr_config = chosen_config
                    self.chosen_config_list.append(chosen_config)
                    mark_chosen(round_info, chosen_config.tag, max_dis)
                    chosen_flc = FileLevelCache.model_validate(json.load(open(chosen_config.cache_file)))
                    file_level_cache.root.update(chosen_flc.root)
                    with open(self.overall_cache_file, "w") as f:
                        f.write(file_level_cache.model_dump_json(indent=3))
                choose_process_details.append(round_info)
        else:
            low_rounds = 0
            round_idx = 0
            consecutive_failures = 0
            while True:
                if self.max_rounds and round_idx >= self.max_rounds:
                    logger.info(
                        f"[Random-Space] Stop condition met: reached max rounds limit ({self.max_rounds})."
                    )
                    append_stop(
                        f"Reached max rounds limit ({self.max_rounds})."
                    )
                    break
                round_idx += 1
                round_counter += 1
                round_info = {
                    "type": "round",
                    "round": round_counter,
                    "strategy": "random-space",
                    "candidates": [],
                }

                # Generate reproducible candidate set for this round
                candidate_config_list: List[Configuration] = []
                attempt = 0
                while len(candidate_config_list) < self.candidate_size and attempt < self.candidate_size * 3:
                    attempt += 1
                    options = self._random_option_set()
                    options_hash = self.config_sampler.get_options_hash(options)
                    if options_hash in getattr(self, "_generated_hashes", set()):
                        continue
                    tag = f"r{round_idx}_c{len(candidate_config_list)}"
                    cfg = self.create_configuration(options, self.workspace, tag)
                    self.config_list.append(cfg)  # Track for cleanup
                    candidate_config_list.append(cfg)
                    self._generated_hashes.add(options_hash)

                if not candidate_config_list:
                    logger.info("[Random-Space] No new candidates generated; scheduling retry.")
                    round_info["note"] = "No candidates generated."
                    choose_process_details.append(round_info)
                    consecutive_failures += 1
                    if consecutive_failures > self.max_round_retries:
                        append_stop(
                            f"Exceeded max consecutive failed rounds ({self.max_round_retries}) due to empty candidate sets."
                        )
                        break
                    continue

                chosen_config = None
                max_dis = -1
                for config in candidate_config_list:
                    logger.TAG = f"{self.project_name}/{config.tag}"
                    process_status = self.prepare_compilation_database(config)
                    if not process_status:
                        round_info["candidates"].append(
                            {
                                "tag": config.tag,
                                "result": "prepare-failed",
                                "options": snapshot_options(config),
                            }
                        )
                        continue
                    self.icebear_for_fdb(config, self.overall_cache_file)
                    curr_flc = FileLevelCache.model_validate(json.load(open(config.cache_file)))
                    curr_dis = file_level_cache.distance(curr_flc)
                    logger.info(f"[Distance] {config.tag}: {curr_dis}")
                    round_info["candidates"].append(
                        {
                            "tag": config.tag,
                            "result": "distance",
                            "distance": curr_dis,
                            "options": snapshot_options(config),
                        }
                    )
                    if curr_dis > max_dis:
                        max_dis = curr_dis
                        chosen_config = config

                if chosen_config is None:
                    logger.info("[Random-Space] All candidates failed; scheduling retry.")
                    round_info["note"] = "All candidates failed to prepare or analyze."
                    choose_process_details.append(round_info)
                    consecutive_failures += 1
                    if consecutive_failures > self.max_round_retries:
                        append_stop(
                            f"Exceeded max consecutive failed rounds ({self.max_round_retries}) due to candidate failures."
                        )
                        break
                    continue

                # Successful round resets failure counter
                consecutive_failures = 0

                if max_dis <= self.stop_threshold:
                    low_rounds += 1
                else:
                    low_rounds = 0

                curr_config = chosen_config
                self.chosen_config_list.append(chosen_config)
                mark_chosen(round_info, chosen_config.tag, max_dis)
                chosen_flc = FileLevelCache.model_validate(json.load(open(chosen_config.cache_file)))
                file_level_cache.root.update(chosen_flc.root)
                with open(self.overall_cache_file, "w") as f:
                    f.write(file_level_cache.model_dump_json(indent=3))

                choose_process_details.append(round_info)

                if low_rounds >= self.stop_patience:
                    logger.info(
                        f"[Random-Space] Stop condition met: max_dis <= {self.stop_threshold} for {self.stop_patience} consecutive rounds."
                    )
                    append_stop(
                        f"Reached stop condition: max distance <= {self.stop_threshold} for {self.stop_patience} consecutive rounds."
                    )
                    break

        def write_choose_process(details: List[Dict], output_path: str):
            lines: List[str] = []

            def write_options(option_list: List[str], indent: str):
                if not option_list:
                    lines.append(f"{indent}(none)")
                else:
                    for i in range(0, len(option_list), 5):
                        chunk = option_list[i:i+5]
                        lines.append(f"{indent}- {' '.join(chunk)}")

            for entry in details:
                if entry.get("type") == "baseline":
                    lines.append("Baseline")
                    lines.append(f"  tag: {entry['tag']}")
                    lines.append("  options:")
                    write_options(entry.get("options", []), "    ")
                    lines.append("")
                elif entry.get("type") == "round":
                    lines.append(f"Round {entry['round']} ({entry['strategy']})")
                    if entry.get("note"):
                        lines.append(f"  note: {entry['note']}")
                    for cand in entry.get("candidates", []):
                        if cand.get("result") == "prepare-failed":
                            lines.append(f"  - {cand['tag']}: prepare failed")
                        else:
                            status = f"distance={cand.get('distance', 'n/a')}"
                            if cand.get("chosen"):
                                status += " [chosen]"
                            lines.append(f"  - {cand['tag']}: {status}")
                        lines.append("      options:")
                        write_options(cand.get("options", []), "        ")
                    lines.append("")
                elif entry.get("type") == "stop":
                    lines.append(f"Stop: {entry['reason']}")
                    lines.append("")

            if lines and lines[-1] == "":
                lines.pop()

            with open(output_path, "w") as f:
                f.write("\n".join(lines))

        write_choose_process(choose_process_details, choose_process_record)

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
