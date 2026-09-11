from pathlib import Path
import sys,json,time,statistics,hashlib
root=Path.cwd();sys.path.insert(0,str(root))
from makhos.core import initial_state,parse_position
from makhos.native import NativeSearch
from makhos.compact_tb3 import CompactTablebase
from makhos.native_endgame import NativeEndgameTablebase
from makhos.native_endgame_search import NativeEndgameSearch
from makhos.search import Engine,SearchLimits,Mode
from makhos.server import is_native_endgame_position
from scratch.nnue_full_suite_attestation import ExclusiveSuiteLease
lib=root/'build/native_endgame_c4/makhos_endgame_search_nnue.so';model=root/'build/nnue_quantized_v1/model_a.mknnue'
magnum=parse_position('B:BM23,26:BK15:RM13,14,19,21,27');nine=parse_position('B:BK6,13,14:RK4,16,17,18,19,21')
rows=[];timings=[]
with ExclusiveSuiteLease(root), CompactTablebase() as tb3, NativeEndgameTablebase(tb3,library=lib) as tb, NativeEndgameSearch(tb,nnue_model=model) as eg, NativeSearch(library=lib,hash_power=12,nnue_model=model) as legacy:
 for name,state in [('opening',initial_state()),('quiet8',parse_position('B:BK1,5,6,9:RK24,28,31,32')),('noncross10',parse_position('B:BK6,13,14,32:RK4,16,17,18,19,21')),('flagoff8',magnum)]:
  engine=Engine(native_search=legacy,native_endgame_search=eg,native_endgame_enabled=name!='flagoff8',native_tablebase=tb3,exact_piece_limit=0)
  for depth in (2,4):
   for mode in Mode:
    engine.clear();result=engine.search(state,SearchLimits(depth=depth),mode=mode)
    rows.append(dict(case=name,depth=result.depth,mode=mode.value,backend=engine.last_search_backend,nodes=result.nodes,score=result.score,move=result.move.notation,pv=[m.notation for m in result.pv],bound=[int(result.bound.lower),int(result.bound.upper)]))
  samples=[]
  for _ in range(5):
   start=time.perf_counter_ns()
   for _ in range(2000): is_native_endgame_position(state)
   samples.append((time.perf_counter_ns()-start)/2000/1000)
  timings.append(dict(case=name,median_predicate_us=statistics.median(samples)))
 report=dict(rows=rows,predicate_timings=timings,admission={name:dict(server=is_native_endgame_position(state),adapter=eg.supports_position(state)) for name,state in [('8to6',magnum),('9to6',nine)]},library_sha256=hashlib.sha256(lib.read_bytes()).hexdigest())
 p=root/'build/transition_validation/non_endgame.json';p.write_text(json.dumps(report,indent=2)+'\n');print(report['admission'])
