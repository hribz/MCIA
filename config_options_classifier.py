import argparse
import os
import random
import re
import json
import subprocess
import sys
import time
from typing import List, Dict
from openai import OpenAI, RateLimitError
from dotenv import load_dotenv

from project import BuildType

class ConfigClassifier:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("API_KEY"), base_url=os.getenv("BASE_URL"))
        
    def _generate_prompt(self, config_item: Dict) -> str:
        return f"""
I will provide some configuration options from C/C++ projects, please classify them according to follow rules:

## option type
1. positive: Enable some features when it is turn on or set to 1 (e.g. --enable-foo, WITH_FOO=1)
2. negative: Disable some features when it is turn on or set to 1 (e.g. --disable-foo, WITHOUT_FOO=1)
3. options: Choose value from predefined options (e.g. BUILD_TYPE=Debug/Release)
4. ignore: Options that do not affect the compilation results of source files. (e.g. --prefix, --libdir)

## The option to classify
{ config_item }

## Output JSON
{{
    "key": "--enable-foo",
    "values": [],
    "kind": "positive",
    "description": "the description of this option",
    "confidence": "0-1",
    "reason": "the reason of classification"
}}
field explaination:
key: name of the option, only reserve --xxx if there are alias names
values: all potential values, only consider this field when there is = (e.g. --xxx=no)
kind: positive|negative|options|ignore
"""

    def classify_item(self, config_item: Dict) -> Dict:
        response = self.client.chat.completions.create(
            model=os.getenv("MODEL"),
            messages=[{
                "role": "user",
                "content": self._generate_prompt(config_item)
            }],
            temperature=0.3
        )
        return self._parse_response(response.choices[0].message.content)

    def _parse_response(self, response: str) -> Dict:
        # clean markdown symbol.
        cleaned = re.sub(r'^```json|```$', '', response, flags=re.IGNORECASE).strip()
        data = json.loads(cleaned)
        return {
            "key": data["key"],
            "values": data.get("values", []),
            "kind": data["kind"],
            "description": data["description"],
            "confidence": float(data["confidence"]),
            "reason": data["reason"]
        }

class EnhancedConfigClassifier(ConfigClassifier):
    def __init__(self):
        super().__init__()
        self.counter = 0
        self.start_time = None
        
    def _print_debug(self, message: str, level: str = "INFO"):
        colors = {
            "INFO": "\033[94m",
            "SUCCESS": "\033[92m",
            "WARNING": "\033[93m",
            "ERROR": "\033[91m",
            "END": "\033[0m"
        }
        timestamp = time.strftime("%H:%M:%S")
        print(f"{colors.get(level, '')}[{timestamp} {level}] {message}{colors['END']}", 
              file=sys.stderr)

    def classify_item(self, config_item) -> Dict:
        if self.counter == 0:
            self.start_time = time.time()
            
        self.counter += 1
        item_number = f"Item {self.counter}"
        
        # 显示处理进度
        self._print_debug(f"Processing {item_number}: {config_item}")
        
        # 记录API请求开始时间
        start_api = time.time()
        self._print_debug(f"Sending request for {item_number}", "INFO")
            
        try:
            result = super().classify_item(config_item)
            
        except Exception as e:
            # 显示错误信息
            self._print_debug(f"Failed to process {item_number}: {str(e)}", "ERROR")
            raise
        
        # 显示API响应时间
        api_time = time.time() - start_api
        self._print_debug(f"Received response for {item_number} (Time: {api_time:.2f}s)", "SUCCESS")
        
        # 显示分类结果
        status_icon = "✓" if result["confidence"] > 0.7 else "?"
        result_summary = (
            f"{status_icon} Classification: {result['kind']} "
            f"(Confidence: {result['confidence']:.2f})"
        )
        self._print_debug(f"{item_number} Result: {result_summary}\nReason: {result['reason']}")

        return result
            
        
    def print_summary(self, total_items: int):
        """输出处理摘要"""
        elapsed = time.time() - self.start_time
        self._print_debug("\nProcessing Summary:", "INFO")
        self._print_debug(f"Total items  : {total_items}")
        self._print_debug(f"Processed    : {self.counter}")
        self._print_debug(f"Elapsed time : {elapsed:.2f}s")
        self._print_debug(f"Speed        : {self.counter/elapsed:.2f} items/sec")

