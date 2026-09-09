#if !defined(_WIN32)
#define _POSIX_C_SOURCE 200809L
#define _FILE_OFFSET_BITS 64
#endif
#include "makhos_endgame_tb.h"
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#if defined(_WIN32)
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#else
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

#define BOARD_COUNT 651008u
#define VECTOR_START (BOARD_COUNT * 4u)
#define COUNT_KEYS 2401u /* 7^4, material count <= 6 */
#define COMPLETION_ENTRIES (33u * COUNT_KEYS)
typedef struct {
    uint8_t counts[4]; /* BM, BK, RM, RK */
    uint64_t boards, offset;
} RankedSignature;
typedef struct {
    const uint8_t *data;
    size_t length;
#if defined(_WIN32)
    HANDLE file;
#else
    int file;
#endif
    MakhosRankedInfo info;
    RankedSignature signatures[70];
    /* signature index + 1; zero means unsupported */
    uint8_t signature_index[COUNT_KEYS];
} RankedMap;
struct MakhosTBSet {
    atomic_uint references;
    uint32_t clock, vectors;
    uint8_t *image;
    uint64_t *completions;
    RankedMap ranked[3];
};
_Static_assert(sizeof(MakhosEndgamePosition)==20, "position ABI");
_Static_assert(sizeof(MakhosTBProbe)==24, "probe ABI");
_Static_assert(sizeof(MakhosRankedInfo)==72, "ranked info ABI");
static uint32_t u32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1]<<8) |
        ((uint32_t)p[2]<<16) | ((uint32_t)p[3]<<24);
}
static uint64_t u64(const uint8_t *p) {
    return (uint64_t)u32(p) | ((uint64_t)u32(p+4)<<32);
}
static uint32_t count_key(const uint8_t c[4]) {
    return ((c[0]*7u+c[1])*7u+c[2])*7u+c[3];
}
static int allowed(uint32_t type, uint32_t square) {
    return !((type==0 && square<4) || (type==2 && square>=28));
}
static uint64_t completion(const MakhosTBSet *set, uint32_t square, const uint8_t c[4]) {
    return set->completions[square*COUNT_KEYS+count_key(c)];
}
static int prepare_completions(MakhosTBSet *set) {
    set->completions=calloc(COMPLETION_ENTRIES,sizeof(uint64_t));
    if (!set->completions) return MK_EG_NO_MEMORY;
    set->completions[32u*COUNT_KEYS]=1;
    for (int square=31;square>=0;square--) {
        for (uint8_t bm=0;bm<=6;bm++) for (uint8_t bk=0;bk<=6-bm;bk++)
        for (uint8_t rm=0;rm<=6-bm-bk;rm++) for (uint8_t rk=0;rk<=6-bm-bk-rm;rk++) {
            uint8_t c[4]={bm,bk,rm,rk};
            uint64_t value=completion(set,(uint32_t)square+1,c);
            for (uint32_t type=0;type<4;type++) if (c[type] && allowed(type,(uint32_t)square)) {
                c[type]--;
                value+=completion(set,(uint32_t)square+1,c);
                c[type]++;
            }
            set->completions[(uint32_t)square*COUNT_KEYS+count_key(c)]=value;
        }
    }
    return MK_EG_OK;
}
static int compare_counts(const void *a, const void *b) {
    const uint8_t *left=a, *right=b;
    int delta=(left[0]+left[2])-(right[0]+right[2]);
    if (delta) return delta;
    for (uint32_t i=0;i<4;i++) if (left[i]!=right[i]) return (int)left[i]-right[i];
    return 0;
}
static uint32_t canonical_counts(uint32_t pieces, uint8_t counts[70][4]) {
    uint32_t n=0;
    for (uint32_t bm=0;bm<=pieces;bm++) for (uint32_t bk=0;bk<=pieces-bm;bk++)
    for (uint32_t rm=0;rm<=pieces-bm-bk;rm++) {
        uint32_t rk=pieces-bm-bk-rm;
        if (!bm && !bk) continue;
        if (!rm && !rk) continue;
        counts[n][0]=(uint8_t)bm; counts[n][1]=(uint8_t)bk;
        counts[n][2]=(uint8_t)rm; counts[n++][3]=(uint8_t)rk;
    }
    qsort(counts,n,4,compare_counts);
    return n;
}
static void unmap_ranked(RankedMap *map) {
    if (!map->data) return;
#if defined(_WIN32)
    UnmapViewOfFile(map->data);
    CloseHandle(map->file);
#else
    munmap((void *)map->data,map->length);
    close(map->file);
#endif
    memset(map,0,sizeof(*map));
}
static int map_ranked(const char *path, RankedMap *map) {
    if (!path || !path[0]) return MK_EG_INVALID;
#if defined(_WIN32)
    int count=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,path,-1,NULL,0);
    if (count<=0) return MK_EG_INVALID;
    wchar_t *wide=malloc((size_t)count*sizeof(*wide));
    if (!wide) return MK_EG_NO_MEMORY;
    if (!MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,path,-1,wide,count)) {
        free(wide); return MK_EG_INVALID;
    }
    HANDLE file=CreateFileW(wide,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,
                            FILE_ATTRIBUTE_NORMAL,NULL);
    free(wide);
    if (file==INVALID_HANDLE_VALUE) return MK_EG_IO;
    BY_HANDLE_FILE_INFORMATION info;
    if (!GetFileInformationByHandle(file,&info) || GetFileType(file)!=FILE_TYPE_DISK) {
        CloseHandle(file); return MK_EG_IO;
    }
    uint64_t size=((uint64_t)info.nFileSizeHigh<<32)|info.nFileSizeLow;
    if (size<48 || size>SIZE_MAX) { CloseHandle(file); return MK_EG_CORRUPT; }
    HANDLE mapping=CreateFileMappingW(file,NULL,PAGE_READONLY,0,0,NULL);
    if (!mapping) { CloseHandle(file); return MK_EG_IO; }
    const uint8_t *data=MapViewOfFile(mapping,FILE_MAP_READ,0,0,0);
    CloseHandle(mapping);
    if (!data) { CloseHandle(file); return MK_EG_IO; }
    map->info.file_device=info.dwVolumeSerialNumber;
    map->info.file_id=((uint64_t)info.nFileIndexHigh<<32)|info.nFileIndexLow;
