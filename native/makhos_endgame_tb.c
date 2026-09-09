#include "makhos_endgame_tb.h"
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>

#define BOARD_COUNT 651008u
#define VECTOR_START (BOARD_COUNT * 4u)
struct MakhosTBSet {
    atomic_uint references;
    uint32_t clock, vectors;
    uint8_t *image;
};
_Static_assert(sizeof(MakhosEndgamePosition)==20, "position ABI");
_Static_assert(sizeof(MakhosTBProbe)==24, "probe ABI");
static uint32_t u32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1]<<8) |
        ((uint32_t)p[2]<<16) | ((uint32_t)p[3]<<24);
}
static uint32_t choose(uint32_t n, uint32_t k) {
    if (n<k) return 0;
    if (k==1) return n;
    if (k==2) return n*(n-1)/2;
    return n*(n-1)*(n-2)/6;
}
uint32_t makhos_endgame_api_version(void) { return MAKHOS_ENDGAME_API_V1; }
int32_t makhos_tb3_create(const uint8_t *image, uint64_t size,
        uint32_t clock, uint32_t vectors, MakhosTBSet **output) {
    if (!output) return MK_EG_INVALID;
    *output=NULL;
    if (!image || clock<1 || clock>200 || vectors<1 || vectors>BOARD_COUNT)
        return MK_EG_INVALID;
    uint64_t expected=VECTOR_START+(uint64_t)vectors*(clock+1)*2;
    if (size!=expected || size>64u*1024u*1024u) return MK_EG_INVALID;
    MakhosTBSet *set=calloc(1,sizeof(*set));
    if (!set) return MK_EG_NO_MEMORY;
    set->image=malloc((size_t)size);
    if (!set->image) { free(set); return MK_EG_NO_MEMORY; }
    memcpy(set->image,image,(size_t)size);
    for (uint32_t i=0;i<BOARD_COUNT;i++) {
        if (u32(set->image+i*4)>=vectors) {
            free(set->image); free(set); return MK_EG_CORRUPT;
        }
    }
    /* 0xffff is the artifact's unsupported-board sentinel. Decode at probe. */
    set->clock=clock; set->vectors=vectors;
    atomic_init(&set->references,1);
    *output=set;
    return MK_EG_OK;
}
void makhos_tb_set_retain(MakhosTBSet *set) {
    if (set) atomic_fetch_add_explicit(&set->references,1,memory_order_relaxed);
}
void makhos_tb_set_release(MakhosTBSet *set) {
    if (set && atomic_fetch_sub_explicit(&set->references,1,memory_order_acq_rel)==1) {
        free(set->image); free(set);
    }
}
int32_t makhos_tb_set_probe(const MakhosTBSet *set,
        const MakhosEndgamePosition *p, MakhosTBProbe *out) {
    if (!set || !p || !out || out->struct_size!=sizeof(*out) ||
        out->version!=MAKHOS_ENDGAME_API_V1) return MK_EG_INVALID;
    uint32_t occupied=p->red|p->black;
    if ((p->red&p->black) || (p->kings&~occupied) ||
        (p->turn!=1 && p->turn!=2) || p->reversible_plies>set->clock)
        return MK_EG_INVALID;
    uint32_t n=0, rank=0, types=0;
    for (uint32_t square=0;square<32;square++) {
        uint32_t bit=UINT32_C(1)<<square;
        if (!(occupied&bit)) continue;
        if (++n>3) return MK_EG_MISS;
        uint32_t type=((p->black&bit)?1u:0u)+((p->kings&bit)?2u:0u);
        types|=type<<(2*(n-1));
        rank+=choose(square,n);
    }
    if (!n) return MK_EG_MISS;
    const uint32_t offsets[4]={0,0,256,16128};
    uint32_t index=offsets[n]+(rank*(1u<<(2*n))+types)*2+p->turn-1;
    uint32_t vector=u32(set->image+index*4);
    uint64_t offset=VECTOR_START+((uint64_t)vector*(set->clock+1)+p->reversible_plies)*2;
    uint32_t value=set->image[offset]|((uint32_t)set->image[offset+1]<<8);
    uint32_t tag=value>>14;
    if (value && tag!=1 && tag!=2) return MK_EG_CORRUPT;
    out->outcome=value?(tag==1?-1:1):0;
    out->distance=value?(int32_t)(value&0x3fff):-1;
    out->material_count=n; out->reserved=0;
    return MK_EG_OK;
}
