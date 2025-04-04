#ifndef INC_INFO_COLLECT_AST_VISITOR_H
#define INC_INFO_COLLECT_AST_VISITOR_H

#include <clang/AST/ASTContext.h>
#include <clang/AST/ComputeDependence.h>
#include <clang/AST/Decl.h>
#include <clang/AST/DeclBase.h>
#include <clang/AST/DeclCXX.h>
#include <clang/AST/DeclTemplate.h>
#include <clang/AST/Expr.h>
#include <clang/AST/ExprCXX.h>
#include <clang/AST/Stmt.h>
#include <clang/AST/Type.h>
#include <clang/Analysis/CallGraph.h>
#include <clang/Basic/LLVM.h>
#include <llvm/ADT/DenseMapInfo.h>
#include <llvm/ADT/DenseSet.h>
#include <llvm/ADT/StringRef.h>
#include <llvm/Support/Error.h>
#include <llvm/Support/JSON.h>
#include <llvm/Support/raw_ostream.h>
#include <vector>

#include "clang/AST/RecursiveASTVisitor.h"
#include "clang/Analysis/AnalysisDeclContext.h"
#include "clang/Frontend/CompilerInstance.h"
#include "clang/Index/USRGeneration.h"

#include "DiffLineManager.h"
#include "FileSummary.h"
#include "Utils.h"

using namespace clang;
using SetOfConstDecls = llvm::DenseSet<const Decl *>;

int CountCanonicalDeclInSet(llvm::DenseSet<const Decl *> &set, const Decl *D);

void InsertCanonicalDeclToSet(llvm::DenseSet<const Decl *> &set, const Decl *D);

namespace llvm {
  template <> struct DenseMapInfo<clang::QualType> {
    static inline clang::QualType getEmptyKey() {
      return clang::QualType::getFromOpaquePtr(
          reinterpret_cast<void *>(~static_cast<uintptr_t>(0)));
    }
    static inline clang::QualType getTombstoneKey() {
      return clang::QualType::getFromOpaquePtr(
          reinterpret_cast<void *>(~static_cast<uintptr_t>(1)));
    }
    static unsigned getHashValue(clang::QualType Val) {
      return DenseMapInfo<void *>::getHashValue(Val.getAsOpaquePtr());
    }
    static bool isEqual(clang::QualType LHS, clang::QualType RHS) {
      return LHS == RHS; // 直接使用 QualType 的判等操作符
    }
  };
} // namespace llvm

class BasicInfoCollectASTVisitor
    : public RecursiveASTVisitor<BasicInfoCollectASTVisitor> {
public:
  explicit BasicInfoCollectASTVisitor(ASTContext *Context, DiffLineManager &dlm,
                                      CallGraph &CG, const IncOptions &incOpt, FileSummary &FileSum_)
      : Context(Context), DLM(dlm), CG(CG), IncOpt(incOpt), FileSum(FileSum_) {}

  // Def
  bool VisitFunctionDecl(FunctionDecl *FD);

  bool TraverseDecl(Decl *D);

  bool VisitDeclRefExpr(DeclRefExpr *DR);

  // Process indirect call.
  bool VisitCallExpr(CallExpr *CE);

  ASTContext *Context;
  DiffLineManager &DLM;
  CallGraph &CG;
  std::vector<const Decl *> inFunctionOrMethodStack;
  const IncOptions &IncOpt;
  FileSummary &FileSum;
};

#endif // INC_INFO_COLLECT_AST_VISITOR_H