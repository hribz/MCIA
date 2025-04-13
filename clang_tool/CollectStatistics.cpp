#include <clang/AST/ASTContext.h>
#include <clang/AST/ComputeDependence.h>
#include <clang/AST/Decl.h>
#include <clang/AST/DeclBase.h>
#include <clang/AST/DeclCXX.h>
#include <clang/AST/DeclTemplate.h>
#include <clang/AST/Expr.h>
#include <clang/AST/ExprCXX.h>
#include <clang/AST/Stmt.h>
#include <clang/Basic/LLVM.h>
#include <clang/Basic/SourceLocation.h>
#include <fstream>
#include <iostream>
#include <llvm/ADT/DenseSet.h>
#include <llvm/ADT/StringRef.h>
#include <llvm/Support/Casting.h>
#include <llvm/Support/Error.h>
#include <llvm/Support/JSON.h>
#include <llvm/Support/Timer.h>
#include <llvm/Support/raw_ostream.h>

#include "llvm/Support/CommandLine.h"
#include <clang/Analysis/AnalysisDeclContext.h>
#include <clang/Frontend/CompilerInstance.h>
#include <clang/Frontend/FrontendAction.h>
#include <clang/Index/USRGeneration.h>
#include <clang/Tooling/CommonOptionsParser.h>
#include <clang/Tooling/Tooling.h>
#include <llvm/ADT/PostOrderIterator.h>
#include <llvm/Support/raw_ostream.h>

#include "BasicInfoCollectASTVisitor.h"
#include "FileSummary.h"
#include "PreprocessCoverageAnalyzer.h"

using namespace clang;
using namespace clang::tooling;

void DisplayTime(llvm::TimeRecord &Time) {
  llvm::errs() << " : " << llvm::format("%1.1f", Time.getWallTime() * 1000)
               << " ms\n";
}

class BasicInfoCollectConsumer : public clang::ASTConsumer {
public:
  explicit BasicInfoCollectConsumer(CompilerInstance &CI, std::string &diffPath,
                                    FileSummary &FileSum_,
                                    const IncOptions &incOpt)
      : CG(), IncOpt(incOpt), DLM(CI.getASTContext().getSourceManager()),
        PP(CI.getPreprocessor()), SM(CI.getASTContext().getSourceManager()),
        FileSum(FileSum_),
        BasicVisitor(&CI.getASTContext(), DLM, CG, IncOpt, FileSum_) {
    std::unique_ptr<llvm::Timer> consumerTimer = std::make_unique<llvm::Timer>(
        "Consumer Timer", "Consumer Constructor Time");
    consumerTimer->startTimer();
    llvm::TimeRecord consumerStart = consumerTimer->getTotalTime();

    FileID MainFileID = SM.getMainFileID();
    const FileEntry *FE = SM.getFileEntryForID(MainFileID);
    MainFilePath = FE->tryGetRealPathName();
    DLM.Initialize(diffPath, MainFilePath.str());

    consumerTimer->stopTimer();
    llvm::TimeRecord consumerStop = consumerTimer->getTotalTime();
    consumerStop -= consumerStart;
    llvm::errs() << "Consumer Time:";
    DisplayTime(consumerStop);
  }

  bool HandleTopLevelDecl(DeclGroupRef DG) override {
    storeTopLevelDecls(DG);
    return true;
  }

  void HandleTopLevelDeclInObjCContainer(DeclGroupRef DG) override {
    storeTopLevelDecls(DG);
  }

  void storeTopLevelDecls(DeclGroupRef DG) {
    for (auto &I : DG) {
      // Skip ObjCMethodDecl, wait for the objc container to avoid
      // analyzing twice.
      if (isa<ObjCMethodDecl>(I))
        continue;
      LocalTUDecls.push_back(I);
    }
  }

