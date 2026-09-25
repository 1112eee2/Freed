from pathlib import Path
import argparse, hashlib
root=Path(__file__).resolve().parents[3]
parser=argparse.ArgumentParser(description='Generate measurement-only TT alias instrumentation; never use it for timing or play.')
parser.add_argument('--output', type=Path, required=True)
args=parser.parse_args()
assert hashlib.sha256((root/'native/makhos_native.c').read_bytes()).hexdigest() == 'ec04d86ec3b1766da1fb69893cf3c36e1adff4c4553800b13bf5a3886bea2e2b', 'Audit source changed; review instrumentation before use'
s=(root/'native/makhos_native.c').read_text()
def sub(a,b):
 global s
 assert s.count(a)==1,(a[:80],s.count(a));s=s.replace(a,b)
sub('    NativeTTEntry *tt;\n','    NativeTTEntry *tt;\n    Position *audit_positions;\n    uint64_t audit_counts[6];\n    uint64_t audit_sample[14];\n')
sub('    context->generation = 1;\n    return true;\n}\n\n#if MAKHOS_SHARED_TT', '    context->audit_positions = calloc(context->tt_count, sizeof(Position));\n    if (!context->audit_positions) { free(context->tt); return false; }\n    context->generation = 1;\n    return true;\n}\n\n#if MAKHOS_SHARED_TT')
sub('static void destroy_native_search(NativeSearchContext *context) {','static void destroy_native_search(NativeSearchContext *context) {\n    free(context->audit_positions);')
sub('        entry->key = key;\n        entry->score = score_to_tt(best_score, ply);','        context->audit_positions[tt_index] = position;\n        entry->key = key;\n        entry->score = score_to_tt(best_score, ply);')
sub('    if (entry->key == key && entry->flag != SEARCH_TT_EMPTY) {','    Position audit_old = context->audit_positions[tt_index];\n    bool audit_alias = audit_old.red != position.red || audit_old.black != position.black || audit_old.kings != position.kings || audit_old.turn != position.turn || audit_old.reversible_plies != position.reversible_plies;\n    if (entry->key == key && entry->flag != SEARCH_TT_EMPTY) {\n        context->audit_counts[0]++;\n        if (audit_alias) { context->audit_counts[1]++; if (audit_old.kings != position.kings) context->audit_counts[2]++; }')
sub('            if (tt_cutoff) {','            if (tt_cutoff) {\n                context->audit_counts[3]++;\n                if (audit_alias) {\n                    context->audit_counts[4]++;\n                    if (audit_old.kings != position.kings) context->audit_counts[5]++;\n                    if (context->audit_sample[0] == 0 || audit_old.kings != position.kings) {\n                        uint64_t sample[14] = {key,audit_old.red,audit_old.black,audit_old.kings,audit_old.turn,audit_old.reversible_plies,position.red,position.black,position.kings,position.turn,position.reversible_plies,(uint64_t)depth,(uint64_t)entry->depth,(uint64_t)entry->flag};\n                        memcpy(context->audit_sample,sample,sizeof(sample));\n                    }\n                }')
s+='\nMAKHOS_API void makhos_loss_audit(void *handle, uint64_t *out) { NativeSearchContext *c=handle; memcpy(out,c->audit_counts,sizeof(c->audit_counts)); memcpy(out+6,c->audit_sample,sizeof(c->audit_sample)); }\n'
s='#define MAKHOS_NO_MAIN 1\n#define MAKHOS_NNUE_RUNTIME_INCLUDED 1\n#define MAKHOS_NNUE_SEARCH_CANDIDATE 1\n#include "makhos_nnue_avx2_update.c"\n'+s
args.output.parent.mkdir(parents=True,exist_ok=True)
with args.output.open('x', encoding='utf-8') as stream: stream.write(s)
print(args.output)
