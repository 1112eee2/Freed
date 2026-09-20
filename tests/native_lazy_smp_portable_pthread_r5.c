/* Appended to verbatim production declarations by the r5 exporter.
 *
 * This harness deliberately separates preflight, bounded SPSC liveness, and
 * concurrent safety/coverage into three slots.  The production publication
 * functions and their seq_cst atomics are extracted without modification.
 */
#include <inttypes.h>
#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define WRITER_COUNT 8
#define READER_COUNT 4
#define CONCURRENT_ITERATIONS 100000
#define SPSC_PUBLICATIONS 256
#define TEST_KEY UINT64_C(123)
#define TEST_EPOCH UINT32_C(7)
#define TEST_DEPTH UINT32_C(42)

enum HarnessExit {
    HARNESS_PASS = 0,
    HARNESS_FAIL = 2,
    HARNESS_INCOMPLETE_COVERAGE = 3,
    HARNESS_NOT_RUN = 4
};

typedef struct {
    uint64_t attempts;
    uint64_t successful;
    uint64_t skipped;
} WriterRecord;

typedef struct {
    uint64_t attempts;
    uint64_t accepted;
    uint64_t rejected;
} ReaderRecord;

typedef struct {
    uint64_t successful;
    uint64_t acknowledgments;
} SpscWriterRecord;

typedef struct {
    uint64_t raw_accepted;
    uint64_t distinct_accepted;
    uint64_t duplicates;
} SpscReaderRecord;

typedef struct {
    uintptr_t id;
    WriterRecord *record;
} WriterArgument;

typedef struct {
    uintptr_t id;
    ReaderRecord *record;
} ReaderArgument;

static SharedMoveHintEntry preflight_slot;
static SharedMoveHintEntry workload_slot;
static SharedMoveHintEntry liveness_slot;
static atomic_bool concurrent_start;
static atomic_bool concurrent_failure;
static atomic_bool concurrent_failure_logged;
static atomic_bool reader_ready;
static atomic_uint_fast32_t spsc_ack;
static atomic_bool spsc_failure;
static SpscWriterRecord spsc_writer_record;
static SpscReaderRecord spsc_reader_record;

static void initialize_slot(SharedMoveHintEntry *entry) {
    atomic_init(&entry->sequence, UINT64_C(0));
    atomic_init(&entry->key, UINT64_C(0));
    atomic_init(&entry->data, UINT64_C(0));
    atomic_init(&entry->move_w0, UINT64_C(0));
    atomic_init(&entry->move_w1, UINT64_C(0));
    atomic_init(&entry->move_w2, UINT64_C(0));
}

static NativeCompactMove encoded_move(uint32_t writer_id, uint32_t iteration) {
    uint64_t value = ((uint64_t)writer_id << 32) | (uint64_t)iteration;
    NativeCompactMove move = {
        value,
        ~value,
        (uint32_t)value,
        ~(uint32_t)value
    };
    return move;
}

static bool validate_move(
    const NativeCompactMove *move,
    uint32_t depth,
    uint32_t writer_min,
    uint32_t writer_max,
    uint32_t iteration_min,
    uint32_t iteration_max,
    uint32_t *out_writer,
    uint32_t *out_iteration
) {
    uint32_t writer_id = (uint32_t)(move->path_low >> 32);
    uint32_t iteration = (uint32_t)move->path_low;
    if (out_writer != NULL) *out_writer = writer_id;
    if (out_iteration != NULL) *out_iteration = iteration;
    return move->captured_low == ~move->path_low &&
           move->path_high_meta == (uint32_t)move->path_low &&
           move->captured_high_meta == ~(uint32_t)move->path_low &&
           depth == TEST_DEPTH &&
           writer_id >= writer_min && writer_id <= writer_max &&
           iteration >= iteration_min && iteration <= iteration_max;
}

