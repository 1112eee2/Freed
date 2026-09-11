#ifndef MAKHOS_FORMAT_H
#define MAKHOS_FORMAT_H

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "makhos_types.h"

static inline void index_to_coord(int square, int *row, int *col) {
    *row = square / 4;
    int offset = square % 4;
    *col = offset * 2 + ((*row % 2) == 0 ? 1 : 0);
}

static inline int coord_to_index(int row, int col) {
    if (row < 0 || row >= 8 || col < 0 || col >= 8 || ((row + col) & 1) != 1) {
        return -1;
    }
    return row * 4 + col / 2;
}

static inline bool is_promotion_square(uint8_t player, int square) {
    int row;
    int col;
    index_to_coord(square, &row, &col);
    (void)col;
    return player == RED ? row == 7 : row == 0;
}

static inline bool valid_man_square(uint8_t player, int square) {
    int row;
    int col;
    index_to_coord(square, &row, &col);
    (void)col;
    return player == BLACK ? row != 0 : row != 7;
}

static inline void print_move_notation(const Move *move) {
    char separator = move->capture_count > 0 ? 'x' : '-';
    for (uint8_t path_index = 0; path_index < move->path_len; ++path_index) {
        if (path_index > 0) {
            putchar(separator);
        }
        printf("%u", (unsigned)move->path[path_index] + 1);
    }
}

static inline bool parse_piece_group(Position *position, const char *group) {
    if (strlen(group) < 3) {
        return false;
    }
    uint8_t player;
    if (group[0] == 'B') {
        player = BLACK;
    } else if (group[0] == 'R') {
        player = RED;
    } else {
        return false;
    }
    bool king;
    if (group[1] == 'K') {
        king = true;
    } else if (group[1] == 'M') {
        king = false;
    } else {
        return false;
    }
    const char *cursor = group + 2;
    if (*cursor == '=') {
        ++cursor;
    }
    if (*cursor == '\0') {
        return true;
    }
    while (*cursor != '\0') {
        char *end = NULL;
        long number = strtol(cursor, &end, 10);
        if (end == cursor || number < 1 || number > 32) {
            return false;
        }
        int square = (int)number - 1;
        uint32_t square_bit = bit_at(square);
        if ((occupied(*position) & square_bit) != 0) {
            return false;
        }
        if (player == RED) {
            position->red |= square_bit;
        } else {
            position->black |= square_bit;
        }
        if (king) {
            position->kings |= square_bit;
        }
        if (*end == '\0') {
            break;
        }
        if (*end != ',') {
            return false;
        }
        cursor = end + 1;
    }
    return true;
}

static inline bool parse_position(const char *text, Position *position) {
    size_t length = strlen(text);
    char *copy = malloc(length + 1);
    if (copy == NULL) {
        return false;
    }
    memcpy(copy, text, length + 1);
    memset(position, 0, sizeof(*position));

    if (
        (copy[0] != 'B' && copy[0] != 'R') ||
        (copy[1] != '\0' && copy[1] != ':')
    ) {
        free(copy);
        return false;
    }
    position->turn = copy[0] == 'B' ? BLACK : RED;
    char *cursor = copy + 1;
    while (*cursor != '\0') {
        if (*cursor != ':') {
            free(copy);
            return false;
        }
        ++cursor;
        char *separator = strchr(cursor, ':');
        if (separator != NULL) {
            *separator = '\0';
        }
        if (*cursor == '\0' || !parse_piece_group(position, cursor)) {
            free(copy);
            return false;
        }
        if (separator == NULL) {
            break;
        }
        cursor = separator;
        *cursor = ':';
    }
    free(copy);

    /*
     * A man promotes as soon as it reaches its far rank, so a serialized
     * position containing an unpromoted man there is not a reachable/rankable
     * state.  The ranked tablebases exclude exactly these states.
     */
    uint32_t black_men = position->black & ~position->kings;
    uint32_t red_men = position->red & ~position->kings;
    for (int square = 0; square < 32; ++square) {
        int row;
        int col;
        index_to_coord(square, &row, &col);
        (void)col;
        uint32_t bit = bit_at(square);
        if (
            ((black_men & bit) != 0 && row == 0) ||
            ((red_men & bit) != 0 && row == 7)
        ) {
            return false;
        }
    }
    return true;
}

#endif /* MAKHOS_FORMAT_H */
