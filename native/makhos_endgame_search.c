/* Isolated reference kernel, like other candidate translation units. Reuse
 * verified native moves, evaluator and repetition machinery without editing
 * them.  The legacy scalar-only search cannot carry WDL proofs; C2/C3 has its
 * own loop.
 */
#ifndef MAKHOS_ENDGAME_SEARCH_NATIVE_INCLUDED
#define MAKHOS_ENDGAME_SEARCH_NATIVE_INCLUDED 1
#define MAKHOS_NO_MAIN
#include "makhos_native.c"
#endif
#include "makhos_endgame_search.h"

typedef struct { int score, lower, upper; } EGValue;
struct MakhosEndgameSession {
    MakhosTBSet *tb;
    NativeSearchContext *context;
    MoveList *moves;
    MakhosEndgameRoot *completed, *pending;
    MakhosEndgameMove pv[MK_EG_MAX_PLY][MK_EG_MAX_PLY];
    uint32_t lengths[MK_EG_MAX_PLY];
    MakhosEndgameSummary summary;
    atomic_bool cancelled;
    int status;
    double deadline;
    uint64_t node_limit;
};
_Static_assert(sizeof(MakhosEndgameMove)==sizeof(MakhosPackedMove), "move ABI");
_Static_assert(sizeof(MakhosEndgameRoot)==3484, "root ABI");
_Static_assert(sizeof(MakhosEndgameSummary)==104, "summary ABI");
_Static_assert(sizeof(MakhosEndgameHistory)==20, "history ABI");
static EGValue eg_value(int score, int lower, int upper) {
    EGValue value={score,lower,upper}; return value;
}
static bool eg_valid(const MakhosEndgamePosition *p) {
    return p && !(p->red&p->black) && !(p->kings&~(p->red|p->black)) &&
        (p->turn==RED || p->turn==BLACK) && p->reversible_plies<=200;
}
static Position eg_position(const MakhosEndgamePosition *p) {
    Position result={p->red,p->black,p->kings,(uint8_t)p->turn,(uint8_t)p->reversible_plies};
    return result;
}
static int eg_compare(const void *a, const void *b) {
    const Move *ma=a, *mb=b;
    char na[64]={0}, nb[64]={0};
    size_t oa=0, ob=0;
    for (uint8_t i=0;i<ma->path_len;i++)
        oa+=(size_t)snprintf(na+oa,sizeof(na)-oa,"%s%u",i?(ma->capture_count?"x":"-"):"",ma->path[i]+1u);
    for (uint8_t i=0;i<mb->path_len;i++)
        ob+=(size_t)snprintf(nb+ob,sizeof(nb)-ob,"%s%u",i?(mb->capture_count?"x":"-"):"",mb->path[i]+1u);
    return strcmp(na,nb);
}
static bool eg_stop(MakhosEndgameSession *s) {
    if (s->status) return true;
    if (atomic_load_explicit(&s->cancelled,memory_order_relaxed) ||
        (s->deadline && search_now_seconds()>=s->deadline) ||
        (s->node_limit && s->summary.nodes>=s->node_limit)) {
        s->status=MK_EG_CANCELLED; return true;
    }
    return false;
}
/* Precedence matches core. Generate into private heap workspace, including at
 * the safety boundary, so no-legal-move terminal wins over a resource limit. */
