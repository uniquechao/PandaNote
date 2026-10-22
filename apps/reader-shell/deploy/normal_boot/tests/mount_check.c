/* Compile and call the exact production stream predicate; no device access. */
#define PANDANOTE_FIXTURE
#define main unused_apply_entry
#include "../apply_tool.c"
#undef main
int main(int argc,char**argv){FILE*f;if(argc!=3)return 2;f=fopen(argv[1],"r");if(!f)return 3;int r=mount_table(f,atoi(argv[2]));if(fclose(f))r=-1;printf("mountcontext_result=%d\n",r);return r?1:0;}