static int run_directed(void) {
    NativeCompactMove seed = {1, 2, 3, 4};
    NativeCompactMove readback = {0};
    uint32_t depth = UINT32_MAX;

    initialize_slot(&preflight_slot);
    if (!shared_move_hint_write(
            &preflight_slot, TEST_KEY, ((uint64_t)TEST_EPOCH << 32), &seed)) {
        fprintf(stderr, "directed: seed publication unexpectedly skipped\n");
        return HARNESS_FAIL;
    }
    atomic_store_explicit(&preflight_slot.sequence, UINT64_C(0), memory_order_seq_cst);
    if (!shared_move_hint_read(
            &preflight_slot, TEST_KEY, TEST_EPOCH, &readback, &depth) ||
        memcmp(&seed, &readback, sizeof(seed)) != 0 || depth != 0) {
        fprintf(stderr, "directed: PR23 seed counterexample was not reproduced\n");
        return HARNESS_FAIL;
    }

    initialize_slot(&preflight_slot);
    NativeCompactMove valid = encoded_move(0, 1);
    uint64_t data = ((uint64_t)TEST_EPOCH << 32) | TEST_DEPTH;
    if (!shared_move_hint_write(&preflight_slot, TEST_KEY, data, &valid)) {
        fprintf(stderr, "directed: valid publication unexpectedly skipped\n");
        return HARNESS_FAIL;
    }
    if (shared_move_hint_read(&preflight_slot, TEST_KEY + 1, TEST_EPOCH, NULL, NULL) ||
        shared_move_hint_read(&preflight_slot, TEST_KEY, TEST_EPOCH + 1, NULL, NULL)) {
        fprintf(stderr, "directed: key or epoch mismatch was accepted\n");
        return HARNESS_FAIL;
    }
    atomic_store_explicit(&preflight_slot.sequence, UINT64_C(3), memory_order_seq_cst);
    if (shared_move_hint_write(&preflight_slot, TEST_KEY, data, &valid) ||
        shared_move_hint_read(&preflight_slot, TEST_KEY, TEST_EPOCH, NULL, NULL)) {
        fprintf(stderr, "directed: paused writer was not rejected\n");
        return HARNESS_FAIL;
    }
    atomic_store_explicit(
        &preflight_slot.sequence, UINT64_MAX - UINT64_C(1), memory_order_seq_cst);
    if (shared_move_hint_write(&preflight_slot, TEST_KEY, data, &valid)) {
        fprintf(stderr, "directed: sequence exhaustion was not rejected\n");
        return HARNESS_FAIL;
    }
    printf("{\"schema\":\"thai-makhos-lazy-smp-g2-r5-process-v1\","
           "\"mode\":\"directed\",\"status\":\"PASS\","
           "\"seed_counterexample_reproduced\":true,"
           "\"key_mismatch_rejected\":true,\"epoch_mismatch_rejected\":true,"
           "\"paused_writer_rejected\":true,\"sequence_exhaustion_rejected\":true}\n");
    return HARNESS_PASS;
}

static void *spsc_writer(void *unused) {
    (void)unused;
    while (!atomic_load_explicit(&reader_ready, memory_order_acquire)) {
        if (atomic_load_explicit(&spsc_failure, memory_order_relaxed)) return NULL;
        sched_yield();
    }
    for (uint32_t publication = 1; publication <= SPSC_PUBLICATIONS; ++publication) {
        NativeCompactMove move = encoded_move(0, publication);
        uint64_t data = ((uint64_t)TEST_EPOCH << 32) | TEST_DEPTH;
        if (!shared_move_hint_write(&liveness_slot, TEST_KEY, data, &move)) {
            fprintf(stderr, "spsc: publication %u unexpectedly skipped\n", publication);
            atomic_store_explicit(&spsc_failure, true, memory_order_release);
            return NULL;
        }
        ++spsc_writer_record.successful;
        while (atomic_load_explicit(&spsc_ack, memory_order_acquire) != publication) {
            if (atomic_load_explicit(&spsc_failure, memory_order_acquire)) return NULL;
            sched_yield();
        }
        ++spsc_writer_record.acknowledgments;
    }
    return NULL;
}

