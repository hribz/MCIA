#ifndef FILE_SUMMARY_H
#define FILE_SUMMARY_H

#include <clang/AST/ASTContext.h>
#include <clang/AST/Decl.h>
#include <clang/AST/Stmt.h>
#include <clang/AST/TypeOrdering.h>
#include <clang/Basic/SourceLocation.h>
#include <clang/Basic/SourceManager.h>
#include <llvm/ADT/DenseSet.h>
#include <llvm/Support/JSON.h>

#include <map>
#include <vector>

using namespace clang;

enum FileKind { SYSTEM, USER, MAIN, UNKNOWN };

inline const std::string getFileKindString(FileKind kind) {
  switch (kind) {
  case SYSTEM:
    return "SYSTEM";
  case USER:
    return "USER";
  case MAIN:
    return "MAIN";
  default:
    return "UNKNOWN";
  }
}

template <typename T>
inline void addItemToMap(llvm::DenseMap<FileID, llvm::DenseSet<T>> &Map,
                         const FileID &FileID, const T &Item) {
  if (Map.find(FileID) == Map.end()) {
    Map[FileID] = llvm::DenseSet<T>();
    Map[FileID].insert(Item);
  } else {
    Map[FileID].insert(Item);
  }
}

inline SourceLocation getDeclBodyLocation(SourceManager &SM, const Decl *D) {
  const Stmt *Body = D->getBody();
  SourceLocation SL = Body ? Body->getBeginLoc() : D->getLocation();
  return SM.getExpansionLoc(SL);
}

struct FileCoverageSummary {
  std::vector<std::pair<unsigned, unsigned>> SkippedRanges;
  unsigned TotalLines = 0;
  FileKind kind;

  llvm::json::Object exportToJSON() {
    llvm::json::Object FileCoverageJSON;
    FileCoverageJSON.try_emplace("total", TotalLines);
    llvm::json::Array skipped_ranges = llvm::json::Array();
    unsigned int skipped_lines = 0;
    for (auto &range : SkippedRanges) {
      skipped_ranges.push_back({range.first, range.second});
      skipped_lines += range.second - range.first;
    }
    FileCoverageJSON.try_emplace("skipped", std::move(skipped_ranges));
    auto coverage = TotalLines == 0
                        ? 100.0
                        : (100.0 * (TotalLines - skipped_lines) / TotalLines);
    FileCoverageJSON.try_emplace("coverage", coverage);
    return FileCoverageJSON;
  }
};

class FileSummary {
public:
  unsigned TotalCGNodes = 0;
  llvm::DenseMap<FileID, llvm::DenseSet<const Decl *>> FunctionsMap;
  llvm::DenseMap<FileID, llvm::DenseSet<const Decl *>> VirtualFunctions;
  llvm::DenseMap<FileID, llvm::DenseSet<QualType>>
      TypesMayUsedByFP; // Function types maybe
  llvm::DenseMap<FileID, unsigned int> TotalCallCount;
  // used by function pointer call.
  llvm::DenseMap<FileID, unsigned int> TotalIndirectCallByVF;
  llvm::DenseMap<FileID, unsigned int> TotalIndirectCallByFP;

  std::map<FileID, FileCoverageSummary> FileCoverageSummaries;
  unsigned UserTotalLines = 0;
  unsigned UserSkippedLines = 0;
  unsigned MainTotalLines = 0;
  unsigned MainSkippedLines = 0;

  const SourceManager *SM;

  void exportToJSON(const std::string &OutputPath) {
    std::error_code EC;
    llvm::raw_fd_ostream OutStream(OutputPath, EC);
    if (EC) {
      llvm::errs() << "Can not open file: " << EC.message() << "\n";
      return;
    }

    llvm::json::Object FileSummaryJSON;

    for (auto item : FileCoverageSummaries) {
      // // skip system and unknown files.
      // if (item.second.kind == SYSTEM || item.second.kind == UNKNOWN) {
      //   continue;
      // }
      auto FE = SM->getFileEntryForID(item.first);
      std::string FileName;
      if (FE) {
        FileName = FE->tryGetRealPathName().str();
      } else {
        FileName = "built-in";
      }
      llvm::json::Object FileObject = llvm::json::Object(
          {{"CG Nodes", FunctionsMap[item.first].size()},
           {"Call Exprs", TotalCallCount[item.first]},
           {"VF", VirtualFunctions[item.first].size()},
           {"VFIC", TotalIndirectCallByVF[item.first]},
           {"FPTY", TypesMayUsedByFP[item.first].size()},
           {"FPIC", TotalIndirectCallByFP[item.first]},
           {"kind", getFileKindString(item.second.kind)},
           {"Coverage", std::move(item.second.exportToJSON())}});
      FileSummaryJSON.try_emplace(FileName, std::move(FileObject));
    }

    // Output to string.
    llvm::json::Value FileSummaryValue(std::move(FileSummaryJSON));
    std::string json_str;
    llvm::raw_string_ostream os(json_str);
    os << FileSummaryValue;
    os.flush();
    // Output to file.
    OutStream << json_str;
  }
};

#endif // FILE_SUMMARY_H