# Vidda C3U — DFRoot + KernelSU Next, automated GitHub Actions builds

> **v4 repository edition — staged patchset, not yet a headless worker.**
> This ZIP includes the complete earlier GitHub Actions skeleton and ordered
> DFRoot integration scripts, plus a pinned-upstream source-inspection workflow.
> The Android 14 foreground service still **holds the process** while
> `MainActivity` dispatches the exploit. Moving the actual `IpSecManager`/JNI
> operation into the service is **not yet implemented or validated** because
> direct DFRoot source checkout was unavailable during packaging. See
> [service worker migration spec](docs/SERVICE-WORKER-MIGRATION.md) and the
> [patchset](patches/dfroot/patchset/README.md). The first GitHub Actions run
> fetches DFRoot v3.1 and produces the required source analysis artifact.
>

> **Experimental, device-specific build system.** This is not an official DFRoot or KernelSU Next release, and **CI cannot verify runtime compatibility**. Do not automatically install, load or flash its binaries. It targets only the exact Hisense firmware listed below.

This repository is ready to push to a fresh GitHub repository. It combines the earlier C3U v6 KernelSU Next build workaround with the single-KMI DFRoot APK integration, and uses GitHub Actions to build **candidate** `.ko` and `.apk` artifacts. A second workflow checks for **new stable KernelSU Next releases daily**, opens a review PR, and builds the new version for offline validation. It never auto-merges or auto-deploys to a projector.

## What Actions does

| Event | What happens |
| --- | --- |
| Push to `main`/`master` | Offline tests, C3U module build, modified DFRoot APK build, upload candidate artifacts |
| Pull request from this repository | Same build, with new version from PR; forks are excluded from the Docker build |
| **Daily at 04:23 UTC** | Check GitHub's latest **published stable** KernelSU Next release; propose a PR if newer; run a fresh candidate build |
| **Run workflow** (Build C3U candidates) | Build now, optionally choose a KernelSU tag, known-good `.ko`, or TV Settings UI fallback |

**No action installs anything on the C3U**. The scheduled update PR deliberately requires human review and manual device validation. A successful structure-layout check is **not** permission to load the `.ko` blindly; your earlier experiments produced kernel panics and watchdog resets.

## One-time GitHub setup

1. Create a new **empty** GitHub repository (no initialized README/license) and extract the archive contents **into its root**, including the hidden `.github/` folder.
2. Commit and push all files to the repository's `main` branch:

   ```bash
   git init
   git add .
   git commit -m "Add Vidda C3U build automation"
   git branch -M main
   git remote add origin https://github.com/YOUR_ACCOUNT/YOUR_REPOSITORY.git
   git push -u origin main
   ```

3. GitHub → your repo → **Actions**: check that workflows are enabled. Open **Build C3U candidates** to follow the first build; when it passes, download the artifact named `c3u-build-…` from that run.
4. For automatic update PRs, in repo **Settings → Actions → General → Workflow permissions**, allow **Read and write permissions** and **Allow GitHub Actions to create and approve pull requests** (if that setting is offered). GitHub may block bot-created PRs until you enable these settings. The workflows use only the built-in `GITHUB_TOKEN` and don't need a personal token.
5. In **Actions → Check upstream KernelSU Next**, choose **Run workflow** once to test the updater. Thereafter it runs daily. When a newer stable upstream tag appears, Actions opens a pull request and separately compiles the candidate in that same run.

If the repository is private, GitHub-hosted runners and artifact storage still follow the limits of your GitHub plan. The Docker build can be disk-intensive; build failure and logs are visible in Actions.

## Protected ADB-triggered Root (C3U integration)

**Foreground-service edition:** the modified APK can initiate DFRoot's existing Root action without navigating Android TV settings or pressing a button, while holding the app process in an Android 14-compatible foreground service:

```bash
adb shell am start -n df.root/.C3UAdbRootActivity
```

This launcher is protected by Android's `DUMP` permission (normally held by ADB shell). Once visible, it starts a non-exported foreground service with an ongoing notification, waits for an internal foreground-readiness acknowledgment, hands a single-use private token to `MainActivity`, and clicks the existing Root/Run Exploit button only when an unambiguous match is found. The foreground service keeps the DFRoot process less likely to be reclaimed by Android while the **C3U-v6 KernelSU** bootstrap runs; it stops after the module appears and a short stabilization interval, or after four minutes. This **does not move DirtyFrag into the service worker**: initial exploitation remains UI-assisted. A normal third-party launcher without shell/root permissions cannot trigger it.

