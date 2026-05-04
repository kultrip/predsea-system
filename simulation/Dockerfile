# PredSea WRF/WPS image.
#
# This build follows the proven Debian Bullseye + conda-forge Jasper pattern.
# It is intended for linux/amd64 cloud runners. On Apple Silicon, build with:
# docker build --platform linux/amd64 -t predsea-wrf:4.5 -f simulation/Dockerfile simulation
FROM debian:bullseye AS wrf-builder

ARG DEBIAN_FRONTEND=noninteractive
ARG WRF_VERSION=4.5
ARG WPS_VERSION=4.5
ARG JASPER_VERSION=2.0.33
ARG WRF_CONFIGURE_OPTION=34
ARG WPS_CONFIGURE_OPTION=3

ENV DIR=/opt \
    WRF_DIR=/opt/WRF \
    WPS_DIR=/opt/WPS \
    NETCDF=/usr \
    JASPERLIB=/usr/local/lib \
    JASPERINC=/usr/local/include \
    LD_LIBRARY_PATH=/usr/local/lib \
    WRFIO_NCD_LARGE_FILE_SUPPORT=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    csh \
    curl \
    file \
    flex \
    gfortran \
    gcc \
    g++ \
    git \
    libnetcdf-dev \
    libnetcdff-dev \
    libopenmpi-dev \
    libpng-dev \
    m4 \
    make \
    netcdf-bin \
    openmpi-bin \
    perl \
    python3 \
    tcsh \
    wget \
    bzip2 \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt

RUN wget -q https://anaconda.org/conda-forge/jasper/${JASPER_VERSION}/download/linux-64/jasper-${JASPER_VERSION}-h98d927c_0.tar.bz2 -O jasper.tar.bz2 \
    && tar -xjf jasper.tar.bz2 -C /usr/local --strip-components=1 \
    && rm jasper.tar.bz2

RUN wget -q https://github.com/wrf-model/WRF/archive/refs/tags/v${WRF_VERSION}.tar.gz -O wrf.tar.gz \
    && tar -xzf wrf.tar.gz \
    && mv WRF-${WRF_VERSION} WRF \
    && rm wrf.tar.gz

WORKDIR /opt/WRF

RUN printf "%s\n1\n" "${WRF_CONFIGURE_OPTION}" | ./configure \
    && ./compile -j "$(nproc)" em_real

WORKDIR /opt

RUN wget -q https://github.com/wrf-model/WPS/archive/refs/tags/v${WPS_VERSION}.tar.gz -O wps.tar.gz \
    && tar -xzf wps.tar.gz \
    && mv WPS-${WPS_VERSION} WPS \
    && rm wps.tar.gz

WORKDIR /opt/WPS

RUN printf "%s\n" "${WPS_CONFIGURE_OPTION}" | ./configure \
    && ./compile

FROM debian:bullseye-slim AS wrf-runtime

ARG DEBIAN_FRONTEND=noninteractive

ENV WRF_DIR=/opt/WRF \
    WPS_DIR=/opt/WPS \
    JASPERLIB=/usr/local/lib \
    JASPERINC=/usr/local/include \
    LD_LIBRARY_PATH=/usr/local/lib \
    PATH=/opt/WRF/run:/opt/WPS:${PATH}

RUN apt-get update && apt-get install -y --no-install-recommends \
    csh \
    libgfortran5 \
    libnetcdf15 \
    libpng16-16 \
    openmpi-bin \
    python3 \
    python3-netcdf4 \
    python3-pip \
    zlib1g \
    && rm -rf /var/lib/apt/lists/*

RUN mpirun --version

COPY --from=wrf-builder /usr/local/lib/libjasper* /usr/local/lib/
COPY --from=wrf-builder /usr/local/include/jasper /usr/local/include/jasper
COPY --from=wrf-builder /opt/WRF /opt/WRF
COPY --from=wrf-builder /opt/WPS /opt/WPS
COPY setup_domain.py /opt/predsea/setup_domain.py
COPY run_pipeline.sh /opt/predsea/run_pipeline.sh

WORKDIR /workspace

ENTRYPOINT ["/bin/bash"]
