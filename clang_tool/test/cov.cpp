#include "cov.h"

int main() {
#ifndef A
foo();
#else
a = 12;
#endif
  return 0;
}