Check `adb logcat -s C3UAdbRoot:I C3URootService:I` for the trigger and foreground-service status and **verify actual root** using `adb shell 'su -c id'`. An Activity starting or a DFRoot marker appearing isn't proof of root. See [docs/ADB-INTENT.md](docs/ADB-INTENT.md) for the host helper, protections, constraints, diagnostics and security notes. The GitHub build applies this patch by default; disable locally with `C3U_ENABLE_ADB_INTENT=0`.

## What gets built

- KernelSU Next LKM: `android14-5.15` only, with the C3U-specific v6 change that **preserves the firmware's normal SELinux permissive mode**.
- DDK Kconfig corrections (`KASAN=n`, no KABI/OEM reservations, different task and ARM64 options) that previously resolved known C3U struct-layout mismatches; build fails if these settings are ignored.
- Strict DWARF offline checks for `struct task_struct`, `struct mutex` and `struct selinux_state`.
- DFRoot native helper `.ko`: only `android14-5.15`, **not the other seven KMIs**.
- DFRoot APK: embeds the custom KSU module bytes, checks the exact firmware and kernel before attempted loading, and includes the interactive temporary root-shell fallback.
- Build manifest recording **resolved Git commit SHA**, requested upstream tag, module and APK SHA-256, and firmware target. Other diagnostics are uploaded with the artifacts.

The APK is built from **source obtained from upstream at build time**; the upstream source repositories are *not* vendored or submodules. No Android SDK or Docker image layers are committed into your repository.

### Exact target firmware

```
Linux 5.15.148-android14-11-g7b7674251b5d-dirty aarch64
Hisense/VIDAA_TV/MT9655:14/UQ1A.240105.004.A1/07.02.70.202512281739:user/release-keys
```

The integrated loader refuses other firmware fingerprints/kernel releases. Do **not** bypass this check to make it work on a different update.

## Important distinction: known-working v6 versus automatically rebuilt candidate

The KernelSU Next module that actually worked on your C3U was built from a particular Git `dev` revision reporting v3.4.1. **We do not have the exact revision hash or the exact working module in this generated repository.** The default `config/upstreams.json` pins the published `v3.4.1` tag for an initial **candidate build**. That tag may contain changes relative to your previously successful dev build; the result is **not automatically known-good**.

If you still have your personally tested v6 `.ko`, put it at:

```
known-good/working-v6.ko
```

Generate its checksum and commit both files:

```bash
shasum -a 256 known-good/working-v6.ko | awk '{print $1}' > known-good/working-v6.sha256
```

Then GitHub Actions → **Build C3U candidates → Run workflow → `use_known_good: true`**. That optional run embeds those exact bytes and checks the hash. The ordinary push and upstream-update builds continue compiling **new candidates**. This allows you to preserve the proven setup rather than silently replacing it with something untested.

You may also pin **exact commit SHAs** rather than tags in `config/upstreams.json` for maximum source reproducibility. The stable-release watcher expects a semantic version tag (`vX.Y.Z`) and will stop with a useful diagnostic if you choose an arbitrary SHA.

## Local builds, without GitHub

Requires x86-64 Docker (ARM64/macOS also works via x86-64 emulation, albeit more slowly), Git, Python 3 and Bash.

```bash
./tools/build-all.sh
```

Output in `dist/`:

```
KernelSU-Next-C3U-CANDIDATE.ko
DFRoot-C3U-CANDIDATE.apk
build-manifest.json
ksu-build/layout-report.txt
ksu-build/ddk-config-after.txt
```

To try another **published** upstream tag locally without editing config:

```bash
C3U_KSU_REF_OVERRIDE=v3.5.0 ./tools/build-all.sh
```

To use the optional known-good module locally:

```bash
C3U_USE_KNOWN_GOOD=1 ./tools/build-all.sh
```

For the experimental **DPAD-focusable Android TV Settings button** (not required for `su`), choose `tv_settings: true` in the manual workflow or locally:

```bash
C3U_ENABLE_TV_SETTINGS=1 ./tools/build-all.sh
```

The UI patch deliberately fails when DFRoot's Java Activity layout no longer matches the supported version. It is **disabled by default** because the projector's UI has not been tested with this modification.

### Upstream release updater (local/offline test)

```bash
python3 tools/check-upstream.py       # read-only version check
python3 tools/check-upstream.py --apply  # edits config/upstreams.json if newer
python3 -m unittest discover -s tests -v
```

`--apply` only updates a JSON file; building/installing remain separate. The default watcher tracks **stable GitHub Releases**, not arbitrary `dev` branch commits.

## Device and APK limitations

