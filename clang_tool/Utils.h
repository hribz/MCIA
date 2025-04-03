#ifndef UTILS_H
#define UTILS_H

#include <string>

class IncOptions {
public:
  bool PrintLoc = false;
  bool ClassLevelTypeChange = true;
  bool FieldLevelTypeChange = false;

  bool DumpCG = false;
  bool DumpToFile = true;
  bool DumpUSR = false;
  bool DumpANR = false;
  bool CTU = false;
  bool DebugPP = false;

  std::string RFPath;
  std::string CppcheckRFPath;
  std::string FilePath;
};

#endif // UTILS_H