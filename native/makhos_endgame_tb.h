#ifndef MAKHOS_ENDGAME_TB_H
#define MAKHOS_ENDGAME_TB_H
#include <stdint.h>
#ifdef _WIN32
#define MK_TB_API __declspec(dllexport)
#else
#define MK_TB_API __attribute__((visibility("default")))
#endif
#define MAKHOS_ENDGAME_API_V1 1u
typedef struct MakhosTBSet MakhosTBSet;
enum { MK_EG_OK=0, MK_EG_MISS=1, MK_EG_CANCELLED=2, MK_EG_INVALID=3,
       MK_EG_CORRUPT=4, MK_EG_BUFFER_TOO_SMALL=5, MK_EG_NO_MEMORY=6 };
typedef struct { uint32_t red, black, kings, turn, reversible_plies; } MakhosEndgamePosition;
typedef struct {
    uint32_t struct_size, version;
    int32_t outcome, distance;
    uint32_t material_count, reserved;
} MakhosTBProbe;
MK_TB_API uint32_t makhos_endgame_api_version(void);
/* Copies a verified decompressed image. No borrowed pointers survive create.
 * The caller verifies artifact provenance; native validates layout/references.
 * The returned set is immutable. Caller owns one reference on success.
 */
MK_TB_API int32_t makhos_tb3_create(const uint8_t *image, uint64_t size,
    uint32_t clock, uint32_t vectors, MakhosTBSet **output);
/* Retain requires an already-owned live reference. Each worker owns a reference;
 * never race release of the last reference with retain or probe. */
MK_TB_API void makhos_tb_set_retain(MakhosTBSet *set);
MK_TB_API void makhos_tb_set_release(MakhosTBSet *set);
/* Output is valid only on OK. Raw WDL is history-free, not a search proof. */
MK_TB_API int32_t makhos_tb_set_probe(const MakhosTBSet *set,
    const MakhosEndgamePosition *position, MakhosTBProbe *output);
#endif
