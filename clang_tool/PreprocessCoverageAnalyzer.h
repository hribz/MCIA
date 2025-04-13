#ifndef PREPROCESS_COVERAGE_ANALYZER_H
#define PREPROCESS_COVERAGE_ANALYZER_H

#include <clang/Lex/PPCallbacks.h>
#include <clang/Lex/Preprocessor.h>
#include <fstream>
#include <iostream>
#include <llvm/ADT/StringRef.h>
#include <set>
#include <stack>
#include <string>

#include "Utils.h"
#include "FileSummary.h"

using namespace clang;

FileKind getFileKind(SourceManager &SM, SourceLocation Loc);

FileKind getFileKind(SourceManager &SM, SourceRange Range);

FileKind getFileKind(SourceManager &SM, FileID FID);

class PreprocessCoverageAnalyzer : public clang::PPCallbacks {
  clang::SourceManager &SM;
  std::set<unsigned> &CoveredLines;
  std::map<FileID, FileCoverageSummary> &FileCoverageSummaries;
  std::stack<bool> ConditionStack;
  std::stack<FileID> FileStack;
  std::set<FileID> Files;
  std::map<PPCallbacks::FileChangeReason, const char *> reason = {
      {PPCallbacks::FileChangeReason::EnterFile, "#entering"},
      {PPCallbacks::FileChangeReason::ExitFile, "#exit"},
      {PPCallbacks::FileChangeReason::RenameFile, "#rename"},
      {PPCallbacks::FileChangeReason::SystemHeaderPragma, "#system"}};

  const IncOptions &IncOpt;
  llvm::StringRef MainFilePath;
  std::ofstream outFile;

  bool CurrentConditionActive() const {
    return ConditionStack.empty() || ConditionStack.top();
  }

  void printDebugInfo(const char *Directive, clang::SourceLocation Loc,
                      const char *Extra = "") {
    if (!IncOpt.DebugPP)
      return;

    unsigned Line = SM.getSpellingLineNumber(Loc);
    auto CurrentFID = SM.getFileID(Loc);
    auto CurrentFilename = SM.getNonBuiltinFilenameForID(CurrentFID);

    outFile << "[PP DEBUG] " << Directive << " "
            << (CurrentFilename ? CurrentFilename->str() : "built-in") << ":"
            << Line << " | State: "
            << (CurrentConditionActive() ? "Active" : "Inactive")
            << " | Filekind: " << getFileKindString(getFileKind(SM, Loc)) << " "
            << Extra << "\n";
    outFile.flush();
  }

  void printDebugInfo(const char *Directive, clang::SourceRange Range,
                      const char *Extra = "") {
    if (!IncOpt.DebugPP)
      return;

    unsigned StartLine = SM.getSpellingLineNumber(Range.getBegin());
    unsigned EndLine = SM.getSpellingLineNumber(Range.getEnd());
    auto CurrentFID = SM.getFileID(Range.getBegin());
    auto CurrentFilename = SM.getNonBuiltinFilenameForID(CurrentFID);

    outFile << "[PP DEBUG] " << Directive << " "
            << (CurrentFilename ? CurrentFilename->str() : "built-in") << ":"
            << StartLine << "," << EndLine << " | State: "
            << (CurrentConditionActive() ? "Active" : "Inactive")
            << " | Filekind: " << getFileKindString(getFileKind(SM, Range))
            << " " << Extra << "\n";
    outFile.flush();
  }

public:
  PreprocessCoverageAnalyzer(clang::SourceManager &SM,
                             std::set<unsigned> &Lines,
                             std::map<FileID, FileCoverageSummary> &FCSs,
                             const IncOptions &IncOpt)
      : SM(SM), CoveredLines(Lines), FileCoverageSummaries(FCSs), IncOpt(IncOpt) {
    FileID MainFileID = SM.getMainFileID();
    const FileEntry *FE = SM.getFileEntryForID(MainFileID);
    MainFilePath = FE->tryGetRealPathName();

    if (IncOpt.DebugPP) {
      std::string PPDebugFile = MainFilePath.str() + ".pp";
      if (!IncOpt.Output.empty()) {
        PPDebugFile = IncOpt.Output + ".pp";
      }

      // Clean the file.
      std::ofstream clear_file(PPDebugFile, std::ios::trunc);
      clear_file.close();

      // Append mode.
      outFile.open(PPDebugFile, std::ios::app);
      if (!outFile.is_open()) {
        llvm::errs() << "Error: Could not open file " << PPDebugFile
                     << " for writing.\n";
      }
    }
  }

  ~PreprocessCoverageAnalyzer() {
    if (outFile.is_open()) {
      outFile.close();
    }
  }

  //===--------------------------------------------------------------------===//
  // Handle preprocess directives.
  //===--------------------------------------------------------------------===//

  /// Callback invoked whenever a source file is entered or exited.
  ///
  /// \param Loc Indicates the new location.
  /// \param PrevFID the file that was exited if \p Reason is ExitFile or the
  /// the file before the new one entered for \p Reason EnterFile.
  void FileChanged(SourceLocation Loc, FileChangeReason Reason,
                   SrcMgr::CharacteristicKind FileType,
                   FileID PrevFID = FileID()) override;

  /// Hook called when a source range is skipped.
  /// \param Range The SourceRange that was skipped. The range begins at the
  /// \#if/\#else directive and ends after the \#endif/\#else directive.
  /// \param EndifLoc The end location of the 'endif' token, which may precede
  /// the range skipped by the directive (e.g excluding comments after an
  /// 'endif').
  void SourceRangeSkipped(SourceRange Range, SourceLocation EndifLoc) override;

  void EndOfMainFile() override;

private:
  // 标记指定位置的行号（如果处于激活状态）
  void MarkLineActive(clang::SourceLocation Loc) {
    if (SM.isWrittenInMainFile(Loc) && CurrentConditionActive()) {
      unsigned line = SM.getSpellingLineNumber(Loc);
      CoveredLines.insert(line);
    }
  }
};

#endif // PREPROCESS_COVERAGE_ANALYZER_H