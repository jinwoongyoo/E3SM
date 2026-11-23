# Aegis Thrust 1 — E3SM/ELM on Apple silicon (Phase 0)

This directory records how the official E3SM land model (ELM) was built and
run on the Aegis development MacBook (Apple silicon, macOS, osx-arm64) using
E3SM's own CIME test harness. Phase 0 goal: pass E3SM's standard tiny
single-point land smoke test with no changes to E3SM source.

Branch: `aegis/thrust1-elm` of https://github.com/jinwoongyoo/E3SM, based on
E3SM-Project/E3SM `master` @ `c5c6b14b23`.

## Contents

| File | Purpose |
|------|---------|
| `environment.yml` | conda-forge environment spec (compilers, MPICH, HDF5, NetCDF, PnetCDF, MOAB, cmake, perl, python) |
| `conda-osx-arm64.lock.txt` | Exact explicit lock (`conda list --explicit --md5`) of the environment that passed the tests |
| `dotcime/config_machines.xml` | CIME user machine definition `aegis-mac` (copy to `~/.cime/`) |
| `dotcime/aegis-mac_gnu.cmake` | CIME cmake macros for `aegis-mac` + `gnu` (copy to `~/.cime/`) |
| `prefetch_inputdata.sh` | Optional parallel input-data prefetch for a CIME case |

## Results

All on the Aegis MacBook (macOS 26.7.1, Apple M3 Max, 14 cores, 96 GiB RAM),
E3SM `master` @ `c5c6b14b23`, MOAB coupler (default), 1 MPI task,
`GMAKE_J=6`, `nice -n 10`. No E3SM source changes.

| Test | Result | Shared-lib build | Model build | Run |
|------|--------|------------------|-------------|-----|
| `SMS_Ld1.1x1_brazil.IELM.aegis-mac_gnu` | **PASS** (all phases incl. MEMLEAK) | 113 s | 88 s | 2 s |
| `SMS_D_Ld1.1x1_brazil.IELM.aegis-mac_gnu` (debug: `-O0`, bounds checks, FP traps) | **PASS** | 97 s | 71 s | 5 s |
| `ERS_Ld3.1x1_brazil.IELM.aegis-mac_gnu` | **PASS** (incl. `COMPARE_base_rest`; cprnc: 159 fields, 0 diffs) | 113 s | 87 s | 4 s |
| `SMS_Ld1_Vmct.1x1_brazil.IELM.aegis-mac_gnu` (legacy MCT driver) | **PASS** | 96 s | 96 s | 4 s |

* The first three tests ran together in one `create_test` call (test id
  `p0h`, input data already present): **359 s wall** in total. The `_Vmct`
  test (id `p0d`) ran with an earlier revision of the macros.
* `e3sm.exe` links BLAS/LAPACK from Apple Accelerate (`otool -L`:
  `/System/Library/Frameworks/Accelerate.framework`); see note 7.
* Input data downloaded into `DIN_LOC_ROOT`: **~40 GiB**, of which ~37.4 GiB
  is `atm/datm7` (CLM_QIAN T62 forcing, 1188 monthly files; see note 6),
  and ~2.4 GiB the MODIS LAI stream (`lnd/clm2/lai_streams`). With
  `prefetch_inputdata.sh` (8 parallel connections, ~7-8 MB/s aggregate) this
  took ~1.5 h; it is a one-time cost.
* Test directories: `/Volumes/SSD-Data/aegis-data/e3sm-work/scratch/tests/<test>.p0h`
  (run dirs: `/Volumes/SSD-Data/aegis-data/e3sm-work/scratch/<test>.p0h/run`).

## Reproduce

### Prerequisites

* macOS on Apple silicon (arm64). Tested: macOS 26.7.1, Apple M3 Max,
  14 cores, 96 GiB RAM.
* Xcode Command Line Tools (`xcode-select --install`). They are used **only**
  for the macOS SDK (system headers, `libSystem`, `libc++`, and the
  Accelerate framework that the conda compilers link against, e.g.
  `.../CommandLineTools/SDKs/MacOSX.sdk`); no Xcode compilers or Python are
  used. (CMake may record the full Xcode SDK path instead if Xcode is also
  installed; either works.)
* Miniforge at `~/miniforge3` (conda/mamba from conda-forge).
* ~45 GiB free disk for input data plus a few GiB for builds.

All paths below are the ones used on the Aegis MacBook. Everything lives in
user space (no sudo, no Homebrew, no Xcode/system Python). conda-forge
supplies the compilers, MPI, the I/O libraries (HDF5, NetCDF, PnetCDF),
MOAB, and cmake/make/perl/python; the system supplies only the macOS SDK,
including the Accelerate framework that E3SM uses for BLAS/LAPACK (see
note 7).

### 1. E3SM clone and submodules

Only the submodules needed for land-only (I-compset) cases are initialised:

```bash
git clone --filter=blob:none -b aegis/thrust1-elm https://github.com/jinwoongyoo/E3SM \
    /Volumes/SSD-Data/aegis-data/E3SM
cd /Volumes/SSD-Data/aegis-data/E3SM
git submodule update --init cime externals/scorpio externals/mct \
    components/elm/src/external_models/fates
git -C cime submodule update --init      # CIME/non_py/cprnc (used by ERS/compare)
```