  void HandleTranslationUnit(clang::ASTContext &Context) override {
    std::unique_ptr<llvm::Timer> toolTimer =
        std::make_unique<llvm::Timer>("tu timer", "TU analysis time");
    toolTimer->startTimer();
    llvm::TimeRecord toolStart = toolTimer->getTotalTime();
    // Don't run the actions if an error has occurred with parsing the file.
    DiagnosticsEngine &Diags = PP.getDiagnostics();
    if (Diags.hasErrorOccurred() || Diags.hasFatalErrorOccurred())
      return;

    // Same as CSA, we just consider initialzed local decl, ignore
    // addition declarations from pch deserialization.
    const unsigned LocalTUDeclsSize = LocalTUDecls.size();
    for (int i = 0; i < LocalTUDeclsSize; i++) {
      auto D = LocalTUDecls[i];
      CG.addToCallGraph(D);
    }
    FileSum.TotalCGNodes = CG.size() - 1;
    DumpCallGraph();

    toolTimer->stopTimer();
    llvm::errs() << "Prepare CG ";
    llvm::TimeRecord toolPrepare = toolTimer->getTotalTime();
    toolPrepare -= toolStart;
    DisplayTime(toolPrepare);
    toolTimer->startTimer();

    llvm::ReversePostOrderTraversal<clang::CallGraph *> RPOT(&CG);
    SourceManager &SM = Context.getSourceManager();
    for (CallGraphNode *N : RPOT) {
      if (N == CG.getRoot())
        continue;
      const Decl *D = N->getDecl();

      const SourceLocation Loc = [&SM](const Decl *D) -> SourceLocation {
        const Stmt *Body = D->getBody();
        SourceLocation SL = Body ? Body->getBeginLoc() : D->getLocation();
        return SM.getExpansionLoc(SL);
      }(D);

      if (Loc.isInvalid())
        continue;
      FileID FID = SM.getFileID(Loc);
      addItemToMap(FileSum.FunctionsMap, FID, D);
    }

    // Consider other factors on AST which make functions need to reanalyze.
    BasicVisitor.TraverseDecl(Context.getTranslationUnitDecl());

    toolTimer->stopTimer();
    llvm::TimeRecord toolEnd = toolTimer->getTotalTime();
    toolEnd -= toolPrepare;
    llvm::errs() << "Analysis CF ";
    DisplayTime(toolEnd);
  }

  static void getUSRName(const Decl *D, std::string &Str) {
    // Don't use this function if don't need USR representation
    // to avoid redundant string copy.
    D = D->getCanonicalDecl();
    SmallString<128> usr;
    index::generateUSRForDecl(D, usr);
    Str = std::to_string(usr.size());
    Str += ":";
    Str += usr.c_str();
  }

  void DumpCallGraph() {
    if (!IncOpt.DumpCG) {
      return;
    }
    std::ostream *OS = &std::cout;
    // `outFile`'s life time should persist until dump finished.
    // And don't create file if don't need to dump to file.
    std::shared_ptr<std::ofstream> outFile;
    if (IncOpt.DumpToFile) {
      std::string CGFile = MainFilePath.str() + ".cg";
      outFile = std::make_shared<std::ofstream>(CGFile);
      if (!outFile->is_open()) {
        llvm::errs() << "Error: Could not open file " << CGFile
                     << " for writing.\n";
        return;
      }
      OS = outFile.get();
    } else {
      *OS << "--- Call Graph ---\n";
    }

    llvm::ReversePostOrderTraversal<clang::CallGraph *> RPOT(&CG);
    for (CallGraphNode *N : RPOT) {
      if (N == CG.getRoot())
        continue;
      Decl *D = N->getDecl();
      if (IncOpt.DumpUSR) {
        std::string ret;
        getUSRName(D, ret);
        *OS << ret;
      } else {
        *OS << AnalysisDeclContext::getFunctionName(D->getCanonicalDecl());
      }
      if (IncOpt.PrintLoc) {
        auto loc = DLM.StartAndEndLineOfDecl(D);
        if (!loc)
          continue;
        auto StartLoc = loc->first;
        auto EndLoc = loc->second;
        *OS << " -> " << StartLoc << ", " << EndLoc;
      }
      *OS << "\n[\n";
      SetOfConstDecls CalleeSet;
      for (CallGraphNode *CR : N->callees()) {
        Decl *Callee = CR->getDecl();
        if (CalleeSet.contains(Callee))
          continue;
        CalleeSet.insert(Callee);
        if (IncOpt.DumpUSR) {
          std::string ret;
          getUSRName(Callee, ret);
          *OS << ret;
        } else {
          *OS << AnalysisDeclContext::getFunctionName(
              Callee->getCanonicalDecl());
        }
        if (IncOpt.PrintLoc) {
          auto loc = DLM.StartAndEndLineOfDecl(Callee);
          if (!loc)
            continue;
          auto StartLoc = loc->first;
          auto EndLoc = loc->second;
          *OS << " -> " << StartLoc << "-" << EndLoc;
        }
        *OS << "\n";
      }
      *OS << "]\n";
    }
    (*OS).flush();
    if (IncOpt.DumpToFile)
      outFile->close();
  }

private:
  const IncOptions &IncOpt;
  llvm::StringRef MainFilePath;
  DiffLineManager DLM;
  CallGraph CG;
  FileSummary &FileSum;
  BasicInfoCollectASTVisitor BasicVisitor;
  std::deque<Decl *> LocalTUDecls;
  Preprocessor &PP;
  clang::SourceManager &SM;
};

