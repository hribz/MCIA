#include "cov.h"

int main() {
  auto ptr = foo;
#ifndef A
  foo();
#else
  a = 12;
#endif
  return 0;
}