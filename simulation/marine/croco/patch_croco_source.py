#!/usr/bin/env python3
import os
import pathlib

def main():
    lm = int(os.environ.get("PREDSEA_CROCO_LM", "499"))
    mm = int(os.environ.get("PREDSEA_CROCO_MM", "399"))
    vertical_levels = int(os.environ.get("PREDSEA_CROCO_N", "32"))
    if min(lm, mm, vertical_levels) <= 0:
        raise ValueError("CROCO compile-time dimensions must be positive")
    build_dir = pathlib.Path("tmp/croco_build")
    src_cppdefs = build_dir / "croco_src/OCEAN/cppdefs.h"
    dst_cppdefs = build_dir / "cppdefs.h"
    src_param = build_dir / "croco_src/OCEAN/param.h"
    dst_param = build_dir / "param.h"

    if not src_cppdefs.exists() or not src_param.exists():
        print("❌ Error: CROCO source files not found under tmp/croco_build/croco_src/OCEAN/")
        return 1

    # 1. Patch cppdefs.h
    print("📝 Patching cppdefs.h...")
    cppdefs_content = src_cppdefs.read_text()

    # Define BALEARIC_1KM and undefine BENGUELA_LR
    cppdefs_content = cppdefs_content.replace(
        "# define BENGUELA_LR",
        "# undef BENGUELA_LR\n# define BALEARIC_1KM"
    )

    # Enable MPI parallelization
    cppdefs_content = cppdefs_content.replace(
        "# undef  MPI",
        "# define MPI"
    )

    # Enable CLIMATOLOGY boundaries and nudging
    cppdefs_content = cppdefs_content.replace(
        "# undef CLIMATOLOGY",
        "# define CLIMATOLOGY"
    )

    # Use real gridded WRF bulk forcing. Explicitly disable the analytical
    # zero-flux fallback used by the historical compile-only prototype.
    cppdefs_content += "\n\n/* BALEARIC_1KM Specific Overrides */\n#ifdef BALEARIC_1KM\n# define MASKING\n# define BULK_FLUX\n# define SOLAR_PENETRATION\n# define WTYPE 1\n# define LMD_MIXING\n# ifdef LMD_MIXING\n#  define LMD_SKPP\n#  define LMD_BKPP\n#  define LMD_RIMIX\n#  define LMD_CONVEC\n#  define LMD_NONLOCAL\n# endif\n# undef ONLINE\n# undef MERRA_AEROSOL\n# undef ANA_SMFLUX\n# undef ANA_STFLUX\n# undef ANA_SSFLUX\n# define FRC_BRY\n# define Z_FRC_BRY\n# define M2_FRC_BRY\n# define M3_FRC_BRY\n# define T_FRC_BRY\n#endif\n"

    dst_cppdefs.write_text(cppdefs_content)
    print("✅ Patched cppdefs.h successfully!")

    # 2. Patch param.h
    print("📝 Patching param.h...")
    param_content = src_param.read_text()

    # Inject BALEARIC_1KM dimension parameters with N=30
    param_content = param_content.replace(
        "#  elif defined GIBRALTAR_VHR5",
        "#  elif defined BALEARIC_1KM\n"
        f"       parameter (LLm0={lm}, MMm0={mm},  N={vertical_levels})\n"
        "#  elif defined GIBRALTAR_VHR5"
    )

    # Set MPI subdivision grid (4 x 4 = 16 cores) for BALEARIC_1KM
    param_content = param_content.replace(
        "      parameter (NP_XI=1,  NP_ETA=4,  NNODES=NP_XI*NP_ETA)",
        "# if defined BALEARIC_1KM\n      parameter (NP_XI=4,  NP_ETA=4,  NNODES=NP_XI*NP_ETA)\n# else\n      parameter (NP_XI=1,  NP_ETA=4,  NNODES=NP_XI*NP_ETA)\n# endif"
    )

    dst_param.write_text(param_content)
    print("✅ Patched param.h successfully!")
    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
