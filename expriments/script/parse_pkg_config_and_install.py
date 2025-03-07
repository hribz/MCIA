#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys

# 配置路径映射（如果某些库的包名与pkg-config名不同）
PKG_MAP = {
    "lensfun": "liblensfun-dev",
    "x264": "libx264-dev",
    "x265": "libx265-dev",
    "frei0r": "frei0r-plugins-dev",
    "gnutls": "libgnutls28-dev",
    "jni": "openjdk-17-jdk",
    "ladspa": "ladspa-sdk",
    "lv2": "liblilv-dev",
    "glslang": "glslang-tools",
    "openjpeg": "libopenjp2-7-dev",
    "rsvg": "librsvg2-dev",
    "v4l2": "libv4l-dev",
    "zmq": "libzmq3-dev",
    "opencl": "ocl-icd-opencl-dev",
    "openssl": "libssl-dev",
    "xcb": "libxcb1-dev"
    # 添加其他需要手动映射的库
}

def parse_configure(file_path):
    """解析FFmpeg的configure文件，提取启用的库及其依赖条件"""
    pattern = re.compile(
        r"^\s*(enabled|disabled)\s+(\w+)\s+&&"
    )
    dependencies = []

    with open(file_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # 匹配类似 "enabled liblensfun && require_pkg_config ..." 的行
            match = pattern.match(line)
            if match:
                state, lib = match.groups()
                apt_pkg = lib[3:] if lib.startswith("lib") else lib
                apt_pkg = apt_pkg.replace("_", "-")
                if state == "enabled":
                    dependencies.append({
                        "lib": lib,
                        "apt_pkg": PKG_MAP.get(apt_pkg, f"lib{apt_pkg}-dev")
                    })
    return dependencies

def install_packages(dependencies):
    """尝试通过apt安装依赖库，并输出结果"""
    results = []
    for dep in dependencies:
        pkg = dep["apt_pkg"]
        print(f"\n尝试安装库: {dep['lib']} ({pkg})")

        # 检查是否已安装
        check_installed = subprocess.run(
            ["dpkg", "-s", pkg],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        if check_installed.returncode == 0:
            results.append((dep["lib"], "已安装", pkg))
            continue

        # 尝试安装
        install_cmd = ["sudo", "apt", "install", "-y", pkg]
        proc = subprocess.run(install_cmd, capture_output=True, text=True)

        if proc.returncode == 0:
            results.append((dep["lib"], "安装成功", pkg))
        else:
            results.append((dep["lib"], "安装失败", pkg))
    
    return results

def filter_deps(deps, project_name):
    real_deps = []
    # options which are not third library.
    # avisynth has been installed by building source code.
    filter_set = {
        'ossfuzz', 'cross-compile', 'debug', 'pic', 'thumb', 'avisynth', 'rpath', 'ftrapv', 'opencv'
    }
    projects = json.load(open('../cleaned_options.json', 'r'))
    for project in projects:
        if project_name != project['project'].split("/")[1]:
            continue
        key_of_options = [op['key'].replace("--enable-", "").replace("lib", "") for op in project['config_options']]
        for dep in deps:
            lib = dep['lib']
            apt_pkg = lib[3:] if lib.startswith("lib") else lib
            apt_pkg = apt_pkg.replace("_", "-")
            if apt_pkg in filter_set:
                continue
            if apt_pkg in key_of_options:
                real_deps.append(dep)

    return real_deps

def main():
    if len(sys.argv) != 3:
        print("用法: ./install_ffmpeg_deps.py <configure文件路径> <project名称>")
        sys.exit(1)

    deps = parse_configure(sys.argv[1])
    if not deps:
        print("未找到需要处理的依赖项")
        return

    deps = filter_deps(deps, sys.argv[2])

    print("检测到以下依赖库需要安装:")
    for dep in deps:
        print(f"  - {dep['lib']} (APT包名: {dep['apt_pkg']})")

    input("\n按Enter键开始安装（需要sudo权限）...")
    results = install_packages(deps)

    print("\n安装结果:")
    failed_results = []
    for lib, status, pkg in results:
        print(f"  - {lib.ljust(15)} [{pkg}]: {status}")
        if status == "安装失败":
            failed_results.append(f"\"--enable-{lib.replace("_", "-")}\",\n")
    
    configure_dir = os.path.dirname(sys.argv[1])
    failed_file = os.path.join(os.path.dirname(configure_dir), 'failed.txt')
    with open(failed_file, 'w') as f:
        f.writelines(failed_results)

if __name__ == "__main__":
    main()