- **No genuinely headless first-stage DirtyFrag binary is included.** DFRoot's first-stage exploit still depends on its Android app and `IpSecManager`, but the new **permission-gated ADB Activity** can request its Root button automatically. The action is UI-assisted and may fail closed if DFRoot's UI changes. `c3u-root-stage2.sh` handles only the root-only second stage and cannot root a fresh boot on its own.
- The integrated DFRoot bootstrap currently expects a previously installed, compatible **`/data/adb/ksud`** from your successful KernelSU Next installation. It does not build or deploy a new `ksud` userspace binary with every release. A newer module may require a matching userspace version. The upstream-update PR must be reviewed for this too.
- The integrated C3U preloader and Android TV control have **not** been validated end-to-end on your projector. The manually loaded v6 module working does not prove the DFRoot integration works.
- The APK may be signed with an ephemeral CI key. A new build can require uninstall/reinstall if your existing DFRoot signature differs, losing its settings. If stable in-place app upgrades matter, use a persistent signing key and review DFRoot's signing configuration before deploying.
- Build artifacts remain available in GitHub Actions for 30 days. Neither the module nor APK is published as an automatic GitHub Release.
- Restrict ADB to trusted computers. The temporary-root fallback service is accessible to ADB shell UID outside KernelSU's per-app permission UI. The vendor kernel runs SELinux permissive by default, reducing isolation.

**Do not enable auto-loading at startup** until you have repeated manual tests, a backup, and a recovery path. A wrong `.ko` can hang/reboot or damage the firmware environment. Do not disable the hardware watchdog to mask a crash.

## Repository layout

```
.github/workflows/build.yml           main candidate CI, manual and reusable
.github/workflows/watch-ksunext.yml    daily stable-release PR + candidate build
config/upstreams.json                 pinned source tags, target firmware
patches/ksunext/                      C3U v6 source patch, DDK builder, ABI checks
patches/dfroot/                       v7.1 integration, Docker APK builder, optional TV UI
tools/build-all.sh                     local/CI build entrypoint
tools/check-upstream.py                release checker
known-good/                            optional device-proven module (YOU provide)
tests/                                 offline tests
```

## Upstream credits and licenses

This kit builds modified code from [DFRoot](https://github.com/diabl0w/DFRoot) and [KernelSU Next](https://github.com/KernelSU-Next/KernelSU-Next). Keep their original copyright and license notices. KernelSU Next's `/kernel` is GPL-2.0-only and other upstream components are GPL-3.0-or-later. The module and APK artifacts may have reciprocal source-distribution obligations; publish the exact patch sources and revision manifest alongside any binaries you distribute. See `NOTICE.md`.

## v4 patchset maintenance

`patches/dfroot/patchset/series.json` is the ordered patch manifest. The main
build calls `tools/inspect_dfroot_root_flow.py` immediately after checking out
DFRoot and uploads its source report inside the build artifact. A separate
**Inspect upstream DFRoot root execution** GitHub Actions workflow downloads
only DFRoot v3.1 Java/JNI paths for the next service migration.

To check that the ZIP is internally consistent before creating your repo:

```bash
python3 tools/check-patchset.py
python3 -m unittest discover -s tests -v
```

The build remains UI-assisted (even though ADB can trigger it); do not mark
it as a fully headless exploit yet. This is deliberately not an automatic
root-on-boot mechanism.

## CI native-build fix and caches (v5.1)

The initial workflow built the patched `android14-5.15` DFRoot kernel module,
then called Gradle without compiling DFRoot's JNI/CMake libraries. The v5
follow-up built the native targets but erroneously demanded a nonexistent
`libexp.so`; v5.1 corrects the packaging checks to match DFRoot v3.1. The APK
could be created without the exploit executable (`libdfroot.so`). In v5.1, the Android Docker stage explicitly
runs `patches/dfroot/build-native-in-docker.sh` **before** `assembleRelease` and
stages the ARM64 CMake results into `app/src/main/jniLibs/arm64-v8a/`.

The build now fails if the **final APK** lacks `libdfroot.so`, `libbootstrap.so`, `libdfrootsu.so`, or
its exact embedded C3U KernelSU module. CMake, Gradle and archive checks all
happen automatically within the existing Actions workflow.

Subsequent GitHub Actions builds restore three kinds of cache:

- Gradle downloads and wrapper: `.ci-cache/gradle` via `actions/cache`.
- Single-KMI DFRoot `.ko`: `.ci-cache/dfroot-ko`, keyed by upstream commit,
  KMI, DDK image and LKM source hashes.
- Android SDK Docker image layers: Buildx/GitHub Actions cache, scoped to
  `c3u-android-sdk`.

GitHub Actions runners remain ephemeral; the KSU compilation container and its
module compilation are not currently cached. Upstream source and patch changes
can invalidate caches. Builds remain **untested on the projector**.

**Upgrading an existing GitHub repo:** overlay the small `CI-Fix-v5-patch.zip`
archive at the repository root, commit and push. Do not add the known-working
KernelSU module to public CI unless you intend to publish that binary.
