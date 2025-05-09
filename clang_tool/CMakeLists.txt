cmake_minimum_required(VERSION 3.10)
project(StatisticsCollector)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED True) 

# Align LLVM version with CSA.
set(MY_LLVM_VERSION 19)
find_package(LLVM REQUIRED CONFIG HINTS ${LLVM_DIR} ${LLVM_DIR}/lib/cmake/llvm)
message(STATUS "Found LLVM: ${LLVM_INCLUDE_DIRS}")

find_package(Clang REQUIRED CONFIG HINTS ${LLVM_DIR} ${LLVM_DIR}/lib/cmake/clang)
message(STATUS "Found Clang: ${CLANG_INCLUDE_DIRS}")

# Set the LLVM and Clang header and library paths.
include_directories(SYSTEM "${LLVM_INCLUDE_DIRS};${CLANG_INCLUDE_DIRS}")

add_definitions(${LLVM_DEFINITIONS})
# LLVM default option disable RTTI, BasicInfoCollector should alse disable RTTI.
add_compile_options(-fno-rtti)

add_executable(collectStatistics CollectStatistics.cpp DiffLineManager.cpp BasicInfoCollectASTVisitor.cpp PreprocessCoverageAnalyzer.cpp)

# Ensure the LLVM and Clang include directories are added
target_include_directories(collectStatistics PRIVATE ${LLVM_INCLUDE_DIRS} ${CLANG_INCLUDE_DIRS})

target_link_libraries(collectStatistics PRIVATE
  LLVMSupport
  LLVMOption
  clangFrontend
  clangSerialization
  clangTooling
  clangBasic
  clangASTMatchers
  clangAST
  clangAnalysis
  clangIndex
  clangDriver
  clangParse
  clangSema
  clangEdit
  clangLex
)