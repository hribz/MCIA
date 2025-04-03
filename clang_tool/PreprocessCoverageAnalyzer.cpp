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

// void PreprocessCoverageAnalyzer::If(clang::SourceLocation Loc,
//                                     clang::SourceRange ConditionRange,
//                                     ConditionValueKind ConditionVal) {
//   printDebugInfo("#if", Loc, ConditionVal == CVK_True ? "(True)" :
//   "(False)"); bool isActive = (ConditionVal !=
//   clang::PPCallbacks::CVK_False); ConditionStack.push(isActive);
//   MarkLineActive(Loc); // 记录条件指令本身的行
// }

// void PreprocessCoverageAnalyzer::Elif(clang::SourceLocation Loc,
//                                       clang::SourceRange ConditionRange,
//                                       ConditionValueKind ConditionVal,
//                                       clang::SourceLocation IfLoc) {
//   printDebugInfo("#elif", Loc, ConditionVal == CVK_True ? "(True)" :
//   "(False)"); if (!ConditionStack.empty()) {
//     bool wasActive = ConditionStack.top();
//     bool isActive = (ConditionVal != clang::PPCallbacks::CVK_False);
//     ConditionStack.top() = (wasActive ? false : isActive);
//     MarkLineActive(Loc);
//   }
// }

// void PreprocessCoverageAnalyzer::Else(clang::SourceLocation Loc,
//                                       clang::SourceLocation IfLoc) {
//   printDebugInfo("#else", Loc);
//   if (!ConditionStack.empty()) {
//     ConditionStack.top() = !ConditionStack.top();
//     MarkLineActive(Loc);
//   }
// }

// void PreprocessCoverageAnalyzer::Endif(clang::SourceLocation Loc,
//                                        clang::SourceLocation IfLoc) {
//   printDebugInfo("#endif", Loc);
//   if (!ConditionStack.empty()) {
//     ConditionStack.pop();
//     MarkLineActive(Loc);
//   }
// }

// void PreprocessCoverageAnalyzer::MacroDefined(const clang::Token
// &MacroNameTok,
//                                               const clang::MacroDirective
//                                               *MD) {
//   printDebugInfo(
//       "#define", MacroNameTok.getLocation(),
//       (Twine(" ") +
//       MacroNameTok.getIdentifierInfo()->getName()).str().c_str());
//   MarkLineActive(MacroNameTok.getLocation());
// }

// void PreprocessCoverageAnalyzer::MacroUndefined(
//     const clang::Token &MacroNameTok, const clang::MacroDefinition &MD,
//     const clang::MacroDirective *Undef) {
//   printDebugInfo(
//       "#undef", MacroNameTok.getLocation(),
//       (Twine(" ") +
//       MacroNameTok.getIdentifierInfo()->getName()).str().c_str());
//   MarkLineActive(MacroNameTok.getLocation());
// }

// void PreprocessCoverageAnalyzer::InclusionDirective(
//     SourceLocation HashLoc, const Token &IncludeTok, StringRef FileName,
//     bool IsAngled, CharSourceRange FilenameRange, OptionalFileEntryRef File,
//     StringRef SearchPath, StringRef RelativePath, const Module
//     *SuggestedModule, bool ModuleImported, SrcMgr::CharacteristicKind
//     FileType) {
//   printDebugInfo("#include", HashLoc,
//                  (Twine(" \"") + FileName + "\"").str().c_str());
//   MarkLineActive(HashLoc);
// }

// void PreprocessCoverageAnalyzer::PragmaDirective(
//     clang::SourceLocation Loc, clang::PragmaIntroducerKind Introducer) {
//   MarkLineActive(Loc);
// }

void PreprocessCoverageAnalyzer::EndOfMainFile() {
  for (auto FID : Files) {
    auto Loc = SM.getLocForEndOfFile(FID);
    auto kind = getFileKind(SM, Loc);
    FileSummaries[kind].TotalLines += SM.getSpellingLineNumber(Loc);
  }
}