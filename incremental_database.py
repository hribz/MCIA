from pydantic import BaseModel, RootModel
from typing import Dict, List

class FileLevelCache(RootModel):
    root: Dict[str, List[str]] = {}

    def distance(self, other: 'FileLevelCache') -> int:
        """Calculate the distance between two FileLevelCache instances."""
        dis = 0
        for key in other.root.keys():
            if key not in self.root:
                dis += 1
            else:
                file_hashes_self = set(self.root[key])
                file_hashes_other = set(other.root[key])
                if file_hashes_other.difference(file_hashes_self):
                    dis += 1
        return dis
    
