/* Linux ASan/UBSan + allocation-free probe contract. Use sparse fixtures from
 * test_native_endgame_ranked.write_fixture; never generate solved TBs here.
 * Build instructions: docs/architecture/ENDGAME_NATIVE_C1_TB456_TH.md on branch research-archive. */
#include "../native/makhos_endgame_tb.h"
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

static uint64_t allocation_calls;
static uint64_t free_calls;
void *__real_malloc(size_t);
void *__real_calloc(size_t, size_t);
void *__real_realloc(void *, size_t);
void __real_free(void *);
void *__wrap_malloc(size_t n) { allocation_calls++; return __real_malloc(n); }
void *__wrap_calloc(size_t n, size_t m) { allocation_calls++; return __real_calloc(n,m); }
void *__wrap_realloc(void *p, size_t n) { allocation_calls++; return __real_realloc(p,n); }
void __wrap_free(void *p) { if (p) free_calls++; __real_free(p); }
static uint32_t rng=20260909;
static uint32_t random_u32(void) {
    rng^=rng<<13; rng^=rng>>17; rng^=rng<<5; return rng;
}
int main(int argc, char **argv) {
    if (argc!=4) { fputs("usage: harness tb4 tb5 tb6\n",stderr); return 2; }
    MakhosTBSet *set=NULL;
    const char *paths[3]={argv[1],argv[2],argv[3]};
    assert(makhos_tb_set_create(NULL,0,80,0,paths,3,0,&set)==MK_EG_OK);
    uint64_t before=allocation_calls;
    uint64_t ok=0, invalid=0, miss=0;
    for (uint32_t i=0;i<100000;i++) {
        MakhosEndgamePosition p={0};
        uint32_t pieces=4+random_u32()%3;
        uint32_t occupied=0;
        for (uint32_t j=0;j<pieces;j++) {
            uint32_t bit;
            do { bit=UINT32_C(1)<<(random_u32()%32); } while (occupied&bit);
            occupied|=bit;
            if (random_u32()&1) p.red|=bit; else p.black|=bit;
            if (random_u32()&1) p.kings|=bit;
        }
        p.turn=1+random_u32()%2; p.reversible_plies=random_u32()%82;
        MakhosTBProbe out={sizeof(out),1,99,99,99,99};
        int status=makhos_tb_set_probe(set,&p,&out);
        if (status==MK_EG_OK) {
            ok++; assert(out.outcome>=-1 && out.outcome<=1);
            assert(out.distance==-1 && out.material_count==pieces);
        } else {
            assert(status==MK_EG_INVALID || status==MK_EG_MISS);
            assert(out.outcome==99 && out.distance==99 && out.material_count==99 && out.reserved==99);
            if (status==MK_EG_INVALID) invalid++; else miss++;
        }
    }
    assert(allocation_calls==before);
    makhos_tb_set_release(set);
    /* Failure after an acquired mapping must release it; sanitizers own the
     * leak/UAF checks and Windows regression tests check writable reopening. */
    for (uint32_t i=0;i<100;i++) {
        const char *duplicate[2]={argv[1],argv[1]};
        set=(MakhosTBSet *)(uintptr_t)1;
        assert(makhos_tb_set_create(NULL,0,80,0,duplicate,2,0,&set)==MK_EG_INVALID);
        assert(set==NULL);
    }
    assert(allocation_calls==free_calls); /* all successful preparation allocations released */
    printf("100000 probes: ok=%llu invalid=%llu miss=%llu; probe allocations=0; allocation/free counts balanced\n",
           (unsigned long long)ok,(unsigned long long)invalid,(unsigned long long)miss);
    return 0;
}