All later steps run from `/Volumes/SSD-Data/aegis-data/E3SM`; `aegis/...`
paths are relative to it.

### 2. Conda environment

```bash
cd /Volumes/SSD-Data/aegis-data/E3SM
export CONDA_PKGS_DIRS=/Volumes/SSD-Data/aegis-data/conda-pkgs
# exact, reproducible:
~/miniforge3/bin/mamba create -p /Volumes/SSD-Data/aegis-data/conda-envs/e3sm \
    --file aegis/conda-osx-arm64.lock.txt
# or, re-solve from the spec (major.minor pins, conda-forge only):
~/miniforge3/bin/mamba env create -p /Volumes/SSD-Data/aegis-data/conda-envs/e3sm \
    -f aegis/environment.yml
```

Toolchain in the lock: gfortran 15.3 (Fortran), clang 21.1 (C/C++),
MPICH 5.0.2, HDF5 2.2.0 (MPI), NetCDF-C 4.10.1, NetCDF-Fortran 4.6.4,
PnetCDF 1.15.1, MOAB 5.6.0 (MPI + TempestRemap), cmake 4.5.1, python 3.11.

The environment does not need to be activated: the CIME machine file puts its
`bin/` first on `PATH`.

### 3. CIME user machine `aegis-mac`

```bash
cd /Volumes/SSD-Data/aegis-data/E3SM
mkdir -p ~/.cime
cp aegis/dotcime/config_machines.xml aegis/dotcime/aegis-mac_gnu.cmake ~/.cime/
mkdir -p /Volumes/SSD-Data/aegis-data/e3sm-work/{scratch,inputdata,baselines,tmp}
```

`aegis-mac` is based on E3SM's `mac` machine entry, with:

| Setting | Value |
|---------|-------|
| `CIME_OUTPUT_ROOT` | `/Volumes/SSD-Data/aegis-data/e3sm-work/scratch` |
| `DIN_LOC_ROOT` | `/Volumes/SSD-Data/aegis-data/e3sm-work/inputdata` |
| `DIN_LOC_ROOT_CLMFORC` | `/Volumes/SSD-Data/aegis-data/e3sm-work/inputdata/atm/datm7` |
| `BASELINE_ROOT` | `/Volumes/SSD-Data/aegis-data/e3sm-work/baselines/$COMPILER` |
| `GMAKE_J` | 6 (a self-hosted CI runner shares this machine) |
| compilers / MPI | `gnu` / `mpich` from the conda env |
| `AEGIS_E3SM_ENV`, `NETCDF_PATH`, `PNETCDF_PATH`, `HDF5_ROOT`, `MOAB_ROOT` | the conda env prefix |
| `FI_PROVIDER` | `tcp` (see notes) |

The conda prefix and the work directory are each written once, as the XML
entities `condaenv` and `work` at the top of `config_machines.xml`. (CIME
resolves every `$ENV{...}` in `<environment_variables>` before setting any
of them, so the paths cannot be derived from `AEGIS_E3SM_ENV` there.) The
cmake macros use `$ENV{AEGIS_E3SM_ENV}`.

Machine/user-specific values to adjust before reusing on another Mac:
the two entities, `MAX_TASKS_PER_NODE` / `MAX_MPITASKS_PER_NODE` (6 here,
to leave cores for a self-hosted CI runner), `GMAKE_J`, and `SUPPORTED_BY`
(contact address). Keep `~/.cime/` and `aegis/dotcime/` byte-identical
when changing them (`diff -r ~/.cime aegis/dotcime` must print nothing).

### 4. Run the tests

