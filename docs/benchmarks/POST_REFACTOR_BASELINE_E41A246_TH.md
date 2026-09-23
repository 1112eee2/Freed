# บันทึกการตรึง Baseline หลัง Refactor (Commit `e41a246`)

บันทึก ณ วันที่: 2026-09-11  
Git Commit Head: `e41a2469f2e5cdeb9158a36d0a511f392bac293e` (Merge PR #16 - ปิด Tech Debt Roadmap Phase 0–3)  
เอกสารนี้ใช้เป็นหมุดอ้างอิง (Baseline Pinning) อย่างเป็นทางการ สำหรับการเปรียบเทียบ Parity, Performance และ Profiling ก่อนพัฒนา SMP ต่อไป

---

## 1. ดัชนีตัวตนและ Checksum ของ Artifacts (SHA-256)

### 1.1 แหล่งข้อมูลที่ไม่เปลี่ยนแปลง (Immutable Invariants)
| รายการ | SHA-256 | ขนาด (Bytes) | บทบาท / สถานะ |
|---|---|---|---|
| `RULESET.json` | `77528ADDC0E08B17217346C511C7C4084BAD4AF48789955C3EC85EF76A64871F` | 1,856 | กติกาทางการ ห้ามแก้ไข |
| `makhos/core.py` | `03152E513BD360E6C2C97ECDF08DC58A290DCA0AE6E28889AE70585A381292AB` | 14,726 | Reference rules implementation ห้ามแก้ไข |
| `build/makhos_native_accepted.dll` | `FEEDD39CF16E5F5ABC236452BE897ABE1ECF26B8BA7ADCDA4A25022B868C3DDD` | 183,808 | Accepted Control Binary (ABI 5) ห้ามเขียนทับ |

### 1.2 โมเดลและสัญญา NNUE (NNUE Production Artifacts)
| รายการ | SHA-256 | ขนาด (Bytes) | บทบาท / สถานะ |
|---|---|---|---|
| `makhos/nnue_features.py` | `EAEB36EDBF09476F36958AAD7C78ED28B02A2B5EE178622D44BC331ABE30A30E` | 6,139 | Feature specification ABI (`thai-makhos-shared-137-v1`) |
| `build/nnue_quantized_v1/model_a.mknnue` | `07B9AB0F83E253CB74B2ACD2BD5291F5F91EB086E042790F33EA0A8C0914164C` | 43,872 | โมเดล NNUE v1 ที่ใช้งานใน GUI |
| `build/nnue_phase1_evidence/quantization_contract_v2.json` | `68CCA3E4FB46B1C6FA9F45FF34875E0D1ACE396881BB1D2E175CBA5D43E91FBF` | 1,531 | Quantization contract |
| `build/nnue_search_v1_r5/makhos_native_nnue_candidate_v1.dll` | `32C323026A7F78CCD9C4013FC3067422A564EE3D0A6ADE4F1CE5C62356747E79` | 224,256 | Production NNUE Candidate DLL (Gate C Passed) |

### 1.3 ซอร์สโค้ดและ Binary ที่คอมไพล์จากโค้ดหลัง Refactor (Post-Refactor Binaries)
| รายการ | SHA-256 | ขนาด (Bytes) | รายละเอียด |
|---|---|---|---|
| `native/makhos_native.c` | `EC04D86EC3B1766DA1FB69893CF3C36E1ADFF4C4553800B13BF5A3886BEA2E2B` | 218,116 | ซอร์สหลักหลังสกัด Types & Format |
| `native/makhos_types.h` | `5D9F13BDC1FFD8C50F9EFBBD82D7ED6CA53365AAE7794E50DF6F4A1DDEEFB3DB` | 3,345 | Leaf types และ ABI static assertions |
| `native/makhos_format.h` | `7684A6FBAED6285298BDD5BA240DBB34EDB3C2EA7A3625A3F563EACAB0CDC87C` | 4,433 | Move notation และ FEN parsing |
| `native/makhos_endgame_search_nnue.c` | `9357F7ADD80B6AD137EFB5EF544135450727433F212738F6D34BFCAC413ABFFD` | 713 | Translation unit สำหรับ C3/C4 NNUE Endgame |
| `build/makhos_native.dll` | `6F18F2AAD57C277C3752AB1888ABB7D0C123AAB27709F538590E68E6F2B1AB7C` | 187,392 | Native HCE DLL ที่คอมไพล์จาก source หลัง refactor (ABI 5) |
| `build/native_endgame_c4/makhos_endgame_search_nnue.dll` | `EB8AF04596420BD6A00F8CFE981B4027220B119975C5ABEC057BE252BAD8F0B1` | 231,936 | C4 Endgame Search DLL ที่คอมไพล์จาก source หลัง refactor |

### 1.4 Endgame Tablebases (Compact np80)
| รายการ | SHA-256 | ขนาด (Bytes) |
|---|---|---|
| `build/tb4_np80.compact.bin` | `650B0C862343D718FD0FE438DB28E47D48618DEA69D693D65210088775DE30E9` | 12,419,180 |
| `build/tb5_np80.compact.bin` | `718763FB0F7E026E2FBFE09C066B5B40C480D37DF9586F1BE84CBE604466F4CC` | 278,902,544 |
| `build/tb6_np80.compact.bin` | `17A0196F3AFEEFD9D57FB00B641045B0EF790B38A64DA73E19DA3F3369D04A4F` | 4,852,172,800 |

---

## 2. Build Configuration & Compilation Recipes

การคอมไพล์ทั้งหมดจัดการผ่านสคริปต์กลาง `tools/build/build_orchestrator.ps1` โดยใช้ LLVM Clang (`C:\Program Files\LLVM\bin\clang.exe`):

1. **Native HCE (`build/makhos_native.dll`)**:
   ```powershell
   & "C:\Program Files\LLVM\bin\clang.exe" -O3 -march=native -std=c17 -Wall -Wextra -Werror -Wno-unused-function -shared -DMAKHOS_NO_MAIN native/makhos_native.c -o build/makhos_native.dll
   ```
2. **C4 Endgame Search NNUE (`build/native_endgame_c4/makhos_endgame_search_nnue.dll`)**:
   ```powershell
   & "C:\Program Files\LLVM\bin\clang.exe" -O2 -std=c17 -Wall -Wextra -Werror -Wno-unused-function -shared native/makhos_endgame_search_nnue.c native/makhos_endgame_tb.c -o build/native_endgame_c4/makhos_endgame_search_nnue.dll
   ```
3. **NNUE Search Candidate (`build/nnue_search_v1_r5/makhos_native_nnue_candidate_v1.dll`)**:
   ```powershell
   & "C:\Program Files\LLVM\bin\clang.exe" -O3 -march=x86-64 -std=c17 -Wall -Wextra -Werror -Wno-unused-function -shared -Wl,/Brepro native/makhos_native_nnue.c -o build/nnue_search_v1_r5/makhos_native_nnue_candidate_v1.dll
   ```

---

## 3. สรุปเกณฑ์เสร็จสิ้นของ Step 1 (Completion Criteria)

- [x] ระบุ Checksum SHA-256 ของซอร์สโค้ด, โมเดล, Tablebase และ Binary ครบถ้วน
- [x] บันทึก Compiler flags และ Build recipe ที่สามารถทำซ้ำได้แบบ 100%
- [x] ยืนยันว่าไม่มีความคลุมเครือว่าผลการทดสอบใดมาจาก Binary หรือ Source ใด
