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
#include <fstream>
#include <iostream>
#include <llvm/ADT/DenseSet.h>
#include <llvm/ADT/StringRef.h>
#include <llvm/Support/Casting.h>
#include <llvm/Support/Error.h>
#include <llvm/Support/JSON.h>
#include <llvm/Support/Timer.h>
#include <llvm/Support/raw_ostream.h>
#include <memory>
#include <ostream>
#include <string>

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

using namespace clang;
using namespace clang::tooling;

void DisplayTime(llvm::TimeRecord &Time) {
  llvm::errs() << " : " << llvm::format("%1.1f", Time.getWallTime() * 1000)
               << " ms\n";
}

class IncInfoCollectConsumer : public clang::ASTConsumer {
public:
  explicit IncInfoCollectConsumer(CompilerInstance &CI, std::string &diffPath,
                                  const IncOptions &incOpt)
      : CG(), IncOpt(incOpt), DLM(CI.getASTContext().getSourceManager()),
        PP(CI.getPreprocessor()), SM(CI.getASTContext().getSourceManager()),
        BasicVisitor(&CI.getASTContext(), DLM, CG, IncOpt) {
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
      Decl *D = N->getDecl();

      const SourceLocation Loc = [&SM](Decl *D) -> SourceLocation {
        const Stmt *Body = D->getBody();
        SourceLocation SL = Body ? Body->getBeginLoc() : D->getLocation();
        return SM.getExpansionLoc(SL);
      }(D);

      if (Loc.isInvalid())
        continue;
      if (SM.isInSystemHeader(Loc)) {
        InsertCanonicalDeclToSet(FunctionsInSystemHeader, D);
      } else if (SM.isInMainFile(Loc)) {
        InsertCanonicalDeclToSet(FunctionsInMainFile, D);
      } else {
        InsertCanonicalDeclToSet(FunctionsInUserHeader, D);
      }
    }

    // Consider other factors on AST which make functions need to reanalyze.
    BasicVisitor.TraverseDecl(Context.getTranslationUnitDecl());

    toolTimer->stopTimer();
    llvm::TimeRecord toolEnd = toolTimer->getTotalTime();
    toolEnd -= toolPrepare;
    llvm::errs() << "Analysis CF ";
    DisplayTime(toolEnd);

    DumpIncSummary();
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

  void DumpIncSummary() {
    std::ostream *OS = &std::cout;
    std::shared_ptr<std::ofstream> outFile;
    if (IncOpt.DumpToFile) {
      std::string IncSummaryFile = MainFilePath.str() + ".ics";
      outFile = std::make_shared<std::ofstream>(IncSummaryFile);
      if (!outFile->is_open()) {
        llvm::errs() << "Error: Could not open file " << IncSummaryFile
                     << " for writing.\n";
        return;
      }
      OS = outFile.get();
    } else {
      *OS << "--- Inc Summary ---\n";
    }

    *OS << "cg nodes (total)" << ":" << CG.size() - 1 << "\n";
    *OS << "cg nodes (system)" << ":" << FunctionsInSystemHeader.size() << "\n";
    *OS << "cg nodes (user)" << ":" << FunctionsInUserHeader.size() << "\n";
    *OS << "cg nodes (main)" << ":" << FunctionsInMainFile.size() << "\n";
    *OS << "virtual functions" << ":"
        << BasicVisitor.VirtualFunctions.size() << "\n";
    *OS << "total vf indirect calls" << ":"
        << BasicVisitor.TotalIndirectCallByVF << "\n";
    *OS << "function pointer types" << ":"
        << BasicVisitor.TypesMayUsedByFP.size() << "\n";
    *OS << "total fp indirect calls" << ":"
        << BasicVisitor.TotalIndirectCallByFP << "\n";

    (*OS).flush();
    if (IncOpt.DumpToFile)
      outFile->close();
  }

private:
  const IncOptions &IncOpt;
  llvm::StringRef MainFilePath;
  DiffLineManager DLM;
  CallGraph CG;
  llvm::DenseSet<const Decl *> FunctionsInSystemHeader;
  llvm::DenseSet<const Decl *> FunctionsInUserHeader;
  llvm::DenseSet<const Decl *> FunctionsInMainFile;
  BasicInfoCollectASTVisitor BasicVisitor;
  std::deque<Decl *> LocalTUDecls;
  Preprocessor &PP;
  const clang::SourceManager &SM;
};

class IncInfoCollectAction : public clang::ASTFrontendAction {
public:
  IncInfoCollectAction(std::string &diffPath, std::string &fsPath,
                       const IncOptions &incOpt)
      : DiffPath(diffPath), FSPath(fsPath), IncOpt(incOpt) {}

  std::unique_ptr<clang::ASTConsumer>
  CreateASTConsumer(clang::CompilerInstance &CI,
                    llvm::StringRef file) override {
    return std::make_unique<IncInfoCollectConsumer>(CI, DiffPath, IncOpt);
  }

private:
  std::string &DiffPath;
  std::string &FSPath;
  const IncOptions &IncOpt;
};

class IncInfoCollectActionFactory : public FrontendActionFactory {
public:
  IncInfoCollectActionFactory(std::string &diffPath, std::string &fsPath,
                              const IncOptions &incOpt)
      : DiffPath(diffPath), FSPath(fsPath), IncOpt(incOpt) {}

  std::unique_ptr<FrontendAction> create() override {
    return std::make_unique<IncInfoCollectAction>(DiffPath, FSPath, IncOpt);
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
static llvm::cl::opt<bool> DumpUSR("dump-usr",
                                   llvm::cl::desc("Dump USR function name"),
                                   llvm::cl::value_desc("dump usr fname"),
                                   llvm::cl::init(false));
static llvm::cl::opt<bool>
    DumpANR("dump-anr", llvm::cl::desc("Dump affected nodes line ranges"),
            llvm::cl::value_desc("dump ANR"), llvm::cl::init(false));
static llvm::cl::opt<bool> CTU("ctu", llvm::cl::desc("Consider CTU analysis"),
                               llvm::cl::value_desc("consider CTU analysis"),
                               llvm::cl::init(false));
static llvm::cl::opt<std::string>
    RFPath("rf-file", llvm::cl::desc("Output RF to the path"),
           llvm::cl::value_desc("dump rf file"), llvm::cl::init(""));
static llvm::cl::opt<std::string> CppcheckRFPath(
    "cppcheck-rf-file", llvm::cl::desc("Output Cppcheck RF to the path"),
    llvm::cl::value_desc("dump cppcheck rf file"), llvm::cl::init(""));
static llvm::cl::opt<std::string>
    FilePath("file-path", llvm::cl::desc("File path before preprocess"),
             llvm::cl::value_desc("origin file"), llvm::cl::init(""));

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
  IncOptions IncOpt{.PrintLoc = PrintLoc,
                    .ClassLevelTypeChange = ClassLevel,
                    .FieldLevelTypeChange = FieldLevel,
                    .DumpCG = DumpCG,
                    .DumpToFile = DumpToFile,
                    .DumpUSR = DumpUSR,
                    .DumpANR = DumpANR,
                    .CTU = CTU,
                    .RFPath = RFPath,
                    .CppcheckRFPath = CppcheckRFPath,
                    .FilePath = FilePath};
  IncInfoCollectActionFactory Factory(DiffPath, FSPath, IncOpt);

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