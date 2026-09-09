/* Offline exporter only. Reuse the unchanged exact solver and move generator.
 * Never link this program into the GUI or replace an accepted search DLL. */
#define MAKHOS_NO_MAIN
#include "makhos_native.c"

static FILE *output_file;
static ExactContext export_context;
static int export_clock;
static uint64_t exported_boards;

static bool export_board(const int *squares, int pieces) {
    for (unsigned types = 0; types < (1u << (2 * pieces)); ++types) {
        Position p = {0};
        bool valid = true;
        for (int i = 0; i < pieces; ++i) {
            unsigned type = (types >> (2 * i)) & 3u;
            uint8_t owner = (type & 1u) ? BLACK : RED;
            bool king = (type & 2u) != 0;
            if (!king && !valid_man_square(owner, squares[i])) valid = false;
            if (owner == BLACK) p.black |= bit_at(squares[i]);
            else p.red |= bit_at(squares[i]);
            if (king) p.kings |= bit_at(squares[i]);
        }
        for (p.turn = RED; p.turn <= BLACK; ++p.turn) {
            for (int clock = 0; clock <= export_clock; ++clock) {
                uint16_t encoded = UINT16_MAX; /* invalid promotion-row man */
                if (valid) {
                    p.reversible_plies = (uint8_t)clock;
                    ExactValue value;
                    if (!exact_solve(&export_context, p, 0, &value)) return false;
                    if (value.distance >= 16384) return false;
                    encoded = value.outcome == OUTCOME_DRAW ? 0 :
                        (uint16_t)((value.outcome == OUTCOME_WIN ? 0x8000 : 0x4000)
                                   | value.distance);
                }
                uint8_t bytes[2] = {(uint8_t)encoded, (uint8_t)(encoded >> 8)};
                if (fwrite(bytes, 1, 2, output_file) != 2) return false;
            }
            ++exported_boards;
        }
    }
    return true;
}

/* Colexicographic order: rank = sum(C(square[i], i + 1)). */
static bool export_combinations(int *squares, int left, int limit, int pieces) {
    if (!left) return export_board(squares, pieces);
    for (int square = left - 1; square < limit; ++square) {
        squares[left - 1] = square;
        if (!export_combinations(squares, left - 1, square, pieces)) return false;
    }
    return true;
}

int main(int argc, char **argv) {
    int hash_power;
    if (argc != 4 || !parse_bounded_int(argv[2], 1, 200, &export_clock)
            || !parse_bounded_int(argv[3], 16, 28, &hash_power)) {
        fprintf(stderr, "usage: makhos_tb3_export RAW_OUTPUT NO_PROGRESS HASH_POWER\n");
        return 1;
    }
    if (!exact_context_init(&export_context, export_clock, hash_power, 3)) return 2;
    output_file = fopen(argv[1], "wb");
    if (!output_file) { exact_context_destroy(&export_context); return 2; }
    bool ok = true;
    int squares[3];
    for (int pieces = 1; ok && pieces <= 3; ++pieces) {
        ok = export_combinations(squares, pieces, 32, pieces);
    }
    if (fclose(output_file) != 0) ok = false;
    fprintf(stderr, "boards=%" PRIu64 " solved_states=%zu complete=%d\n",
            exported_boards, export_context.count, (int)ok);
    exact_context_destroy(&export_context);
    return ok ? 0 : 3;
}