class BasicInfoCollectAction : public clang::ASTFrontendAction {
public:
  BasicInfoCollectAction(std::string &diffPath, std::string &fsPath,
                         const IncOptions &incOpt)
      : DiffPath(diffPath), FSPath(fsPath), IncOpt(incOpt) {}

  std::unique_ptr<clang::ASTConsumer>
  CreateASTConsumer(clang::CompilerInstance &CI,
                    llvm::StringRef file) override {
    DiagnosticsEngine &Diags = CI.getPreprocessor().getDiagnostics();
    FileSum.SM = &CI.getSourceManager();
    if (!Diags.hasErrorOccurred() && !Diags.hasFatalErrorOccurred()) {
      CI.getPreprocessor().addPPCallbacks(
          std::make_unique<PreprocessCoverageAnalyzer>(
              CI.getSourceManager(), CoveredLines,
              FileSum.FileCoverageSummaries, IncOpt));
    }
    return std::make_unique<BasicInfoCollectConsumer>(CI, DiffPath, FileSum,
                                                      IncOpt);
  }

  void EndSourceFileAction() override {
    SourceManager &SM = getCompilerInstance().getSourceManager();
    FileID mainFileID = SM.getMainFileID();
    unsigned totalLines =
        SM.getSpellingLineNumber(SM.getLocForEndOfFile(mainFileID));

    auto TotalSkippedLines =
        [](const std::vector<std::pair<unsigned, unsigned>> &ranges)
        -> unsigned {
      unsigned skipped = 0;
      for (auto range : ranges) {
        skipped += (range.second - range.first);
      }
      return skipped;
    };

    for (auto item : FileSum.FileCoverageSummaries) {
      auto FID = item.first;
      auto FCS = item.second;
      auto skipped = TotalSkippedLines(FCS.SkippedRanges);
      auto total = FCS.TotalLines;

      auto kind = getFileKind(SM, FID);
      if (kind == USER) {
        FileSum.UserTotalLines += total;
        FileSum.UserSkippedLines += skipped;
      } else if (kind == MAIN) {
        FileSum.MainTotalLines += total;
        FileSum.MainSkippedLines += skipped;
      }
    }

    llvm::errs() << "--------------------------\n"
                 << "User Files Coverage Summary\n"
                 << "Total Lines: " << FileSum.UserTotalLines << "\n"
                 << "Skipped Lines: " << FileSum.UserSkippedLines << "\n"
                 << "Coverage: "
                 << llvm::format("%1f%%\n", FileSum.UserTotalLines == 0
                                                ? 100.0
                                                : (100.0 *
                                                   (FileSum.UserTotalLines -
                                                    FileSum.UserSkippedLines) /
                                                   FileSum.UserTotalLines))
                 << "--------------------------\n"
                 << "Main Files Coverage Summary\n"
                 << "Total Lines: " << FileSum.MainTotalLines << "\n"
                 << "Skipped Lines: " << FileSum.MainSkippedLines << "\n"
                 << "Coverage: "
                 << llvm::format("%1f%%\n", FileSum.MainTotalLines == 0
                                                ? 100.0
                                                : (100.0 *
                                                   (FileSum.MainTotalLines -
                                                    FileSum.MainSkippedLines) /
                                                   FileSum.MainTotalLines))
                 << "--------------------------\n";

    std::string InfoSummaryFile =
        SM.getFileEntryForID(mainFileID)->tryGetRealPathName().str() + ".json";
    if (!IncOpt.Output.empty()) {
      InfoSummaryFile = IncOpt.Output;
    }
    FileSum.exportToJSON(InfoSummaryFile);
  }

private:
  std::string &DiffPath;
  std::string &FSPath;
  const IncOptions &IncOpt;
  std::set<unsigned> CoveredLines;
  FileSummary FileSum;
};

