#include <clang/Basic/SourceLocation.h>
#include <clang/Lex/PPCallbacks.h>
#include <llvm/Support/raw_ostream.h>
#include <map>

#include "FileSummary.h"
#include "PreprocessCoverageAnalyzer.h"

FileKind getFileKind(SourceManager &SM, SourceLocation Loc) {
  auto FID = SM.getFileID(Loc);
  if (Loc.isInvalid()) {
    return FileKind::UNKNOWN;
  }
  if (SM.isInSystemHeader(Loc)) {
    return FileKind::SYSTEM;
  } else if (SM.isInMainFile(Loc)) {
    if (FID == SM.getMainFileID()) {
      return FileKind::MAIN;
    } else {
      // built-in code.
      return FileKind::UNKNOWN;
    }
  } else {
    return FileKind::USER;
  }
}

FileKind getFileKind(SourceManager &SM, SourceRange Range) {
  return getFileKind(SM, Range.getBegin());
}

FileKind getFileKind(SourceManager &SM, FileID FID) {
  return getFileKind(SM, SM.getLocForStartOfFile(FID));
}

void PreprocessCoverageAnalyzer::FileChanged(
    SourceLocation Loc, FileChangeReason Reason,
    SrcMgr::CharacteristicKind FileType, FileID PrevFID) {
  auto CurrentFilename = SM.getFilename(Loc).str();
  printDebugInfo(reason[Reason], Loc, CurrentFilename.c_str());
  auto FID = SM.getFileID(Loc);
  // if (SM.isInSystemHeader(Loc)) {
  //   return;
  // }
  Files.insert(FID);
}

void AddNewItemInFCSs(
    std::map<FileID, FileCoverageSummary> &FileCoverageSummaries,
    SourceManager &SM, FileID FID) {
  if (!FileCoverageSummaries.count(FID)) {
    FileCoverageSummaries.insert(
        {FID,
         {.SkippedRanges = {}, .TotalLines = 0, .kind = getFileKind(SM, FID)}});
  }
}

void PreprocessCoverageAnalyzer::SourceRangeSkipped(SourceRange Range,
                                                    SourceLocation EndifLoc) {
  printDebugInfo("#range", Range);
  unsigned StartLine = SM.getSpellingLineNumber(Range.getBegin());
  unsigned EndLine = SM.getSpellingLineNumber(Range.getEnd());
  auto FID = SM.getFileID(Range.getBegin());
  AddNewItemInFCSs(FileCoverageSummaries, SM, FID);
  FileCoverageSummaries[FID].SkippedRanges.push_back({StartLine, EndLine});
}

void PreprocessCoverageAnalyzer::EndOfMainFile() {
  for (auto FID : Files) {
    auto Loc = SM.getLocForEndOfFile(FID);
    AddNewItemInFCSs(FileCoverageSummaries, SM, FID);
    FileCoverageSummaries[FID].TotalLines += SM.getSpellingLineNumber(Loc);
  }
}