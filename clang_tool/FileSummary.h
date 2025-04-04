#ifndef FILE_SUMMARY_H
#define FILE_SUMMARY_H

#include <clang/AST/Decl.h>
#include <clang/Basic/SourceLocation.h>
#include <llvm/ADT/DenseSet.h>
#include <llvm/Support/JSON.h>
#include <map>
#include <vector>

using namespace clang;

enum FileKind { SYSTEM, USER, MAIN, UNKNOWN };

struct FileCoverageSummary {
  std::string FileName;
  std::vector<std::pair<unsigned, unsigned>> SkippedRanges;
  unsigned TotalLines = 0;
  FileKind kind;

  llvm::json::Object exportToJSON() {
    llvm::json::Object FileCoverageJSON;
    FileCoverageJSON.try_emplace("file", FileName);
    FileCoverageJSON.try_emplace("total", TotalLines);
    llvm::json::Array skipped = llvm::json::Array();
    for (auto &range : SkippedRanges) {
      skipped.push_back({range.first, range.second});
    }
    FileCoverageJSON.try_emplace("skipped", std::move(skipped));
    return FileCoverageJSON;
  }
};

class FileSummary {
public:
  unsigned TotalCGNodes = 0;
  llvm::DenseSet<const Decl *> FunctionsInSystemHeader;
  llvm::DenseSet<const Decl *> FunctionsInUserHeader;
  llvm::DenseSet<const Decl *> FunctionsInMainFile;
  llvm::DenseSet<const FunctionDecl *> VirtualFunctions;
  llvm::DenseSet<QualType> TypesMayUsedByFP; // Function types maybe
  // used by function pointer call.
  unsigned int TotalIndirectCallByVF = 0;
  unsigned int TotalIndirectCallByFP = 0;

  std::map<FileID, FileCoverageSummary> FileCoverageSummaries;
  unsigned UserTotalLines = 0;
  unsigned UserSkippedLines = 0;
  unsigned MainTotalLines = 0;
  unsigned MainSkippedLines = 0;

  void exportToJSON(const std::string &OutputPath) {
    std::error_code EC;
    llvm::raw_fd_ostream OutStream(OutputPath, EC);
    if (EC) {
      llvm::errs() << "Can not open file: " << EC.message() << "\n";
      return;
    }

    llvm::json::Object FileSummaryJSON;
    FileSummaryJSON.try_emplace(
        "Call Graph",
        llvm::json::Object({{"total", TotalCGNodes},
                            {"system", FunctionsInSystemHeader.size()},
                            {"user", FunctionsInUserHeader.size()},
                            {"main", FunctionsInMainFile.size()}}));
    FileSummaryJSON.try_emplace(
        "Indirect Call", llvm::json::Object({{"VF", VirtualFunctions.size()},
                                             {"VFIC", TotalIndirectCallByVF},
                                             {"FPTY", TypesMayUsedByFP.size()},
                                             {"FPIC", TotalIndirectCallByFP}}));

    llvm::errs() << "export coverage\n";
    auto UserCoverage =
        UserTotalLines == 0
            ? 100.0
            : (100.0 * (UserTotalLines - UserSkippedLines) / UserTotalLines);

    auto MainCoverage =
        MainTotalLines == 0
            ? 100.0
            : (100.0 * (MainTotalLines - MainSkippedLines) / MainTotalLines);

    llvm::json::Array Files;
    for (auto item : FileCoverageSummaries) {
      // skip system and unknown files.
      if (item.second.kind == SYSTEM || item.second.kind == UNKNOWN) {
        continue;
      }
      Files.push_back(std::move(item.second.exportToJSON()));
    }
    auto CoverageObject = llvm::json::Object({
        {"user", llvm::json::Object({{"total", UserTotalLines},
                                     {"skipped", UserSkippedLines},
                                     {"coverage", UserCoverage}})},
        {"main", llvm::json::Object({{"total", MainTotalLines},
                                     {"skipped", MainSkippedLines},
                                     {"coverage", MainCoverage}})},
    });
    CoverageObject.try_emplace("files", std::move(Files));
    FileSummaryJSON.try_emplace("Coverage", std::move(CoverageObject));

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