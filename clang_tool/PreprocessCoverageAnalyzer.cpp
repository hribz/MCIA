#include "PreprocessCoverageAnalyzer.h"
#include <clang/Basic/SourceLocation.h>
#include <clang/Basic/SourceManager.h>
#include <clang/Lex/PPCallbacks.h>
#include <map>

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

std::string getFileKindString(FileKind kind) {
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

void PreprocessCoverageAnalyzer::FileChanged(
    SourceLocation Loc, FileChangeReason Reason,
    SrcMgr::CharacteristicKind FileType, FileID PrevFID) {
  auto CurrentFilename = SM.getFilename(Loc).str();
  printDebugInfo(reason[Reason], Loc, CurrentFilename.c_str());
  auto FID = SM.getFileID(Loc);
  if (SM.isInSystemHeader(Loc)) {
    return;
  }
  if (Reason == PPCallbacks::FileChangeReason::EnterFile) {
    FileStack.push(FID);
    Files.insert(FID);
  } else if (Reason == PPCallbacks::FileChangeReason::ExitFile) {
    FileStack.pop();
  }
}

void PreprocessCoverageAnalyzer::SourceRangeSkipped(SourceRange Range,
                                                    SourceLocation EndifLoc) {
  printDebugInfo("#skip", Range);
  unsigned StartLine = SM.getSpellingLineNumber(Range.getBegin());
  unsigned EndLine = SM.getSpellingLineNumber(Range.getEnd());
  auto filekind = getFileKind(SM, Range);
  FileSummaries[filekind].SkippedLines += (EndLine - StartLine);
}

void PreprocessCoverageAnalyzer::EndOfMainFile() {
  for (auto FID : Files) {
    auto Loc = SM.getLocForEndOfFile(FID);
    auto kind = getFileKind(SM, Loc);
    FileSummaries[kind].TotalLines += SM.getSpellingLineNumber(Loc);
  }
}