# Android SDK + JDK builder for diabl0w/DFRoot (APK stage only).
# Kernel modules are built separately with the upstream GKI/DDK Docker images.
FROM --platform=linux/amd64 eclipse-temurin:21-jdk-jammy

ENV DEBIAN_FRONTEND=noninteractive
ENV ANDROID_HOME=/opt/android-sdk
ENV ANDROID_SDK_ROOT=/opt/android-sdk
ENV PATH="${ANDROID_HOME}/cmdline-tools/latest/bin:${ANDROID_HOME}/platform-tools:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
        bash ca-certificates curl git make python3 unzip zip \
        libstdc++6 zlib1g libgcc-s1 \
    && rm -rf /var/lib/apt/lists/*

# Official Android command-line tools for Linux. SHA-256 is published by Google.
ARG CMDLINE_TOOLS_VERSION=15859902
ARG CMDLINE_TOOLS_SHA256=4e4c464f145a7512b57d088ac6c278c03c9eea610886b35a5e0804e74eedf583
RUN mkdir -p "${ANDROID_HOME}/cmdline-tools" \
    && curl -fSL --retry 3 \
         "https://dl.google.com/android/repository/commandlinetools-linux-${CMDLINE_TOOLS_VERSION}_latest.zip" \
         -o /tmp/android-tools.zip \
    && echo "${CMDLINE_TOOLS_SHA256}  /tmp/android-tools.zip" | sha256sum -c - \
    && unzip -q /tmp/android-tools.zip -d "${ANDROID_HOME}/cmdline-tools" \
    && mv "${ANDROID_HOME}/cmdline-tools/cmdline-tools" "${ANDROID_HOME}/cmdline-tools/latest" \
    && rm /tmp/android-tools.zip

# Android 17 platform is published as android-37.0 (NOT android-37).
# Current DFRoot uses Android Gradle Plugin 9.4, whose default NDK is r28.2.
RUN (yes || true) | sdkmanager --sdk_root="${ANDROID_HOME}" --licenses >/dev/null \
    && sdkmanager --sdk_root="${ANDROID_HOME}" --install \
         "platforms;android-37.0" \
         "build-tools;37.0.0" \
         "platform-tools" \
         "ndk;28.2.13676358" \
         "cmake;3.22.1" \
    && test -s "${ANDROID_HOME}/platforms/android-37.0/android.jar" \
    && test -x "${ANDROID_HOME}/ndk/28.2.13676358/ndk-build" \
    && test -x "${ANDROID_HOME}/cmake/3.22.1/bin/cmake"

WORKDIR /work
