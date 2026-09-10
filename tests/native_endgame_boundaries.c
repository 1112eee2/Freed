/* White-box C2 boundary gate, compiled only as a separate test executable. */
#include "../native/makhos_endgame_search.c"
#define CHECK(test) do { if (!(test)) { fprintf(stderr,"boundary check failed at line %d\n",__LINE__); return 1; } } while (0)
int main(int argc, char **argv) {
    CHECK(argc==4);
    FILE *f=fopen(argv[1],"rb"); CHECK(f);
    CHECK(fseek(f,0,SEEK_END)==0);
    long length=ftell(f); CHECK(length>0);
    rewind(f); uint8_t *image=malloc((size_t)length); CHECK(image);
    CHECK(fread(image,1,(size_t)length,f)==(size_t)length); fclose(f);
    MakhosTBSet *tb=NULL;
    CHECK(makhos_tb3_create(image,(uint64_t)length,(uint32_t)atoi(argv[2]),
                           (uint32_t)atoi(argv[3]),&tb)==MK_EG_OK);
    free(image);
    MakhosEndgameSession *s=NULL;
    CHECK(makhos_endgame_session_create(tb,&s)==MK_EG_OK);
    makhos_tb_set_release(tb);
    s->context->no_progress_plies=80; s->context->repetition_limit=3;
    Position p={1u<<27,(1u<<5)|(1u<<14),(1u<<27)|(1u<<5)|(1u<<14),BLACK,0};
    MakhosHistoryEntry history={p.red,p.black,p.kings,p.turn,3,{0,0}};
    s->context->initial_history=&history; s->context->initial_history_count=1;
    for (int quiet=0;quiet<2;quiet++) {
        s->status=0; p.reversible_plies=80;
        EGValue v=eg_search(s,p,0,-2,2,95,quiet!=0);
        CHECK(!s->status && v.score==0 && v.lower==0 && v.upper==0);
        CHECK(s->summary.repetition_draws==(uint64_t)quiet+1);
    }
    CHECK(s->summary.tb_hits[3]==0);
    history.count=1;
    EGValue v=eg_search(s,p,1,-2,2,95,false);
    CHECK(!s->status && v.lower==0 && v.upper==0);
    p.black=0; p.kings=p.red; p.reversible_plies=0;
    v=eg_search(s,p,1,-2,2,95,false);
    CHECK(!s->status && v.score==-MAKHOS_SEARCH_MATE+95 && v.upper==-1);
    p=(Position){1u<<27,(1u<<5)|(1u<<14),(1u<<27)|(1u<<5)|(1u<<14),BLACK,0};
    (void)eg_search(s,p,1,-2,2,95,false);
    CHECK(s->status==MK_EG_PLY_LIMIT);
    for (int quiet=0;quiet<2;quiet++) {
        s->status=0;
        v=eg_search(s,p,0,-2,-1,0,quiet!=0);
        CHECK(!s->status && v.score==0 && v.lower==0 && v.upper==1);
        v=eg_search(s,p,0,-MAKHOS_SEARCH_INFINITY,MAKHOS_SEARCH_INFINITY,0,quiet!=0);
        CHECK(!s->status && v.score>=0 && v.lower==0 && v.upper==1);
        p.turn=RED; p.red=1u<<31; p.kings=p.red|p.black;
        v=eg_search(s,p,0,1,2,0,quiet!=0);
        CHECK(!s->status && v.score==0 && v.lower==-1 && v.upper==0);
        p.turn=BLACK; p.red=1u<<27; p.kings=p.red|p.black;
    }
    s->context->repetition_limit=0;
    v=eg_search(s,p,2,-MAKHOS_SEARCH_INFINITY,MAKHOS_SEARCH_INFINITY,0,false);
    CHECK(!s->status && v.score>990000 && v.lower==1 && v.upper==1);
    s->context->initial_history=NULL;
    makhos_endgame_session_destroy(s);
    puts("terminal/max-ply/negamax/quiescence/window boundaries PASS");
    return 0;
}