class ResilientClassifier(EnhancedConfigClassifier):
    def __init__(self):
        super().__init__()
        self.max_retries = 5
        self.min_delay = 1.0  # 初始延迟1秒
        self.max_delay = 60.0  # 最大延迟60秒
        self.request_count = 0
        self.last_request_time = time.time()
        
    def _calculate_backoff(self, attempt: int) -> float:
        """指数退避算法计算等待时间"""
        backoff = self.min_delay * (2**attempt) + random.uniform(0, 1)
        return min(backoff, self.max_delay)
    
    def _rate_limit_delay(self):
        """控制请求速率（假设限制为3000 RPM）"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        # 计算需要保持的间隔（例如每分钟3000次请求 ≈ 每请求间隔0.02秒）
        required_interval = 0.02  # 可根据实际限额调整
        
        if time_since_last < required_interval:
            sleep_time = required_interval - time_since_last
            time.sleep(sleep_time)
            
        self.last_request_time = time.time()
    
    def classify_item(self, config_item) -> Dict:
        """带速率控制和自动重试的分类方法"""
        for attempt in range(self.max_retries):
            try:
                self._rate_limit_delay()  # 前置速率控制
                
                self._print_debug(f"Attempt {attempt+1}/{self.max_retries}")
                result = super().classify_item(config_item)
                self.request_count += 1
                
                # 成功时重置延迟
                self.min_delay = max(1.0, self.min_delay * 0.9)
                return result
                
            except RateLimitError as e:
                backoff = self._calculate_backoff(attempt)
                self._print_debug(
                    f"Rate limit reached. Backing off for {backoff:.2f}s", 
                    "WARNING"
                )
                
                # 动态调整延迟参数
                self.min_delay = min(self.max_delay, self.min_delay * 1.5)
                time.sleep(backoff)
                
            except Exception as e:
                self._print_debug(f"Unexpected error: {str(e)}", "ERROR")
                raise
                
        return {
            "classification": "ignore",
            "values": [],
            "confidence": 0.0,
            "reason": "Max retries exceeded"
        }

class ConfigExtractor:
    @staticmethod
    def from_cmake(build_dir, src_dir) -> List[Dict]:
        result = subprocess.run(
            ["cmake", "-LH", "-B", build_dir, "-S", src_dir],
            capture_output=True,
            text=True
        )
        items = []
        current_desc = []
        
        for line in result.stdout.split("\n"):
            if line.startswith("//"):
                current_desc.append(line[3:].strip())
            elif match := re.match(r"^([A-Za-z_]+):([A-Z]+)=(.+)$", line.strip()):
                items.append({
                    "option": line.strip(),
                    "description": " ".join(current_desc)
                })
                current_desc = []
        return items

    @staticmethod
    def from_autoconf(configure_path, cwd) -> List[Dict]:
        result = subprocess.run(
            [configure_path, '--help'],
            capture_output=True,
            text=True,
            cwd=cwd
        )
        items = []

        in_option = False
        for line in result.stdout.split("\n"):
            line = line.strip()
            if len(line) == 0 or line.endswith(":"):
                in_option = False
                continue
            elif line.startswith("-"):
                in_option = True
                items.append(line)
            elif len(items)>0 and in_option:
                items[-1] += f" {line}"
        return items

def get_if_exists(dict, key, default=None):
    return dict[key] if key in dict else default

def handle_project(projects, opts, classifier: ResilientClassifier):
    pwd = os.path.abspath(".")
    projects_root_dir = os.path.join(pwd, "expriments")
    model_name = os.getenv("MODEL").split("/")[-1]

    for project in projects:
        repo_name = project['project']
        build_type = BuildType.getType(project['build_type'])
        out_of_tree = get_if_exists(project, 'out_of_tree', True)
        repo_dir = os.path.join(projects_root_dir, repo_name)

        if opts.repo and opts.repo != repo_name and opts.repo != os.path.basename(repo_dir):
            continue

        build_dir = f"{repo_dir}_build" if out_of_tree else repo_dir
        
        config_items = []
        if build_type == BuildType.CMake:
            config_items = ConfigExtractor.from_cmake(build_dir, repo_dir)
        elif build_type == BuildType.AutoConf:
            config_items = ConfigExtractor.from_autoconf(os.path.join(repo_dir, 'configure'), repo_dir)
        
        # classification.
        results = []
        for (idx, item) in enumerate(config_items):
            classification = classifier.classify_item(item)
            if classification["kind"] != "ignore":
                results.append(classification)

            if idx % 3 == 0:
                classifier._print_debug(f"Progress: {idx}/{len(config_items)} ({idx/len(config_items):.0%})")
                project["config_options"] = results
                # Store results.
                json.dump(projects, open(f'expriments/config_options_{model_name}.json', 'w'), indent=3)
        
        project["config_options"] = results
        classifier.print_summary(len(config_items))
        classifier.counter = 0
    
    json.dump(projects, open(f'expriments/config_options_{model_name}.json', 'w'), indent=4)


class MCArgumentParser():
    def __init__(self):
        self.parser = argparse.ArgumentParser()
        self.parser.add_argument('--repo', type=str, dest='repo', help='Only analyse specific repos.')
    
    def parse_args(self, args):
        return self.parser.parse_args(args)

def main(args):
    load_dotenv()
    parser = MCArgumentParser()
    opts = parser.parse_args(args)
    projects = json.load(open('expriments/config_options.json', 'r'))
    classifier = ResilientClassifier()
    handle_project(projects, opts, classifier)


if __name__ == '__main__':
    main(sys.argv[1:])