static void *spsc_reader(void *unused) {
    (void)unused;
    NativeCompactMove move = {0};
    uint32_t depth = 0;
    if (shared_move_hint_read(&liveness_slot, TEST_KEY, TEST_EPOCH, &move, &depth)) {
        fprintf(stderr, "spsc: initial workload namespace did not miss\n");
        atomic_store_explicit(&spsc_failure, true, memory_order_release);
        return NULL;
    }
    atomic_store_explicit(&reader_ready, true, memory_order_release);

    uint32_t next_expected = 1;
    while (next_expected <= SPSC_PUBLICATIONS) {
        if (!shared_move_hint_read(
                &liveness_slot, TEST_KEY, TEST_EPOCH, &move, &depth)) {
            sched_yield();
            continue;
        }
        ++spsc_reader_record.raw_accepted;
        uint32_t writer_id = UINT32_MAX;
        uint32_t publication = UINT32_MAX;
        if (!validate_move(
                &move, depth, 0, 0, 1, SPSC_PUBLICATIONS,
                &writer_id, &publication)) {
            fprintf(stderr,
                    "spsc: invalid tuple next=%u writer=%u publication=%u "
                    "w0=%" PRIu64 " w1=%" PRIu64 " m0=%u m1=%u depth=%u\n",
                    next_expected, writer_id, publication,
                    move.path_low, move.captured_low,
                    move.path_high_meta, move.captured_high_meta, depth);
            atomic_store_explicit(&spsc_failure, true, memory_order_release);
            return NULL;
        }
        if (publication < next_expected) {
            ++spsc_reader_record.duplicates;
            sched_yield();
            continue;
        }
        if (publication > next_expected) {
            fprintf(stderr, "spsc: future publication observed next=%u got=%u\n",
                    next_expected, publication);
            atomic_store_explicit(&spsc_failure, true, memory_order_release);
            return NULL;
        }
        ++spsc_reader_record.distinct_accepted;
        atomic_store_explicit(&spsc_ack, publication, memory_order_release);
        ++next_expected;
    }
    return NULL;
}

static int run_spsc(void) {
    pthread_t writer;
    pthread_t reader;
    initialize_slot(&liveness_slot);
    atomic_init(&reader_ready, false);
    atomic_init(&spsc_ack, 0);
    atomic_init(&spsc_failure, false);
    memset(&spsc_writer_record, 0, sizeof(spsc_writer_record));
    memset(&spsc_reader_record, 0, sizeof(spsc_reader_record));

    if (pthread_create(&reader, NULL, spsc_reader, NULL) != 0) {
        fprintf(stderr, "spsc: reader thread creation failed before reader-ready\n");
        return HARNESS_NOT_RUN;
    }
    if (pthread_create(&writer, NULL, spsc_writer, NULL) != 0) {
        fprintf(stderr, "spsc: writer thread creation failed before reader-ready\n");
        atomic_store_explicit(&spsc_failure, true, memory_order_release);
        pthread_join(reader, NULL);
        return HARNESS_NOT_RUN;
    }
    if (pthread_join(writer, NULL) != 0 || pthread_join(reader, NULL) != 0) {
        fprintf(stderr, "spsc: thread join failed\n");
        return atomic_load_explicit(&reader_ready, memory_order_acquire)
            ? HARNESS_FAIL : HARNESS_NOT_RUN;
    }
    if (atomic_load_explicit(&spsc_failure, memory_order_acquire) ||
        spsc_writer_record.successful != SPSC_PUBLICATIONS ||
        spsc_writer_record.acknowledgments != SPSC_PUBLICATIONS ||
        spsc_reader_record.distinct_accepted != SPSC_PUBLICATIONS ||
        atomic_load_explicit(&spsc_ack, memory_order_acquire) != SPSC_PUBLICATIONS) {
        fprintf(stderr,
                "spsc: incomplete successful=%" PRIu64 " ack=%" PRIu64
                " distinct=%" PRIu64 " raw=%" PRIu64 " duplicates=%" PRIu64 "\n",
                spsc_writer_record.successful, spsc_writer_record.acknowledgments,
                spsc_reader_record.distinct_accepted, spsc_reader_record.raw_accepted,
                spsc_reader_record.duplicates);
        return HARNESS_FAIL;
    }
    return HARNESS_PASS;
}

static void *concurrent_writer(void *opaque) {
    WriterArgument *argument = (WriterArgument *)opaque;
    while (!atomic_load_explicit(&concurrent_start, memory_order_acquire)) sched_yield();
    for (uint32_t iteration = 1; iteration <= CONCURRENT_ITERATIONS; ++iteration) {
        ++argument->record->attempts;
        NativeCompactMove move = encoded_move((uint32_t)argument->id, iteration);
        uint64_t data = ((uint64_t)TEST_EPOCH << 32) | TEST_DEPTH;
        if (shared_move_hint_write(&workload_slot, TEST_KEY, data, &move))
            ++argument->record->successful;
        else
            ++argument->record->skipped;
    }
    return NULL;
}