class BasicInfoCollectActionFactory : public FrontendActionFactory {
public:
  BasicInfoCollectActionFactory(std::string &diffPath, std::string &fsPath,
                                const IncOptions &incOpt)
      : DiffPath(diffPath), FSPath(fsPath), IncOpt(incOpt) {}

  std::unique_ptr<FrontendAction> create() override {
    return std::make_unique<BasicInfoCollectAction>(DiffPath, FSPath, IncOpt);
  }

private:
  std::string &DiffPath;
  std::string &FSPath;
  const IncOptions &IncOpt;
};

static llvm::cl::OptionCategory ToolCategory("Collect Inc Info Options");
static llvm::cl::opt<std::string>
    DiffPath("diff", llvm::cl::desc("Specify diff info files"),
             llvm::cl::value_desc("diff info files"), llvm::cl::init(""));
static llvm::cl::opt<std::string>
    FSPath("fs-file",
           llvm::cl::desc("Function summary files, use under inline mode"),
           llvm::cl::value_desc("function summary files"), llvm::cl::init(""));
static llvm::cl::opt<bool> PrintLoc(
    "loc", llvm::cl::desc("Print location information in FunctionName or not"),
    llvm::cl::value_desc("AnonymousTagLocations"), llvm::cl::init(false));
static llvm::cl::opt<bool>
    ClassLevel("class", llvm::cl::desc("Propogate type change by class level"),
               llvm::cl::value_desc("class level change"),
               llvm::cl::init(true));
static llvm::cl::opt<bool>
    FieldLevel("field", llvm::cl::desc("Propogate type change by field level"),
               llvm::cl::value_desc("field level change"),
               llvm::cl::init(false));
static llvm::cl::opt<bool> DumpCG("dump-cg", llvm::cl::desc("Dump CG or not"),
                                  llvm::cl::value_desc("dump cg"),
                                  llvm::cl::init(false));
static llvm::cl::opt<bool>
    DumpToFile("dump-file", llvm::cl::desc("Dump CG and CF to file"),
               llvm::cl::value_desc("dump to file or stream"),
               llvm::cl::init(true));
static llvm::cl::opt<bool>
    DebugPP("debug-pp", llvm::cl::desc("Enable preprocessing debug output"),
            llvm::cl::init(false));
static llvm::cl::opt<std::string> Output("o",
                                         llvm::cl::desc("Specify output file"),
                                         llvm::cl::value_desc("output file"),
                                         llvm::cl::init(""));

int main(int argc, const char **argv) {
  std::unique_ptr<llvm::Timer> toolTimer =
      std::make_unique<llvm::Timer>("tool timer", "tool analysis time");
  toolTimer->startTimer();
  llvm::TimeRecord toolStart = toolTimer->getTotalTime();

  auto ExpectedParser = CommonOptionsParser::create(argc, argv, ToolCategory);
  if (!ExpectedParser) {
    // Fail gracefully for unsupported options.
    llvm::errs() << ExpectedParser.takeError();
    return 1;
  }
  CommonOptionsParser &OptionsParser = ExpectedParser.get();

  ClangTool Tool(OptionsParser.getCompilations(),
                 OptionsParser.getSourcePathList());

  const IncOptions IncOpt{
      .PrintLoc = PrintLoc,
      .ClassLevelTypeChange = ClassLevel,
      .FieldLevelTypeChange = FieldLevel,
      .DumpCG = DumpCG,
      .DumpToFile = DumpToFile,
      .DebugPP = DebugPP,
      .Output = Output,
  };
  BasicInfoCollectActionFactory Factory(DiffPath, FSPath, IncOpt);

  toolTimer->stopTimer();
  llvm::TimeRecord toolPrepare = toolTimer->getTotalTime();
  toolPrepare -= toolStart;
  llvm::errs() << "Tool Prepare ";
  DisplayTime(toolPrepare);
  toolTimer->startTimer();

  auto ret = Tool.run(&Factory);

  toolTimer->stopTimer();
  llvm::TimeRecord toolStop = toolTimer->getTotalTime();
  toolStop -= toolStart;
  llvm::errs() << "Tool Stop ";
  DisplayTime(toolStop);

  return ret;
}