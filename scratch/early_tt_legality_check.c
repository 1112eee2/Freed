#define MAKHOS_NO_MAIN
#define MAKHOS_EARLY_TT_CUTOFF 1
#include "../native/makhos_native.c"

static uint64_t check_rng = UINT64_C(0x9e3779b97f4a7c15);

static uint32_t check_random_u32(void) {
    check_rng ^= check_rng >> 12;
    check_rng ^= check_rng << 25;
    check_rng ^= check_rng >> 27;
    return (uint32_t)(check_rng * UINT64_C(0x2545f4914f6cdd1d));
}

static Position check_random_position(void) {
    Position position;
    memset(&position, 0, sizeof(position));
    int pieces = (int)(check_random_u32() % 17);
    for (int index = 0; index < pieces; ++index) {
        uint32_t available = ~occupied(position);
        if (available == 0) break;
        int square = (int)(check_random_u32() % 32);
        while ((available & bit_at(square)) == 0) {
            square = (square + 1) & 31;
        }
        if ((check_random_u32() & 1) != 0) {
            position.red |= bit_at(square);
        } else {
            position.black |= bit_at(square);
        }
        if ((check_random_u32() & 3) == 0) {
            position.kings |= bit_at(square);
        }
    }
    position.turn = (check_random_u32() & 1) != 0 ? RED : BLACK;
    position.reversible_plies = (uint8_t)(check_random_u32() % 80);
    return position;
}

int main(void) {
    MoveList *moves = malloc(sizeof(*moves));
    if (moves == NULL) return 2;

    const uint32_t cases = UINT32_C(1000000);
    for (uint32_t index = 0; index < cases; ++index) {
        Position position = check_random_position();
        generate_moves(position, moves);
        bool expected = moves->count != 0;
        bool actual = native_has_legal_move(position);
        if (actual != expected) {
            fprintf(
                stderr,
                "mismatch at case %" PRIu32
                ": red=%08" PRIx32 " black=%08" PRIx32
                " kings=%08" PRIx32 " turn=%u moves=%" PRIu32 "\n",
                index,
                position.red,
                position.black,
                position.kings,
                position.turn,
                moves->count
            );
            free(moves);
            return 1;
        }
    }

    free(moves);
    printf("early TT legal-move check passed: %" PRIu32 " positions\n", cases);
    return 0;
}
