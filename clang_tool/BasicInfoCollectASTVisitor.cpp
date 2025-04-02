#include <clang/AST/ASTContext.h>
#include <clang/AST/Decl.h>
#include <clang/AST/DeclCXX.h>
#include <clang/AST/Expr.h>
#include <clang/AST/Type.h>
#include <llvm/Support/Casting.h>
#include <llvm/Support/raw_ostream.h>

#include "BasicInfoCollectASTVisitor.h"

int CountCanonicalDeclInSet(llvm::DenseSet<const Decl *> &set,
  const Decl *D) {
  return set.count(D->getCanonicalDecl());
}

void InsertCanonicalDeclToSet(llvm::DenseSet<const Decl *> &set,
  const Decl *D) {
  set.insert(D->getCanonicalDecl());
}

bool BasicInfoCollectASTVisitor::TraverseDecl(Decl *D) {
  if (!D) {
    // D maybe nullptr when VisitTemplateTemplateParmDecl.
    return true;
  }

  bool isFunctionDecl = isa<FunctionDecl>(D);
  if (isFunctionDecl) {
    if (!CG.getNode(D)) {
      // Don't care functions not exist in CallGraph.
      return true;
    }
    auto FD = dyn_cast<FunctionDecl>(D);
    inFunctionOrMethodStack.push_back(
        D->getCanonicalDecl()); // enter function/method
  }
  bool Result =
      clang::RecursiveASTVisitor<BasicInfoCollectASTVisitor>::TraverseDecl(D);
  if (isFunctionDecl) {
    inFunctionOrMethodStack.pop_back(); // exit function/method
  }
  return Result;
}

bool BasicInfoCollectASTVisitor::VisitFunctionDecl(FunctionDecl *FD) {
  if (auto MD = llvm::dyn_cast<CXXMethodDecl>(FD)) {
    if (MD->isVirtual()) {
      VirtualFunctions.insert(MD);
    }
  }
  return true;
}

bool maybeIndirectCall(ASTContext *Context, DeclRefExpr *DR) {
  auto parents = Context->getParents(*DR);

  while (!parents.empty()) {
    if (auto CE = parents[0].get<CallExpr>()) {
      if (CE->getCalleeDecl() == DR->getFoundDecl()) {
        return false;
      }
      return true;
    }

    if (parents[0].get<clang::ImplicitCastExpr>()) {
      parents = Context->getParents(parents[0]);
      continue;
    }
    break;
  }

  return true;
}

QualType getCanonicalFunctionType(clang::QualType type) {
  if (auto *ptrType = type->getAs<clang::PointerType>()) {
    return ptrType->getPointeeType().getCanonicalType();
  }
  return type.getCanonicalType();
}

bool BasicInfoCollectASTVisitor::VisitDeclRefExpr(DeclRefExpr *DR) {
  auto ND = DR->getFoundDecl();

  // TODO: May need a pre-pass to collect MayUsedAsFP before BasicInfoCollectASTVisitor.
  if (isa<FunctionDecl>(ND)) {
    // If this dereference is not a direct function call.
    if (maybeIndirectCall(Context, DR)) {
      auto FD = dyn_cast<FunctionDecl>(ND);
      TypesMayUsedByFP.insert(FD->getType().getCanonicalType());
    }
  }

  return true;
}

bool BasicInfoCollectASTVisitor::VisitCallExpr(CallExpr *CE) {
  Expr *callee = CE->getCallee()->IgnoreImpCasts();
  // Identify indirect call: function pointer.
  if (callee->getType()->isFunctionPointerType()) {
    TotalIndirectCallByFP++;
  } 
  // Identify indirect call: virtual function.
  else if (clang::MemberExpr *memberExpr =
                 llvm::dyn_cast<clang::MemberExpr>(callee)) {
    clang::ValueDecl *decl = memberExpr->getMemberDecl();
    if (clang::CXXMethodDecl *methodDecl =
            llvm::dyn_cast<clang::CXXMethodDecl>(decl)) {
      if (methodDecl->isVirtual()) {
        TotalIndirectCallByVF++;
      }
    }
  }
  return true;
}