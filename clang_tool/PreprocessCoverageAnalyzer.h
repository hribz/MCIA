#include <clang/Basic/SourceLocation.h>
#include <clang/Lex/PPCallbacks.h>
#include <clang/Lex/Preprocessor.h>
#include <fstream>
#include <iostream>
#include <llvm/ADT/StringRef.h>
#include <set>
#include <stack>
#include <string>

#include "Utils.h"

using namespace clang;

enum FileKind { SYSTEM, USER, MAIN, UNKNOWN };

struct FileSummary {
  unsigned SkippedLines = 0;
  unsigned TotalLines = 0;
};

FileKind getFileKind(SourceManager &SM, SourceLocation Loc);

FileKind getFileKind(SourceManager &SM, SourceRange Range);

std::string getFileKindString(FileKind kind);

class PreprocessCoverageAnalyzer : public clang::PPCallbacks {
  clang::SourceManager &SM;
  std::set<unsigned> &CoveredLines;
  std::map<FileKind, FileSummary> &FileSummaries;
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

    outFile << "[PP DEBUG] " << Directive << " @ line " << (CurrentFilename ? CurrentFilename->str(): "built-in")
            << ":" << Line << " | State: "
            << (CurrentConditionActive() ? "Active" : "Inactive")
            << " | Filekind: "
            << getFileKindString(getFileKind(SM, Loc)) << " " 
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

    outFile << "[PP DEBUG] " << Directive << " @ line " << (CurrentFilename ? CurrentFilename->str(): "built-in")
            << ":" << StartLine << "," << EndLine << " | State: "
            << (CurrentConditionActive() ? "Active" : "Inactive") 
            << " | Filekind: "
            << getFileKindString(getFileKind(SM, Range)) << " " 
            << Extra << "\n";
    outFile.flush();
  }

public:
  PreprocessCoverageAnalyzer(clang::SourceManager &SM,
                             std::set<unsigned> &Lines,
                             std::map<FileKind, FileSummary> &FS,
                             const IncOptions &IncOpt)
      : SM(SM), CoveredLines(Lines), FileSummaries(FS), IncOpt(IncOpt) {
    FileID MainFileID = SM.getMainFileID();
    const FileEntry *FE = SM.getFileEntryForID(MainFileID);
    MainFilePath = FE->tryGetRealPathName();

    if (IncOpt.DebugPP) {
      std::string PPDebugFile = MainFilePath.str() + ".pp";

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

  // /// Hook called whenever an \#if is seen.
  // /// \param Loc the source location of the directive.
  // /// \param ConditionRange The SourceRange of the expression being tested.
  // /// \param ConditionValue The evaluated value of the condition.
  // ///
  // // FIXME: better to pass in a list (or tree!) of Tokens.
  // void If(clang::SourceLocation Loc, clang::SourceRange ConditionRange,
  //         ConditionValueKind ConditionVal) override;

  // /// Hook called whenever an \#elif is seen.
  // /// \param Loc the source location of the directive.
  // /// \param ConditionRange The SourceRange of the expression being tested.
  // /// \param ConditionValue The evaluated value of the condition.
  // /// \param IfLoc the source location of the \#if/\#ifdef/\#ifndef
  // directive.
  // // FIXME: better to pass in a list (or tree!) of Tokens.
  // void Elif(clang::SourceLocation Loc, clang::SourceRange ConditionRange,
  //           ConditionValueKind ConditionVal,
  //           clang::SourceLocation IfLoc) override;

  // /// Hook called whenever an \#ifdef is seen.
  // /// \param Loc the source location of the directive.
  // /// \param MacroNameTok Information on the token being tested.
  // /// \param MD The MacroDefinition if the name was a macro, null otherwise.
  // void Ifdef(SourceLocation Loc, const Token &MacroNameTok,
  //            const MacroDefinition &MD) override;

  // /// Hook called whenever an \#elifdef branch is taken.
  // /// \param Loc the source location of the directive.
  // /// \param MacroNameTok Information on the token being tested.
  // /// \param MD The MacroDefinition if the name was a macro, null otherwise.
  // void Elifdef(SourceLocation Loc, const Token &MacroNameTok,
  //              const MacroDefinition &MD) override;

  // /// Hook called whenever an \#elifdef is skipped.
  // /// \param Loc the source location of the directive.
  // /// \param ConditionRange The SourceRange of the expression being tested.
  // /// \param IfLoc the source location of the \#if/\#ifdef/\#ifndef
  // directive.
  // // FIXME: better to pass in a list (or tree!) of Tokens.
  // void Elifdef(SourceLocation Loc, SourceRange ConditionRange,
  //              SourceLocation IfLoc) override;

  // /// Hook called whenever an \#ifndef is seen.
  // /// \param Loc the source location of the directive.
  // /// \param MacroNameTok Information on the token being tested.
  // /// \param MD The MacroDefiniton if the name was a macro, null otherwise.
  // void Ifndef(SourceLocation Loc, const Token &MacroNameTok,
  //             const MacroDefinition &MD) override;

  // /// Hook called whenever an \#elifndef branch is taken.
  // /// \param Loc the source location of the directive.
  // /// \param MacroNameTok Information on the token being tested.
  // /// \param MD The MacroDefinition if the name was a macro, null otherwise.
  // void Elifndef(SourceLocation Loc, const Token &MacroNameTok,
  //               const MacroDefinition &MD) override;
  // /// Hook called whenever an \#elifndef is skipped.
  // /// \param Loc the source location of the directive.
  // /// \param ConditionRange The SourceRange of the expression being tested.
  // /// \param IfLoc the source location of the \#if/\#ifdef/\#ifndef
  // directive.
  // // FIXME: better to pass in a list (or tree!) of Tokens.
  // void Elifndef(SourceLocation Loc, SourceRange ConditionRange,
  //               SourceLocation IfLoc) override;

  // /// Hook called whenever an \#else is seen.
  // /// \param Loc the source location of the directive.
  // /// \param IfLoc the source location of the \#if/\#ifdef/\#ifndef
  // directive. void Else(clang::SourceLocation Loc, clang::SourceLocation
  // IfLoc) override;

  // /// Hook called whenever an \#endif is seen.
  // /// \param Loc the source location of the directive.
  // /// \param IfLoc the source location of the \#if/\#ifdef/\#ifndef
  // directive. void Endif(clang::SourceLocation Loc, clang::SourceLocation
  // IfLoc) override;

  // //===--------------------------------------------------------------------===//
  // // 宏指令处理
  // //===--------------------------------------------------------------------===//

  // void MacroDefined(const clang::Token &MacroNameTok,
  //                   const clang::MacroDirective *MD) override;

  // void MacroUndefined(const clang::Token &MacroNameTok,
  //                     const clang::MacroDefinition &MD,
  //                     const clang::MacroDirective *Undef) override;

  // //===--------------------------------------------------------------------===//
  // // 包含指令处理
  // //===--------------------------------------------------------------------===//

  // void InclusionDirective(SourceLocation HashLoc, const Token &IncludeTok,
  //                         StringRef FileName, bool IsAngled,
  //                         CharSourceRange FilenameRange,
  //                         OptionalFileEntryRef File, StringRef SearchPath,
  //                         StringRef RelativePath, const Module
  //                         *SuggestedModule, bool ModuleImported,
  //                         SrcMgr::CharacteristicKind FileType) override;

  // void PragmaDirective(clang::SourceLocation Loc,
  //                      clang::PragmaIntroducerKind Introducer) override;

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