import os
import re
from typing import Dict, List, Optional

from pydantic import BaseModel, RootModel

class FileLevelCache(RootModel):
    root: Dict[str, List[str]] = {}

    @staticmethod
    def _normalize_build_dir_text(text: str, build_root: str, placeholder: str) -> str:
        normalized_build_root = os.path.normpath(build_root)
        path_sep_pattern = r"(?:/|\\\\)"
        pattern = rf"{re.escape(normalized_build_root)}{path_sep_pattern}[^/\\\\\s\"']+"
        replacement = f"{normalized_build_root}{os.sep}{placeholder}"
        return re.sub(pattern, replacement, text)

    def normalize_build_dir(self, build_root: Optional[str], placeholder: str = "__BUILD_DIR__") -> 'FileLevelCache':
        if not build_root:
            return self

        normalized_root: Dict[str, List[str]] = {}
        for key, values in self.root.items():
            normalized_key = self._normalize_build_dir_text(key, build_root, placeholder)
            normalized_values = [
                self._normalize_build_dir_text(value, build_root, placeholder)
                for value in values
            ]
            existing_values = normalized_root.setdefault(normalized_key, [])
            for value in normalized_values:
                if value not in existing_values:
                    existing_values.append(value)

        return FileLevelCache(root=normalized_root)

    def distance(self, other: 'FileLevelCache', build_root: Optional[str] = None) -> int:
        """Calculate the distance between two FileLevelCache instances."""
        if build_root:
            lhs = self.normalize_build_dir(build_root)
            rhs = other.normalize_build_dir(build_root)
        else:
            lhs = self
            rhs = other

        dis = 0
        for key in rhs.root.keys():
            if key not in lhs.root:
                dis += 1
            else:
                file_hashes_self = set(lhs.root[key])
                file_hashes_other = set(rhs.root[key])
                if file_hashes_other.difference(file_hashes_self):
                    dis += 1
        return dis
    