The `PATH` export below is only needed to run `create_test` itself (it
needs the env's python/perl); builds and runs get their `PATH` from the
machine file.

```bash
cd /Volumes/SSD-Data/aegis-data/E3SM
export PATH=/Volumes/SSD-Data/aegis-data/conda-envs/e3sm/bin:/usr/bin:/bin:/usr/sbin:/sbin
W=/Volumes/SSD-Data/aegis-data/e3sm-work
nice -n 10 ./cime/scripts/create_test \
    SMS_Ld1.1x1_brazil.IELM.aegis-mac_gnu \
    SMS_D_Ld1.1x1_brazil.IELM.aegis-mac_gnu \
    ERS_Ld3.1x1_brazil.IELM.aegis-mac_gnu \
    --output-root $W/scratch --test-root $W/scratch/tests --test-id p0h --wait
```

CIME downloads missing input data automatically (E3SM server first, then the
CESM svn server). Its downloader is serial; to fill a new `DIN_LOC_ROOT`
faster, build with `--no-run`, prefetch, then submit (same `PATH` and `W`
as above):

```bash
cd /Volumes/SSD-Data/aegis-data/E3SM
nice -n 10 ./cime/scripts/create_test SMS_Ld1.1x1_brazil.IELM.aegis-mac_gnu \
    --output-root $W/scratch --test-root $W/scratch/tests --test-id p0h --no-run --wait
aegis/prefetch_inputdata.sh $W/scratch/tests/SMS_Ld1.1x1_brazil.IELM.aegis-mac_gnu.p0h 8
(cd $W/scratch/tests/SMS_Ld1.1x1_brazil.IELM.aegis-mac_gnu.p0h && ./case.submit)
```

`prefetch_inputdata.sh CASEROOT [NJOBS]` exits 0 only if every listed file
under `DIN_LOC_ROOT` is present afterwards; otherwise it prints the
`MISSING` files and a summary and exits 1. Downloads are accepted only if
non-empty, not an HTML error page, and (for `.nc`) start with a NetCDF or
HDF5 signature.

## Notes and gotchas (all handled without changing E3SM source)

1. **Driver.** E3SM `master` now defaults to the MOAB coupler
   (`cime_config/customize/config.py: driver_default = "moab"`), so the
   build needs a MOAB library. conda-forge `moab=*=mpi_mpich_tempest_*`
   works (its `imoab.mod` is gfortran-15 compatible); `MOAB_ROOT` points
   at the env. The legacy MCT driver also builds and is selectable with the
   `_Vmct` test modifier (e.g. `SMS_Ld1_Vmct.1x1_brazil.IELM.aegis-mac_gnu`).
2. **MPI.** conda-forge Open MPI 5.0.x segfaults in `PMIx_Finalize` on this
   macOS, so the env uses MPICH. MPICH's default libfabric provider hangs in
   `MPI_Finalize` on macOS; `FI_PROVIDER=tcp` (set in the machine file)
   fixes it.
3. **`-mcmodel=large`.** E3SM's `gnu.cmake` adds it on `arm64`, but
   gfortran/clang for arm64-apple-darwin do not implement it; the machine
   macros strip it.
   `gnu.cmake` also appends the gfortran-only `-fcheck=bounds
   -ffpe-trap=invalid,zero,overflow` to the **C** debug flags. clang ignores
   them (an "argument unused" warning per C file, no checking), so the
   macros strip them from `CMAKE_C_FLAGS_DEBUG`; Fortran debug flags are
   unchanged. (What actually broke `_D` tests is note 8.)
4. **HDF5 `.dylib`.** `components/cmake/modules/FindHDF5.cmake` limits
   `find_library` to `.so`/`.a`, so on macOS it cannot find conda's
   `libhdf5*.dylib` and the link fails with `-lHDF5_HL_LIBRARIES-NOTFOUND`.
   The machine macros resolve `HDF5_LIBRARIES` / `HDF5_HL_LIBRARIES` first
   with `find_library(... NO_DEFAULT_PATH REQUIRED)` in the env's `lib/`.
   (A one-line upstream fix would add `.dylib` to the suffix list.)
5. **Case-folding path bug.** CMake 4.x on macOS normalises path case even
   on a case-sensitive APFS volume. A sibling directory named `e3sm` next to
   the `E3SM` clone made CMake rewrite `.../E3SM/...` to `.../e3sm/...`
   ("source directory does not exist"). The work tree is therefore
   `/Volumes/SSD-Data/aegis-data/e3sm-work`, not `.../e3sm`. Never create
   a directory whose name differs from `E3SM` only by case next to the clone.
6. **Input data.** `1x1_brazil` + `IELM` uses the DATM `CLM_QIAN` forcing
   (global T62, 1972–2004). CIME checks every stream file even for a 1-day
   run, so the first run downloads ~1188 monthly files (~37.4 GiB). The E3SM
   server (`web.lcrc.anl.gov`) does not host this dataset; it comes from
   the CESM svn inputdata server.
7. **BLAS/LAPACK.** E3SM's `components/cmake/find_dep_packages.cmake` uses
   CMake `find_package(BLAS/LAPACK)`; the macros set `BLA_VENDOR=Apple`, so
   `e3sm.exe` links Apple **Accelerate** from the macOS SDK (`otool -L`
   shows `/System/Library/Frameworks/Accelerate.framework`). The conda-forge
   OpenBLAS-backed `libblas`/`liblapack` in the env are there only because
   `moab` and `tempest-remap` depend on them (`libTempestRemap` links
   them); E3SM's own code does not use them. CIME's `SLIBS` and a
   `LAPACK_ROOT` variable are not used by E3SM's CMake build, so they are
   not set.
8. **Debug builds and `__powidf2`.** `e3sm.exe` is linked by `mpicxx`
   (clang++). Its `-lm` (libSystem) precedes gfortran's `-lgcc`, so the
   gfortran helper `__powidf2` (used for `x**n` at `-O0`) bound to Apple's
   compiler-rt copy, which evaluates `1/r` even for positive `n`. In
   `SMS_D` this made `0.0**3` in DATM (`datm_comp_mod.F90`, shortwave
   split at night) raise divide-by-zero, which `-ffpe-trap` turns into
   **SIGILL** on Apple silicon (FP traps are delivered as SIGILL there).
   The macros put gfortran's `libgcc.a` first on the link line so these
   helpers come from libgcc, as in a gfortran-driven link. Release builds
   inline `x**3` and were not affected.