static uint32_t eg_terminal(MakhosEndgameSession *s, Position p, int ply) {
    s->context->line[ply]=p;
    if (s->context->repetition_limit &&
        search_repetition_count(s->context,p,ply)>=s->context->repetition_limit) {
        s->summary.repetition_draws++; return 1;
    }
    if (p.reversible_plies>=s->context->no_progress_plies) return 2;
    generate_moves(p,&s->moves[ply]);
    return s->moves[ply].count ? 0 : 3;
}
static EGValue eg_search(MakhosEndgameSession *s, Position p, int depth,
                         int alpha, int beta, int ply, bool quiet) {
    EGValue known=eg_value(0,-1,1);
    s->lengths[ply]=0;
    if (eg_stop(s)) return known;
    s->summary.nodes++;
    uint32_t terminal=eg_terminal(s,p,ply);
    if (terminal) return terminal==3 ? eg_value(-MAKHOS_SEARCH_MATE+ply,-1,-1) : eg_value(0,0,0);
    /* A limit is an explicit failed search, never an eval-based proof. */
    if (ply>=(int)MK_EG_MAX_PLY-1) { s->status=MK_EG_PLY_LIMIT; return known; }
    MakhosEndgamePosition pos={p.red,p.black,p.kings,p.turn,p.reversible_plies};
    MakhosTBProbe probe={sizeof(probe),MAKHOS_ENDGAME_API_V1,0,0,0,0};
    int status=makhos_tb_set_probe(s->tb,&pos,&probe);
    if (status==MK_EG_OK) {
        s->summary.tb_hits[probe.material_count]++;
        known.lower=known.upper=probe.outcome;
        int distance=probe.distance<0?0:probe.distance;
        known.score=probe.outcome*(MAKHOS_SEARCH_MATE-distance);
        if (s->context->repetition_limit) {
            if (probe.outcome==1) known.lower=0;
            if (probe.outcome==-1) known.upper=0;
        }
        if (known.lower==known.upper) return known;
        if (known.lower==0 && alpha<0) alpha=0;
        if (known.upper==0 && beta>0) beta=0;
        if (alpha>=beta) { known.score=known.lower==0?alpha:beta; return known; }
    } else if (status!=MK_EG_MISS) { s->status=status; return known; }
    if (!quiet && depth<=0) return eg_search(s,p,0,alpha,beta,ply,true);
    MoveList *moves=&s->moves[ply];
    if (quiet && !moves->moves[0].capture_count) {
        /* Use the same evaluator seam as the native search.  In the ordinary
         * C2 build this is HCE; the isolated C3 wrapper selects NNUE through
         * MAKHOS_NNUE_SEARCH_CANDIDATE without changing the search contract. */
        known.score=native_search_evaluate(s->context,p,p.turn,ply);
        if (known.lower==0 && known.score<0) known.score=0;
        if (known.upper==0 && known.score>0) known.score=0;
        return known;
    }
    qsort(moves->moves,moves->count,sizeof(Move),eg_compare);
    int best=-MAKHOS_SEARCH_INFINITY, lower=-1, upper=-1;
    bool complete=true;
    for (uint32_t i=0;i<moves->count;i++) {
        Move *move=&moves->moves[i];
        EGValue child;
        if (quiet || i==0) {
            if (!native_search_prepare_child(s->context,move->next,ply+1)) {
                s->status=MK_EG_CORRUPT; return known;
            }
            child=eg_search(s,move->next,depth-1,-beta,-alpha,ply+1,quiet);
        } else {
            if (!native_search_prepare_child(s->context,move->next,ply+1)) {
                s->status=MK_EG_CORRUPT; return known;
            }
            child=eg_search(s,move->next,depth-1,-alpha-1,-alpha,ply+1,false);
            int score=-child.score;
            if (!s->status && alpha<score && score<beta) {
                if (!native_search_prepare_child(s->context,move->next,ply+1)) {
                    s->status=MK_EG_CORRUPT; return known;
                }
                child=eg_search(s,move->next,depth-1,-beta,-alpha,ply+1,false);
            }
        }
        if (s->status) return known;
        int score=-child.score;
        if (-child.upper>lower) lower=-child.upper;
        if (-child.lower>upper) upper=-child.lower;
        if (score>best) {
            best=score;
            MakhosPackedMove packed;
            pack_move(&packed,move);
            memcpy(&s->pv[ply][0],&packed,sizeof(packed));
            s->lengths[ply]=s->lengths[ply+1]+1;
            memcpy(&s->pv[ply][1],s->pv[ply+1],s->lengths[ply+1]*sizeof(MakhosEndgameMove));
        }
        if (score>alpha) alpha=score;
        if (alpha>=beta) { complete=false; break; }
    }
    if (!complete) upper=1;
    if (known.lower>lower) lower=known.lower;
    if (known.upper<upper) upper=known.upper;
    if (lower>upper) { s->status=MK_EG_CORRUPT; return known; }
    if (known.lower==0 && best<0) best=0;
    if (known.upper==0 && best>0) best=0;
    return eg_value(best,lower,upper);
}
uint32_t makhos_endgame_search_version(void) { return MK_EG_SEARCH_VERSION; }
int32_t makhos_endgame_session_create(MakhosTBSet *tb, MakhosEndgameSession **out) {
    if (!out) return MK_EG_INVALID;
    *out=NULL;
    if (!tb) return MK_EG_INVALID;
    MakhosEndgameSession *s=calloc(1,sizeof(*s));
    if (!s) return MK_EG_NO_MEMORY;
    s->context=calloc(1,sizeof(*s->context));
    s->moves=calloc(MK_EG_MAX_PLY,sizeof(MoveList));
    s->completed=calloc(MAX_MOVES,sizeof(MakhosEndgameRoot));
    s->pending=calloc(MAX_MOVES,sizeof(MakhosEndgameRoot));
    if (!s->context || !s->moves || !s->completed || !s->pending) {
        makhos_endgame_session_destroy(s); return MK_EG_NO_MEMORY;
    }
#if MAKHOS_NNUE_SEARCH_CANDIDATE
    native_nnue_initialize_stack(s->context);
#endif
    atomic_init(&s->cancelled,false);
    s->status=MK_EG_INVALID; /* no snapshot exists before the first run */
    makhos_tb_set_retain(tb); s->tb=tb; *out=s; return MK_EG_OK;
}
void makhos_endgame_session_destroy(MakhosEndgameSession *s) {
    if (!s) return;
    makhos_tb_set_release(s->tb);
    free(s->context); free(s->moves); free(s->completed); free(s->pending); free(s);
}
void makhos_endgame_cancel(MakhosEndgameSession *s) {
    if (s) atomic_store_explicit(&s->cancelled,true,memory_order_relaxed);
}
int32_t makhos_endgame_run(MakhosEndgameSession *s, const MakhosEndgamePosition *root,
        const MakhosEndgameHistory *history, uint32_t count, uint32_t depth,
        uint32_t clock, uint32_t repetition, uint32_t time_ms, uint64_t node_limit) {
    if (!s) return MK_EG_INVALID;
    memset(&s->summary,0,sizeof(s->summary));
    s->summary.struct_size=sizeof(s->summary); s->summary.version=1;
    s->status=MK_EG_INVALID;
    if (!eg_valid(root) || !depth || depth>=MK_EG_MAX_PLY-1 || repetition>255 ||
        clock!=makhos_tb_set_horizon(s->tb) || count>65535 || (count && !history)) return s->status;
    /* Include root once in initial history; native line count starts at ply 1. */
    MakhosHistoryEntry *entries=calloc((size_t)count+1,sizeof(*entries));
    if (!entries) return s->status=MK_EG_NO_MEMORY;
    bool root_found=false;
    for (uint32_t i=0;i<count;i++) {
        MakhosEndgamePosition h={history[i].red,history[i].black,history[i].kings,history[i].turn,0};
        if (!eg_valid(&h) || !history[i].count || history[i].count>255) { free(entries); return s->status; }
        Position p=eg_position(&h);
        for (uint32_t j=0;j<i;j++) if (same_history_entry(&entries[j],p)) { free(entries); return s->status; }
        entries[i]=(MakhosHistoryEntry){h.red,h.black,h.kings,(uint8_t)h.turn,(uint8_t)history[i].count,{0,0}};
        if (same_history_entry(&entries[i],eg_position(root))) root_found=true;
    }
    if (!root_found) entries[count++]=(MakhosHistoryEntry){root->red,root->black,root->kings,(uint8_t)root->turn,1,{0,0}};
    s->context->initial_history=entries; s->context->initial_history_count=count;
    s->context->no_progress_plies=(uint8_t)clock; s->context->repetition_limit=(uint8_t)repetition;
    s->deadline=time_ms?search_now_seconds()+time_ms/1000.0:0;
    s->node_limit=node_limit; s->status=0;
    atomic_store_explicit(&s->cancelled,false,memory_order_relaxed);
    Position p=eg_position(root);
    uint32_t terminal=eg_terminal(s,p,0);
    if (terminal) {
        s->summary.terminal_reason=terminal;
        s->summary.score=terminal==3?-MAKHOS_SEARCH_MATE:0;
        s->summary.lower=s->summary.upper=terminal==3?-1:0;
    } else {
#if MAKHOS_NNUE_SEARCH_CANDIDATE
        /* Terminal adjudication must precede NNUE feature encoding.  In
         * particular a clock-80 root is a draw even though NNUE rejects the
         * 80-ply feature bucket. */
        if (!native_search_refresh_root(s->context,p)) {
            s->status=MK_EG_CORRUPT;
        }
#endif
        if (s->status) {
            s->context->initial_history=NULL; s->context->initial_history_count=0;
            memset(s->context->line,0,sizeof(s->context->line)); free(entries);
            return s->status;
        }
        qsort(s->moves[0].moves,s->moves[0].count,sizeof(Move),eg_compare);
        for (uint32_t d=1;d<=depth && !s->status;d++) {
            for (uint32_t i=0;i<s->moves[0].count;i++) {
                Move *move=&s->moves[0].moves[i];
                EGValue value=eg_search(s,move->next,(int)d-1,-MAKHOS_SEARCH_INFINITY,MAKHOS_SEARCH_INFINITY,1,false);
                if (s->status) break;
                MakhosEndgameRoot *r=&s->pending[i];
                memset(r,0,sizeof(*r)); r->struct_size=sizeof(*r); r->version=1;
                r->score=-value.score; r->lower=-value.upper; r->upper=-value.lower;
                r->depth=d; r->pv_count=s->lengths[1]+1;
                MakhosPackedMove packed; pack_move(&packed,move);
                memcpy(r->pv,&packed,sizeof(packed));
                memcpy(r->pv+1,s->pv[1],s->lengths[1]*sizeof(MakhosEndgameMove));
            }
            if (!s->status) {
                s->summary.completed_depth=d; s->summary.root_count=s->moves[0].count;
                memcpy(s->completed,s->pending,s->summary.root_count*sizeof(*s->completed));
            }
        }
    }
    s->context->initial_history=NULL; s->context->initial_history_count=0;
    memset(s->context->line,0,sizeof(s->context->line)); free(entries);
    if (s->status && s->status!=MK_EG_CANCELLED) {
        s->summary.completed_depth=0; s->summary.root_count=0;
    }
    return s->status;
}
int32_t makhos_endgame_results(MakhosEndgameSession *s, MakhosEndgameSummary *out,
                              MakhosEndgameRoot *roots, uint32_t capacity) {
    if (!s || !out || out->struct_size!=sizeof(*out) || out->version!=1) return MK_EG_INVALID;
    if (s->status && s->status!=MK_EG_CANCELLED) return s->status;
    *out=s->summary;
    if (capacity<out->root_count) return MK_EG_BUFFER_TOO_SMALL;
    if (out->root_count && !roots) return MK_EG_INVALID;
    if (out->root_count) memcpy(roots,s->completed,out->root_count*sizeof(*roots));
    return MK_EG_OK;
}
