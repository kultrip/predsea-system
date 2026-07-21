#!/usr/bin/env python3
import pathlib

def main():
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
    cppdefs_content += "\n\n/* BALEARIC_1KM Specific Overrides */\n#ifdef BALEARIC_1KM\n# define BULK_FLUX\n# undef ONLINE\n# undef MERRA_AEROSOL\n# undef ANA_SMFLUX\n# undef ANA_STFLUX\n# undef ANA_SSFLUX\n# undef FRC_BRY\n# undef Z_FRC_BRY\n# undef M2_FRC_BRY\n# undef M3_FRC_BRY\n# undef T_FRC_BRY\n#endif\n"

    dst_cppdefs.write_text(cppdefs_content)
    print("✅ Patched cppdefs.h successfully!")

    # 2. Patch param.h
    print("📝 Patching param.h...")
    param_content = src_param.read_text()

    # Inject BALEARIC_1KM dimension parameters with N=30
    param_content = param_content.replace(
        "#  elif defined GIBRALTAR_VHR5",
        "#  elif defined BALEARIC_1KM\n       parameter (LLm0=1799, MMm0=949,  N=30)\n#  elif defined GIBRALTAR_VHR5"
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