static void *concurrent_reader(void *opaque) {
    ReaderArgument *argument = (ReaderArgument *)opaque;
    while (!atomic_load_explicit(&concurrent_start, memory_order_acquire)) sched_yield();
    for (uint32_t iteration = 1; iteration <= CONCURRENT_ITERATIONS; ++iteration) {
        NativeCompactMove move = {0};
        uint32_t depth = 0;
        ++argument->record->attempts;
        if (!shared_move_hint_read(
                &workload_slot, TEST_KEY, TEST_EPOCH, &move, &depth)) {
            ++argument->record->rejected;
            continue;
        }
        ++argument->record->accepted;
        uint32_t writer_id = UINT32_MAX;
        uint32_t publication = UINT32_MAX;
        if (!validate_move(
                &move, depth, 0, WRITER_COUNT - 1, 1, CONCURRENT_ITERATIONS,
                &writer_id, &publication)) {
            atomic_store_explicit(&concurrent_failure, true, memory_order_release);
            if (!atomic_exchange_explicit(
                    &concurrent_failure_logged, true, memory_order_acq_rel)) {
                fprintf(stderr,
                        "concurrent: invalid accepted tuple reader=%" PRIuPTR
                        " attempt=%u decoded_writer=%u decoded_iteration=%u "
                        "w0=%" PRIu64 " w1=%" PRIu64 " m0=%u m1=%u depth=%u\n",
                        argument->id, iteration, writer_id, publication,
                        move.path_low, move.captured_low,
                        move.path_high_meta, move.captured_high_meta, depth);
            }
            return NULL;
        }
    }
    return NULL;
}

static int run_concurrent(
    WriterRecord writers[WRITER_COUNT],
    ReaderRecord readers[READER_COUNT]
) {
    pthread_t writer_threads[WRITER_COUNT];
    pthread_t reader_threads[READER_COUNT];
    WriterArgument writer_arguments[WRITER_COUNT];
    ReaderArgument reader_arguments[READER_COUNT];
    size_t writers_created = 0;
    size_t readers_created = 0;

    initialize_slot(&workload_slot);
    atomic_init(&concurrent_start, false);
    atomic_init(&concurrent_failure, false);
    atomic_init(&concurrent_failure_logged, false);
    memset(writers, 0, sizeof(WriterRecord) * WRITER_COUNT);
    memset(readers, 0, sizeof(ReaderRecord) * READER_COUNT);

    NativeCompactMove initial = {0};
    uint32_t initial_depth = 0;
    if (shared_move_hint_read(
            &workload_slot, TEST_KEY, TEST_EPOCH, &initial, &initial_depth)) {
        fprintf(stderr, "concurrent: workload slot did not initially miss\n");
        return HARNESS_FAIL;
    }

    for (uintptr_t id = 0; id < WRITER_COUNT; ++id) {
        writer_arguments[id].id = id;
        writer_arguments[id].record = &writers[id];
        if (pthread_create(
                &writer_threads[id], NULL, concurrent_writer, &writer_arguments[id]) != 0) {
            fprintf(stderr, "concurrent: writer thread creation failed id=%" PRIuPTR "\n", id);
            goto creation_failed;
        }
        ++writers_created;
    }
    for (uintptr_t id = 0; id < READER_COUNT; ++id) {
        reader_arguments[id].id = id;
        reader_arguments[id].record = &readers[id];
        if (pthread_create(
                &reader_threads[id], NULL, concurrent_reader, &reader_arguments[id]) != 0) {
            fprintf(stderr, "concurrent: reader thread creation failed id=%" PRIuPTR "\n", id);
            goto creation_failed;
        }
        ++readers_created;
    }

    atomic_store_explicit(&concurrent_start, true, memory_order_release);
    for (size_t index = 0; index < writers_created; ++index)
        if (pthread_join(writer_threads[index], NULL) != 0) return HARNESS_FAIL;
    for (size_t index = 0; index < readers_created; ++index)
        if (pthread_join(reader_threads[index], NULL) != 0) return HARNESS_FAIL;

    if (atomic_load_explicit(&concurrent_failure, memory_order_acquire))
        return HARNESS_FAIL;

    bool incomplete = false;
    for (size_t index = 0; index < WRITER_COUNT; ++index) {
        if (writers[index].attempts != CONCURRENT_ITERATIONS ||
            writers[index].successful + writers[index].skipped != CONCURRENT_ITERATIONS) {
            fprintf(stderr, "concurrent: writer accounting failed id=%zu\n", index);
            return HARNESS_FAIL;
        }
        if (writers[index].successful == 0) incomplete = true;
    }
    for (size_t index = 0; index < READER_COUNT; ++index) {
        if (readers[index].attempts != CONCURRENT_ITERATIONS ||
            readers[index].accepted + readers[index].rejected != CONCURRENT_ITERATIONS) {
            fprintf(stderr, "concurrent: reader accounting failed id=%zu\n", index);
            return HARNESS_FAIL;
        }
        if (readers[index].accepted == 0) incomplete = true;
    }
    return incomplete ? HARNESS_INCOMPLETE_COVERAGE : HARNESS_PASS;

creation_failed:
    atomic_store_explicit(&concurrent_start, true, memory_order_release);
    for (size_t index = 0; index < writers_created; ++index)
        pthread_join(writer_threads[index], NULL);
    for (size_t index = 0; index < readers_created; ++index)
        pthread_join(reader_threads[index], NULL);
    return HARNESS_NOT_RUN;
}

