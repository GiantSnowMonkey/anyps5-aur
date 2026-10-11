ARG ARCH_IMAGE=archlinux@sha256:4e77cf2ea5f410e6f8be5abf93ccf17ce2436e87a138c167208356711a405dbd
FROM ${ARCH_IMAGE} AS builder
RUN pacman -Syu --noconfirm --needed base-devel git cmake ninja python ca-certificates libx11 libxext alsa-lib libpulse systemd vulkan-headers vulkan-icd-loader && pacman -Scc --noconfirm
RUN useradd --create-home builder
USER builder
WORKDIR /home/builder
ARG UPSTREAM_COMMIT
ARG JOBS=4
RUN git clone https://github.com/boykopovar/AnyPS5.git source && cd source && git checkout --detach "$UPSTREAM_COMMIT" && test "$(git rev-parse HEAD)" = "$UPSTREAM_COMMIT" && git rev-parse HEAD > /home/builder/upstream-commit.txt
WORKDIR /home/builder/source
RUN cmake -S . -B build-relinker -G Ninja -DCMAKE_BUILD_TYPE=Release -DANYPS5_RELINKER_ONLY=ON -DBUILD_TESTING=ON && cmake --build build-relinker --parallel "$JOBS" && ctest --test-dir build-relinker --output-on-failure --no-tests=error
RUN git submodule update --init --recursive
RUN cmake -S . -B build-full -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=gcc -DCMAKE_CXX_COMPILER=g++ -DBUILD_TESTING=ON && cmake --build build-full --parallel "$JOBS" && cmake --build build-full --target libs --parallel "$JOBS" && ctest --test-dir build-full --output-on-failure --no-tests=error

FROM ${ARCH_IMAGE} AS artifacts
COPY --from=builder /home/builder/source/build-full/core/relinker/relinker /opt/anyps5/relinker
COPY --from=builder /home/builder/source/build-full/core/libs/libs/ /opt/anyps5/libs/
COPY --from=builder /home/builder/upstream-commit.txt /opt/anyps5/upstream-commit.txt
COPY --from=builder /home/builder/source/LICENSE /opt/anyps5/LICENSE
WORKDIR /opt/anyps5
CMD ["sleep", "infinity"]
