#include <cstdio>

#ifdef A
int a = 10;
#elif B
int b = 10;
#else
void foo();
#endif

class A {
    
    virtual void foo() {}
};