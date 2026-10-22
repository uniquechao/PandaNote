// This minimal executable has no static constructors or init arrays.
// Its shared libraries are initialized by the stock dynamic loader.
extern "C" void __libc_csu_init(int, char **, char **) {}
extern "C" void __libc_csu_fini() {}