#else
    int file=open(path,O_RDONLY | O_CLOEXEC);
    if (file<0) return MK_EG_IO;
    struct stat info;
    if (fstat(file,&info)!=0 || !S_ISREG(info.st_mode)) { close(file); return MK_EG_IO; }
    if (info.st_size<48 || (uintmax_t)info.st_size>SIZE_MAX) { close(file); return MK_EG_CORRUPT; }
    uint64_t size=(uint64_t)info.st_size;
    void *mapped=mmap(NULL,(size_t)size,PROT_READ,MAP_PRIVATE,file,0);
    if (mapped==MAP_FAILED) { close(file); return MK_EG_IO; }
    const uint8_t *data=mapped;
    map->info.file_device=(uint64_t)info.st_dev;
    map->info.file_id=(uint64_t)info.st_ino;
#endif
    map->data=data; map->length=(size_t)size; map->file=file;
    map->info.file_bytes=size;
    return MK_EG_OK;
}
static int load_ranked(MakhosTBSet *set, const char *path, uint32_t verify_checksum) {
    RankedMap map={0};
    int status=map_ranked(path,&map);
    if (status) return status;
    const uint8_t *p=map.data;
    uint32_t pieces=u32(p+12), clock=u32(p+16), signatures=u32(p+20);
    if (memcmp(p,"MKTCWDL1",8) || u32(p+8)!=1 || pieces<4 || pieces>6 ||
        clock<1 || clock>126 || clock!=set->clock) goto corrupt;
    if (set->ranked[pieces-4].data) { unmap_ranked(&map); return MK_EG_INVALID; }
    uint8_t counts[70][4];
    uint32_t expected=canonical_counts(pieces,counts);
    if (signatures!=expected) goto corrupt;
    uint64_t positions=0, states=0, checksum=UINT64_C(1469598103934665603);
    size_t offset=48;
    for (uint32_t i=0;i<signatures;i++) {
        if (map.length-offset<20) goto corrupt;
        const uint8_t *header=p+offset;
        uint64_t boards=completion(set,0,counts[i]);
        /* All arithmetic uses trusted, bounded DP counts, never file counts. */
        uint64_t bytes=boards*2;
        if (memcmp(header,counts[i],4) || u64(header+4)!=boards || u64(header+12)!=bytes)
            goto corrupt;
        offset+=20;
        if (bytes>map.length-offset) goto corrupt;
        memcpy(map.signatures[i].counts,counts[i],4);
        map.signatures[i].boards=boards; map.signatures[i].offset=offset;
        map.signature_index[count_key(counts[i])]=(uint8_t)(i+1);
        if (verify_checksum) for (uint64_t j=0;j<bytes;j++) {
            checksum^=p[offset+(size_t)j]; checksum*=UINT64_C(1099511628211);
        }
        positions+=bytes; states+=bytes*(clock+1u);
        offset+=(size_t)bytes;
    }
    if (offset!=map.length || positions!=u64(p+24) || states!=u64(p+32)) goto corrupt;
    if (verify_checksum && checksum!=u64(p+40)) goto corrupt;
    map.info.struct_size=sizeof(map.info); map.info.version=MAKHOS_ENDGAME_API_V1;
    map.info.material_count=pieces; map.info.no_progress_plies=clock;
    map.info.signature_count=signatures; map.info.checksum_verified=verify_checksum;
    map.info.total_positions=positions; map.info.total_states=states;
    map.info.expected_checksum=u64(p+40);
    set->ranked[pieces-4]=map;
    return MK_EG_OK;
corrupt:
    unmap_ranked(&map); return MK_EG_CORRUPT;
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
        for (uint32_t i=0;i<3;i++) unmap_ranked(&set->ranked[i]);
        free(set->completions); free(set->image); free(set);
    }
}
int32_t makhos_tb_set_create(const uint8_t *image, uint64_t size,
        uint32_t clock, uint32_t vectors, const char *const *paths,
        uint32_t path_count, uint32_t verify_checksum, MakhosTBSet **output) {
    if (!output) return MK_EG_INVALID;
    *output=NULL;
    if (clock<1 || clock>200 || path_count>3 || (path_count && !paths) ||
        verify_checksum>1 || (!image && (size || vectors || !path_count))) return MK_EG_INVALID;
    MakhosTBSet *set=NULL;
    int status;
    if (image) {
        status=makhos_tb3_create(image,size,clock,vectors,&set);
        if (status) return status;
    } else {
        set=calloc(1,sizeof(*set));
        if (!set) return MK_EG_NO_MEMORY;
        atomic_init(&set->references,1); set->clock=clock;
    }
    if (path_count) {
        status=prepare_completions(set);
        if (status) { makhos_tb_set_release(set); return status; }
    }
    for (uint32_t i=0;i<path_count;i++) {
        status=load_ranked(set,paths[i],verify_checksum);
        if (status) { makhos_tb_set_release(set); return status; }
    }
    *output=set; return MK_EG_OK;
}
int32_t makhos_tb_set_ranked_info(const MakhosTBSet *set, uint32_t pieces, MakhosRankedInfo *out) {
    if (!set || !out || pieces<4 || pieces>6 || out->struct_size!=sizeof(*out) ||
        out->version!=MAKHOS_ENDGAME_API_V1) return MK_EG_INVALID;
    if (!set->ranked[pieces-4].data) return MK_EG_MISS;
    *out=set->ranked[pieces-4].info; return MK_EG_OK;
}
int32_t makhos_tb_set_ranked_bytes(const MakhosTBSet *set, uint32_t pieces,
        const uint8_t **data, uint64_t *size) {
    if (!set || pieces<4 || pieces>6 || !data || !size) return MK_EG_INVALID;
    const RankedMap *map=&set->ranked[pieces-4];
    if (!map->data) return MK_EG_MISS;
    *data=map->data; *size=map->length; return MK_EG_OK;
}
static int probe_tb3(const MakhosTBSet *set, const MakhosEndgamePosition *p, MakhosTBProbe *out) {
    if (!set->image) return MK_EG_MISS;
    uint32_t occupied=p->red|p->black;
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
static int probe_ranked(const MakhosTBSet *set, const MakhosEndgamePosition *p,
                        uint32_t pieces, MakhosTBProbe *out) {
    const RankedMap *map=&set->ranked[pieces-4];
    if (!map->data) return MK_EG_MISS;
    uint8_t types[32], counts[4]={0};
    for (uint32_t square=0;square<32;square++) {
        uint32_t bit=UINT32_C(1)<<square;
        if (!((p->red|p->black)&bit)) { types[square]=4; continue; }
        uint32_t type=((p->black&bit)?0u:2u)+((p->kings&bit)?1u:0u);
        if (!allowed(type,square)) return MK_EG_INVALID;
        types[square]=(uint8_t)type; counts[type]++;
    }
    uint32_t id=map->signature_index[count_key(counts)];
    if (!id) return MK_EG_MISS;
    const RankedSignature *signature=&map->signatures[id-1];
    uint64_t rank=0;
    for (uint32_t square=0;square<32;square++) {
        uint32_t actual=types[square];
        if (actual==4) continue;
        rank+=completion(set,square+1,counts);
        for (uint32_t type=0;type<actual;type++) if (counts[type] && allowed(type,square)) {
            counts[type]--; rank+=completion(set,square+1,counts); counts[type]++;
        }
        counts[actual]--;
    }
    if (rank>=signature->boards) return MK_EG_CORRUPT;
    uint8_t encoded=map->data[(size_t)(signature->offset+rank*2+p->turn-1)];
    uint32_t threshold=encoded&0x7fu;
    if (encoded && (!threshold || threshold>set->clock)) return MK_EG_CORRUPT;
    out->outcome=(!encoded || p->reversible_plies>=threshold)?0:((encoded&0x80)?1:-1);
    out->distance=-1; out->material_count=pieces; out->reserved=0;
    return MK_EG_OK;
}
int32_t makhos_tb_set_probe(const MakhosTBSet *set,
        const MakhosEndgamePosition *p, MakhosTBProbe *out) {
    if (!set || !p || !out || out->struct_size!=sizeof(*out) ||
        out->version!=MAKHOS_ENDGAME_API_V1) return MK_EG_INVALID;
    uint32_t occupied=p->red|p->black;
    if ((p->red&p->black) || (p->kings&~occupied) ||
        (p->turn!=1 && p->turn!=2) || p->reversible_plies>set->clock) return MK_EG_INVALID;
    uint32_t pieces=0;
    for (uint32_t bits=occupied;bits;bits&=bits-1) pieces++;
    if (pieces<=3) return probe_tb3(set,p,out);
    if (pieces<=6) return probe_ranked(set,p,pieces,out);
    return MK_EG_MISS;
}