static void print_protocol_json(
    int status,
    const WriterRecord writers[WRITER_COUNT],
    const ReaderRecord readers[READER_COUNT]
) {
    const char *name = status == HARNESS_PASS ? "PASS" :
                       status == HARNESS_FAIL ? "FAIL" :
                       status == HARNESS_INCOMPLETE_COVERAGE ? "INCOMPLETE_COVERAGE" :
                       "NOT_RUN";
    printf("{\"schema\":\"thai-makhos-lazy-smp-g2-r5-process-v1\","
           "\"mode\":\"protocol\",\"status\":\"%s\","
           "\"spsc\":{\"writer_successful\":%" PRIu64
           ",\"acknowledgments\":%" PRIu64
           ",\"reader_raw_accepted\":%" PRIu64
           ",\"reader_distinct_accepted\":%" PRIu64
           ",\"duplicate_reads\":%" PRIu64 "},\"writers\":[",
           name, spsc_writer_record.successful, spsc_writer_record.acknowledgments,
           spsc_reader_record.raw_accepted, spsc_reader_record.distinct_accepted,
           spsc_reader_record.duplicates);
    for (size_t index = 0; index < WRITER_COUNT; ++index) {
        if (index != 0) putchar(',');
        printf("{\"id\":%zu,\"attempts\":%" PRIu64
               ",\"successful\":%" PRIu64 ",\"skipped\":%" PRIu64 "}",
               index, writers[index].attempts, writers[index].successful,
               writers[index].skipped);
    }
    printf("],\"readers\":[");
    for (size_t index = 0; index < READER_COUNT; ++index) {
        if (index != 0) putchar(',');
        printf("{\"id\":%zu,\"attempts\":%" PRIu64
               ",\"accepted\":%" PRIu64 ",\"rejected\":%" PRIu64 "}",
               index, readers[index].attempts, readers[index].accepted,
               readers[index].rejected);
    }
    printf("]}\n");
}

static int run_protocol(void) {
    WriterRecord writers[WRITER_COUNT] = {{0}};
    ReaderRecord readers[READER_COUNT] = {{0}};
    int spsc = run_spsc();
    if (spsc != HARNESS_PASS) {
        print_protocol_json(spsc, writers, readers);
        return spsc;
    }
    int concurrent = run_concurrent(writers, readers);
    print_protocol_json(concurrent, writers, readers);
    return concurrent;
}

int main(int argc, char **argv) {
    _Static_assert(sizeof(SharedMoveHintEntry) == 48, "production entry ABI");
    _Static_assert(sizeof(NativeCompactMove) == 24, "production move ABI");
    if (argc != 2) {
        fprintf(stderr, "usage: %s directed|protocol\n", argv[0]);
        return HARNESS_NOT_RUN;
    }
    if (strcmp(argv[1], "directed") == 0) return run_directed();
    if (strcmp(argv[1], "protocol") == 0) return run_protocol();
    fprintf(stderr, "unknown mode: %s\n", argv[1]);
    return HARNESS_NOT_RUN;
}
